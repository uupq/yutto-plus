#!/usr/bin/env python3
"""
yutto-plus - B站视频下载器
基于纯 HTTP API 实现，不依赖 yutto CLI 输出解析
"""

import asyncio
import httpx
import re
import json
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass
from enum import Enum
import subprocess


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"
    EXTRACTING = "extracting"
    DOWNLOADING = "downloading"
    MERGING = "merging"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class DownloadConfig:
    """下载配置"""
    sessdata: Optional[str] = None
    default_output_dir: str = "./downloads"
    default_quality: int = 80  # 1080P
    default_audio_quality: int = 30280  # 320kbps
    default_video_codec: str = "avc"
    default_audio_codec: str = "mp4a"
    default_output_format: str = "mp4"
    overwrite: bool = False
    # 新增弹幕相关配置
    require_danmaku: bool = True
    danmaku_format: str = "ass"  # xml, ass, protobuf
    require_video: bool = True
    require_audio: bool = True
    require_cover: bool = True
    # 新增音频相关配置
    audio_format: str = "mp3"  # mp3, wav, flac, m4a, aac
    audio_only: bool = False
    audio_bitrate: str = "192k"  # 音频比特率
    # 新增断点续传配置
    enable_resume: bool = True  # 启用断点续传


class BilibiliAPIClient:
    """B站 API 客户端"""
    
    def __init__(self, sessdata: Optional[str] = None):
        self.sessdata = sessdata
        self.session = None
    
    async def __aenter__(self):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com/"
        }
        
        cookies = {}
        if self.sessdata:
            cookies["SESSDATA"] = self.sessdata
        
        self.session = httpx.AsyncClient(
            headers=headers,
            cookies=cookies,
            timeout=30.0,
            follow_redirects=True
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.aclose()
    
    async def get_user_info(self):
        """获取用户信息，包括登录状态和会员状态"""
        info_api = "https://api.bilibili.com/x/web-interface/nav"
        response = await self.session.get(info_api)
        data = response.json()
        
        if data["code"] != 0:
            # 如果获取失败，返回默认值
            return {
                "vip_status": False,
                "is_login": False
            }
        
        res_json_data = data.get("data", {})
        return {
            "vip_status": res_json_data.get("vipStatus") == 1,  # API 返回的是 int，如果未登录就没这个值
            "is_login": res_json_data.get("isLogin", False),  # API 返回的是 bool
        }
    
    def extract_bv_info(self, url: str) -> Dict[str, Any]:
        """从 URL 中提取视频标识"""
        bv_match = re.search(r'BV([a-zA-Z0-9]+)', url)
        if bv_match:
            return {"bvid": f"BV{bv_match.group(1)}", "aid": None}
        
        av_match = re.search(r'av(\d+)', url)
        if av_match:
            return {"bvid": None, "aid": int(av_match.group(1))}
        
        raise ValueError(f"无法解析视频 URL: {url}")
    
    async def get_video_info(self, url: str) -> Dict[str, Any]:
        """获取视频基本信息"""
        video_id = self.extract_bv_info(url)
        
        if video_id["bvid"]:
            api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={video_id['bvid']}"
        else:
            api_url = f"https://api.bilibili.com/x/web-interface/view?aid={video_id['aid']}"
        
        response = await self.session.get(api_url)
        data = response.json()
        
        if data["code"] != 0:
            raise Exception(f"获取视频信息失败: {data['message']}")
        
        video_data = data["data"]
        return {
            "title": video_data["title"],
            "uploader": video_data["owner"]["name"],
            "bvid": video_data["bvid"],
            "aid": video_data["aid"],
            "duration": video_data["duration"],
            "description": video_data["desc"],
            "pic": video_data["pic"],
            "pages": video_data["pages"]
        }
    
    async def get_playurl(self, aid: int, bvid: str, cid: int) -> tuple[List[Dict], List[Dict]]:
        """获取播放地址"""
        api_url = f"https://api.bilibili.com/x/player/playurl?avid={aid}&bvid={bvid}&cid={cid}&qn=127&fnval=4048&fourk=1"
        
        response = await self.session.get(api_url)
        data = response.json()
        
        if data["code"] != 0:
            raise Exception(f"获取播放地址失败: {data['message']}")
        
        play_data = data["data"]
        
        if not play_data.get("dash"):
            raise Exception("该视频不支持 DASH 格式")
        
        # 解析视频流
        videos = []
        if play_data["dash"].get("video"):
            for video in play_data["dash"]["video"]:
                videos.append({
                    "url": video["base_url"],
                    "codec": self._get_codec_name(video["codecid"]),
                    "width": video["width"],
                    "height": video["height"],
                    "quality": video["id"],
                    "bandwidth": video.get("bandwidth", 0)
                })
        
        # 解析音频流
        audios = []
        if play_data["dash"].get("audio"):
            for audio in play_data["dash"]["audio"]:
                audios.append({
                    "url": audio["base_url"],
                    "codec": "mp4a",
                    "quality": audio["id"],
                    "bandwidth": audio.get("bandwidth", 0)
                })
        
        return videos, audios
    
    async def get_xml_danmaku(self, cid: int) -> str:
        """获取 XML 格式弹幕"""
        danmaku_api = f"http://comment.bilibili.com/{cid}.xml"
        response = await self.session.get(danmaku_api)
        response.encoding = "utf-8"
        return response.text
    
    async def get_protobuf_danmaku_meta(self, aid: int, cid: int) -> int:
        """获取 protobuf 弹幕元数据，返回分段数量"""
        danmaku_meta_api = f"https://api.bilibili.com/x/v2/dm/web/view?type=1&oid={cid}&pid={aid}"
        response = await self.session.get(danmaku_meta_api)
        meta_data = response.content
        
        # 简单解析分段数量（这里简化处理，实际需要解析 protobuf）
        # 对于大部分视频，分段数量为 1
        return 1
    
    async def get_protobuf_danmaku_segment(self, cid: int, segment_id: int = 1) -> bytes:
        """获取单个 protobuf 弹幕分段"""
        danmaku_api = f"http://api.bilibili.com/x/v2/dm/web/seg.so?type=1&oid={cid}&segment_index={segment_id}"
        response = await self.session.get(danmaku_api)
        return response.content
    
    async def get_protobuf_danmaku(self, aid: int, cid: int) -> List[bytes]:
        """获取完整的 protobuf 弹幕数据"""
        segment_count = await self.get_protobuf_danmaku_meta(aid, cid)
        
        segments = []
        for i in range(1, segment_count + 1):
            segment = await self.get_protobuf_danmaku_segment(cid, i)
            segments.append(segment)
        
        return segments
    
    async def get_danmaku(self, aid: int, cid: int, user_info: Dict = None) -> Dict:
        """获取弹幕数据，根据登录状态选择格式"""
        if user_info and user_info.get("is_login", False):
            # 已登录，使用 protobuf 格式获取更多弹幕
            print(f"📝 [弹幕获取] 已登录用户，使用 protobuf 格式")
            data = await self.get_protobuf_danmaku(aid, cid)
            return {
                "source_type": "protobuf",
                "data": data
            }
        else:
            # 未登录，使用 XML 格式
            print(f"📝 [弹幕获取] 未登录用户，使用 XML 格式")
            data = await self.get_xml_danmaku(cid)
            return {
                "source_type": "xml",
                "data": [data]
            }
    
    async def get_cover_data(self, pic_url: str) -> bytes:
        """下载封面图片"""
        response = await self.session.get(pic_url)
        return response.content
    
    def _get_codec_name(self, codecid: int) -> str:
        """获取编码名称"""
        codec_map = {7: "avc", 12: "hevc", 13: "av1"}
        return codec_map.get(codecid, f"unknown_{codecid}")


class DownloadTask:
    """单个下载任务"""
    
    def __init__(self, url: str, config: DownloadConfig, task_config: Dict[str, Any] = None):
        self.url = url
        self.config = config
        self.task_config = task_config or {}
        self.status = TaskStatus.PENDING
        
        # 任务信息
        self.video_info = None
        self.selected_video = None
        self.selected_audio = None
        self.output_filepath = None
        self.error_message = None
        
        # 新增数据字段
        self.danmaku_data = None
        self.cover_data = None
        
        # 进度跟踪
        self._progress_callback = None
        self._completion_callback = None
        self._download_thread = None
        
        # 多流进度管理
        self._stream_progress = {}  # 存储每个流的进度信息
        self._total_size = 0  # 所有流的总大小
        self._last_report_time = 0  # 上次报告时间
        
        # 流信息回调
        self._stream_info_callback = None
        
    def start(self, progress_callback: Optional[Callable] = None, 
              completion_callback: Optional[Callable] = None,
              stream_info_callback: Optional[Callable] = None):
        """开始下载"""
        self._progress_callback = progress_callback
        self._completion_callback = completion_callback
        self._stream_info_callback = stream_info_callback
        
        # 启动下载线程
        self._start_download_thread()
    
    def _start_download_thread(self):
        """启动下载线程前的准备工作"""
        # 在新线程中执行下载
        self._download_thread = threading.Thread(target=self._run_download, daemon=True)
        self._download_thread.start()
    
    def _update_stream_progress(self, stream_id: str, current_bytes: int, total_bytes: int, speed_bps: float):
        """更新单个流的进度并计算总体进度"""
        import time
        
        # 更新流进度
        self._stream_progress[stream_id] = {
            'current': current_bytes,
            'total': total_bytes,
            'speed': speed_bps
        }
        
        # 计算总体进度 - 确保所有流都被计入
        total_current = 0
        total_size = 0
        
        for stream_id, progress in self._stream_progress.items():
            total_current += progress['current']
            total_size += progress['total']
        
        # 计算平均速度
        total_speed = sum(p['speed'] for p in self._stream_progress.values())
        
        # 限制报告频率（每0.5秒最多报告一次）
        current_time = time.time()
        if current_time - self._last_report_time >= 0.5:
            if self._progress_callback and total_size > 0:
                # 确保进度不超过100%
                progress_percentage = min(100.0, (total_current / total_size * 100))
                
                self._progress_callback(
                    current_bytes=total_current,
                    total_bytes=total_size,
                    speed_bps=total_speed,
                    item_name=f"下载中 - {self.video_info['title']}"
                )
            self._last_report_time = current_time
    
    def _run_download(self):
        """运行下载（在独立线程中）"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._async_download())
        except Exception as e:
            self.error_message = str(e)
            self.status = TaskStatus.FAILED
            if self._completion_callback:
                self._completion_callback(False, None, self.error_message)
        finally:
            loop.close()
    
    async def _async_download(self):
        """异步下载实现"""
        try:
            # 1. 获取视频信息
            self.status = TaskStatus.EXTRACTING
            print(f"🔍 [信息提取] 正在分析视频: {self.url}")
            
            async with BilibiliAPIClient(self.config.sessdata) as client:
                self.video_info = await client.get_video_info(self.url)
                
                print(f"✅ [视频解析] 成功获取视频信息:")
                print(f"    📰 标题: {self.video_info['title']}")
                print(f"    👤 UP主: {self.video_info['uploader']}")
                print(f"    🆔 BV号: {self.video_info['bvid']}")
                print(f"    ⏰ 时长: {self.video_info['duration']} 秒")
                
                # 初始化输出目录和文件名
                output_dir = Path(self.task_config.get('output_dir', self.config.default_output_dir))
                output_dir.mkdir(parents=True, exist_ok=True)
                filename = re.sub(r'[<>:"/\\|?*]', '_', self.video_info['title'])
                self._output_dir = output_dir
                self._filename = filename
                
                # 获取用户信息（用于弹幕下载）
                user_info = None
                if self.config.sessdata:
                    try:
                        user_info = await client.get_user_info()
                    except:
                        user_info = {"is_login": False, "vip_status": False}
                
                # 获取播放地址
                page = self.video_info['pages'][0]
                cid = page['cid']
                
                # 根据配置决定下载什么内容
                require_video = self.task_config.get('require_video', self.config.require_video)
                require_audio = self.task_config.get('require_audio', self.config.require_audio)
                require_danmaku = self.task_config.get('require_danmaku', self.config.require_danmaku)
                require_cover = self.task_config.get('require_cover', self.config.require_cover)
                
                # 检查是否需要下载任何内容
                if not any([require_video, require_audio, require_danmaku, require_cover]):
                    raise Exception("没有选择任何下载内容")
                
                videos, audios = [], []
                if require_video or require_audio:
                    videos, audios = await client.get_playurl(
                        self.video_info['aid'],
                        self.video_info['bvid'],
                        cid
                    )
                
                # 选择最佳流（如果需要）
                if require_video:
                    self.selected_video = self._select_best_video(videos)
                if require_audio:
                    self.selected_audio = self._select_best_audio(audios)
                
                print(f"🎯 [流选择] 已选择内容:")
                if self.selected_video:
                    print(f"    🎥 视频: {self.selected_video['codec'].upper()} {self.selected_video['width']}x{self.selected_video['height']}")
                if self.selected_audio:
                    print(f"    🔊 音频: {self.selected_audio['codec'].upper()} 质量:{self.selected_audio['quality']}")
                
                # 下载弹幕
                if require_danmaku:
                    print(f"📝 [弹幕下载] 正在下载弹幕...")
                    self.danmaku_data = await client.get_danmaku(
                        self.video_info['aid'],
                        cid,
                        user_info
                    )
                    print(f"✅ [弹幕下载] 弹幕下载完成 ({self.danmaku_data['source_type']} 格式)")
                
                # 下载封面
                if require_cover:
                    print(f"🖼️ [封面下载] 正在下载封面...")
                    self.cover_data = await client.get_cover_data(self.video_info['pic'])
                    print(f"✅ [封面下载] 封面下载完成 ({len(self.cover_data)} 字节)")
                
                # 立即通知流信息可用
                if self._stream_info_callback:
                    stream_info = self.get_selected_streams_info()
                    if stream_info:
                        self._stream_info_callback(stream_info)
                
                # 2. 开始下载媒体文件
                if require_video or require_audio:
                    self.status = TaskStatus.DOWNLOADING
                    await self._download_streams(client)
                    
                    # 3. 合并文件
                    self.status = TaskStatus.MERGING
                    
                    # 通知合并状态
                    if self._stream_info_callback:
                        # 根据模式显示不同的状态
                        audio_only = self.task_config.get('audio_only', False)
                        if audio_only:
                            self._stream_info_callback({'status': 'merging', 'message': '正在转换音频格式...'})
                        else:
                            self._stream_info_callback({'status': 'merging', 'message': '正在合并音视频...'})
                    
                    await self._merge_streams()
                
                # 4. 保存弹幕和封面
                await self._save_additional_files()
                
                # 5. 完成
                self.status = TaskStatus.COMPLETED
                print(f"🎉 [下载完成] 所有内容已保存完毕")
                
                if self._completion_callback:
                    result_info = self._build_result_info()
                    self._completion_callback(True, result_info, None)
                    
        except Exception as e:
            self.error_message = str(e)
            self.status = TaskStatus.FAILED
            print(f"❌ [下载失败] {self.error_message}")
            if self._completion_callback:
                self._completion_callback(False, None, self.error_message)
    
    def _select_best_video(self, videos: List[Dict]) -> Optional[Dict]:
        """选择最佳视频流"""
        if not videos:
            return None
        
        target_quality = self.task_config.get('quality', self.config.default_quality)
        codec_preference = self.task_config.get('video_codec', self.config.default_video_codec)
        
        # 按质量和编码偏好排序
        def score_video(v):
            codec_score = 10 if v['codec'] == codec_preference else 0
            quality_score = abs(v['quality'] - target_quality)
            return codec_score - quality_score
        
        return max(videos, key=score_video)
    
    def _select_best_audio(self, audios: List[Dict]) -> Optional[Dict]:
        """选择最佳音频流"""
        if not audios:
            return None
        
        target_quality = self.task_config.get('audio_quality', self.config.default_audio_quality)
        
        # 选择最接近目标质量的音频流
        return min(audios, key=lambda a: abs(a['quality'] - target_quality))
    
    async def _get_stream_size_with_retry(self, client: BilibiliAPIClient, url: str, existing_size: int = 0, max_retries: int = 3) -> tuple[int, bool]:
        """获取流大小，使用yutto的Range请求方案"""
        for attempt in range(max_retries):
            try:
                if existing_size > 0:
                    # 断点续传情况：检查文件完整性
                    headers = {'Range': f'bytes={existing_size}-{existing_size}'}
                    response = await client.session.get(url, headers=headers)
                    
                    if response.status_code == 416:
                        # 文件已完整，使用Range请求获取大小
                        headers = {'Range': 'bytes=0-1'}
                        test_response = await client.session.get(url, headers=headers)
                        if test_response.status_code == 206:
                            content_range = test_response.headers.get('content-range')
                            if content_range and '/' in content_range:
                                total_size = int(content_range.split('/')[-1])
                                return total_size, True
                        return existing_size, True  # 保守处理
                    elif response.status_code == 206:
                        # 从Content-Range获取总大小
                        content_range = response.headers.get('content-range')
                        if content_range and '/' in content_range:
                            total_size = int(content_range.split('/')[-1])
                            completed = existing_size >= total_size
                            return total_size, completed
                        else:
                            raise Exception("无法从Content-Range获取大小")
                    else:
                        raise Exception(f"Range请求失败: {response.status_code}")
                else:
                    # 新下载：使用yutto的方案
                    # 方法1: Range请求获取前2字节（最可靠）
                    try:
                        headers = {'Range': 'bytes=0-1'}
                        response = await client.session.get(url, headers=headers)
                        if response.status_code == 206:
                            content_range = response.headers.get('content-range')
                            if content_range and '/' in content_range:
                                total_size = int(content_range.split('/')[-1])
                                if total_size > 0:
                                    return total_size, False
                        elif response.status_code == 200:
                            # 服务器不支持Range，从Content-Length获取
                            total_size = int(response.headers.get('content-length', 0))
                            if total_size > 0:
                                return total_size, False
                    except Exception:
                        pass
                    
                    # 方法2: HEAD请求（备用方案）
                    try:
                        response = await client.session.head(url)
                        total_size = int(response.headers.get('content-length', 0))
                        if total_size > 0:
                            return total_size, False
                    except Exception:
                        pass
                    
                    # 方法3: Range请求获取前1KB（最后备用）
                    try:
                        headers = {'Range': 'bytes=0-1023'}
                        response = await client.session.get(url, headers=headers)
                        if response.status_code == 206:
                            content_range = response.headers.get('content-range')
                            if content_range and '/' in content_range:
                                total_size = int(content_range.split('/')[-1])
                                if total_size > 0:
                                    return total_size, False
                    except Exception:
                        pass
                    
                    # 如果所有方法都失败
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1)  # 等待1秒后重试
                        continue
                    else:
                        raise Exception("所有获取大小的方法都失败了")
                        
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                else:
                    raise Exception(f"获取流大小失败（已重试{max_retries}次）: {e}")
        
        raise Exception("获取流大小失败")

    async def _download_streams(self, client: BilibiliAPIClient):
        """下载视频和音频流"""
        output_dir = Path(self.task_config.get('output_dir', self.config.default_output_dir))
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 清理文件名
        filename = re.sub(r'[<>:"/\\|?*]', '_', self.video_info['title'])
        
        tasks = []
        temp_files = []
        
        # 清空进度跟踪，重新开始
        self._stream_progress = {}
        
        # 预先获取所有流的大小信息
        stream_info = []
        
        print(f"🔍 正在检测文件大小...")
        
        # 准备视频流信息（如果需要）
        audio_only = self.task_config.get('audio_only', False)
        
        if self.selected_video and not audio_only:
            video_path = output_dir / f"{filename}_video.m4s"
            temp_files.append(video_path)
            
            # 获取视频流大小
            existing_size = 0
            if self.config.enable_resume and not self.config.overwrite and video_path.exists():
                existing_size = video_path.stat().st_size
            
            try:
                total_size, completed = await self._get_stream_size_with_retry(
                    client, self.selected_video['url'], existing_size
                )
                
                if completed:
                    print(f"✅ 视频流已完整: {total_size / (1024*1024):.1f} MB")
                else:
                    if existing_size > 0:
                        print(f"📹 视频流: {total_size / (1024*1024):.1f} MB (已下载: {existing_size / (1024*1024):.1f} MB)")
                    else:
                        print(f"📹 视频流: {total_size / (1024*1024):.1f} MB")
                
                stream_info.append({
                    'type': '视频流',
                    'path': video_path,
                    'url': self.selected_video['url'],
                    'existing_size': existing_size,
                    'total_size': total_size,
                    'completed': completed
                })
            except Exception as e:
                raise Exception(f"获取视频流大小失败: {e}")
        
        # 准备音频流信息（如果需要）
        if self.selected_audio:
            audio_path = output_dir / f"{filename}_audio.m4s"
            temp_files.append(audio_path)
            
            # 获取音频流大小
            existing_size = 0
            if self.config.enable_resume and not self.config.overwrite and audio_path.exists():
                existing_size = audio_path.stat().st_size
            
            try:
                total_size, completed = await self._get_stream_size_with_retry(
                    client, self.selected_audio['url'], existing_size
                )
                
                if completed:
                    print(f"✅ 音频流已完整: {total_size / (1024*1024):.1f} MB")
                else:
                    if existing_size > 0:
                        print(f"🔊 音频流: {total_size / (1024*1024):.1f} MB (已下载: {existing_size / (1024*1024):.1f} MB)")
                    else:
                        print(f"🔊 音频流: {total_size / (1024*1024):.1f} MB")
                
                stream_info.append({
                    'type': '音频流',
                    'path': audio_path,
                    'url': self.selected_audio['url'],
                    'existing_size': existing_size,
                    'total_size': total_size,
                    'completed': completed
                })
            except Exception as e:
                raise Exception(f"获取音频流大小失败: {e}")
        
        if not stream_info:
            raise Exception("没有流需要下载")
        
        # 计算总大小和已下载大小
        total_size_all = sum(info['total_size'] for info in stream_info)
        total_existing_all = sum(info['existing_size'] for info in stream_info)
        
        # 显示文件信息
        print(f"📊 总大小: {total_size_all / (1024*1024):.1f} MB")
        if total_existing_all > 0:
            print(f"🔄 已下载: {total_existing_all / (1024*1024):.1f} MB ({total_existing_all/total_size_all*100:.1f}%)")
        
        # 检查是否所有流都已完成
        total_completed = sum(1 for info in stream_info if info['completed'])
        if total_completed == len(stream_info):
            print(f"✅ 视频已完整下载，跳过下载步骤")
            # 设置进度信息
            for info in stream_info:
                stream_id = f"{info['type']}_{info['path'].name}"
                self._stream_progress[stream_id] = {
                    'current': info['total_size'],
                    'total': info['total_size'],
                    'speed': 0
                }
        else:
            # 开始下载
            print(f"📥 开始下载视频...")
            
            # 检查是否有断点续传
            has_resume = any(info['existing_size'] > 0 and not info['completed'] for info in stream_info)
            if has_resume:
                print(f"🔄 检测到断点续传，继续下载")
            
            # 初始化所有流的进度信息
            for info in stream_info:
                stream_id = f"{info['type']}_{info['path'].name}"
                self._stream_progress[stream_id] = {
                    'current': info['existing_size'],
                    'total': info['total_size'],
                    'speed': 0
                }
            
            # 开始并发下载所有未完成的流
            for info in stream_info:
                if not info['completed']:
                    tasks.append(self._download_single_stream_with_info(client, info))
            
            # 并发下载所有流
            if tasks:
                await asyncio.gather(*tasks)
        
        # 验证所有流都有进度信息
        if not self._stream_progress:
            raise Exception("没有任何流被下载")
        
        # 设置临时文件路径
        self._temp_files = temp_files
        self._filename = filename
        self._output_dir = output_dir
        
        # 输出最终下载统计
        total_downloaded = sum(p['current'] for p in self._stream_progress.values())
        print(f"✅ 下载完成: {total_downloaded / (1024*1024):.1f} MB")
    
    async def _download_single_stream_with_info(self, client: BilibiliAPIClient, info: Dict):
        """使用预获取信息下载单个流"""
        stream_type = info['type']
        output_path = info['path']
        url = info['url']
        existing_size = info['existing_size']
        total_size = info['total_size']
        
        # 生成流ID
        stream_id = f"{stream_type}_{output_path.name}"
        
        # 如果已完整下载，直接设置进度并跳过
        if info['completed']:
            self._stream_progress[stream_id] = {
                'current': total_size,
                'total': total_size,
                'speed': 0
            }
            return
        
        try:
            # 开始实际下载
            current_size = existing_size
            start_time = time.time()
            last_speed_calc = start_time
            
            # 设置下载的Range头（如果需要）
            headers = {}
            if existing_size > 0:
                headers['Range'] = f'bytes={existing_size}-'
            
            # 选择文件打开模式
            file_mode = 'ab' if existing_size > 0 else 'wb'
            
            async with client.session.stream('GET', url, headers=headers) as response:
                response.raise_for_status()
                
                with open(output_path, file_mode) as f:
                    async for chunk in response.aiter_bytes(chunk_size=8192):
                        f.write(chunk)
                        current_size += len(chunk)
                        
                        # 计算速度（只计算本次下载的速度）
                        current_time = time.time()
                        if current_time > last_speed_calc:
                            speed = (current_size - existing_size) / (current_time - start_time)
                        else:
                            speed = 0
                        
                        # 更新进度
                        self._update_stream_progress(stream_id, current_size, total_size, speed)
                        
                        last_speed_calc = current_time
        
        except Exception as e:
            print(f"❌ [下载失败] 网络错误: {e}")
            # 如果下载失败，仍需要设置进度信息避免计算错误
            if stream_id not in self._stream_progress:
                self._stream_progress[stream_id] = {
                    'current': existing_size,
                    'total': existing_size,  # 使用已下载大小作为总大小
                    'speed': 0
                }
            raise
        
        # 下载完成后，确保总大小是准确的
        self._stream_progress[stream_id]['total'] = total_size
        self._stream_progress[stream_id]['current'] = current_size
    
    async def _merge_streams(self):
        """合并音视频流"""
        print(f"🔄 [文件合并] 正在合并音视频...")
        
        # 检查是否为仅音频模式
        audio_only = self.task_config.get('audio_only', False)
        audio_format = self.task_config.get('audio_format', 'mp3')
        
        if audio_only and len(self._temp_files) == 1:
            # 仅音频模式，需要转换格式
            print(f"🎵 [音频模式] 转换为 {audio_format.upper()} 格式")
            self.output_filepath = self._output_dir / f"{self._filename}.{audio_format}"
            
            # 获取音频比特率设置
            audio_bitrate = self.task_config.get('audio_bitrate', '192k')
            
            # 构建 FFmpeg 音频转换命令
            input_file = self._temp_files[0]
            cmd = ["ffmpeg", "-y", "-i", str(input_file)]
            
            # 强制禁用视频流和字幕流，只处理音频
            cmd.extend(["-vn", "-sn"])
            
            # 根据音频格式设置编码参数
            if audio_format == 'mp3':
                cmd.extend(["-codec:a", "libmp3lame", "-b:a", audio_bitrate, "-ar", "44100"])
            elif audio_format == 'wav':
                cmd.extend(["-codec:a", "pcm_s16le", "-ar", "44100"])
            elif audio_format == 'flac':
                cmd.extend(["-codec:a", "flac", "-ar", "44100"])
            elif audio_format == 'm4a':
                cmd.extend(["-codec:a", "aac", "-b:a", audio_bitrate, "-ar", "44100"])
            elif audio_format == 'aac':
                cmd.extend(["-codec:a", "aac", "-b:a", audio_bitrate, "-ar", "44100"])
            else:
                # 默认复制音频，但仍然禁用视频
                cmd.extend(["-codec:a", "copy"])
            
            # 添加其他优化参数
            cmd.extend(["-map", "0:a:0"])  # 只映射第一个音频流
            cmd.append(str(self.output_filepath))
            
            print(f"    🔧 FFmpeg 音频命令: {' '.join(cmd)}")
            
        else:
            # 视频模式或多流模式
            output_format = self.task_config.get('output_format', self.config.default_output_format)
            self.output_filepath = self._output_dir / f"{self._filename}.{output_format}"
            
            # 检查可用的临时文件
            available_files = [f for f in self._temp_files if f.exists()]
            
            if not available_files:
                raise Exception("没有可用的流文件进行合并")
            
            # 构建 FFmpeg 命令
            cmd = ["ffmpeg", "-y"]  # -y 覆盖输出文件
            
            # 添加输入文件
            for temp_file in available_files:
                cmd.extend(["-i", str(temp_file)])
            
            # 根据文件数量决定输出设置
            if len(available_files) == 1:
                # 只有一个流，直接复制
                cmd.extend(["-c", "copy", str(self.output_filepath)])
                print(f"    📝 单流模式: 直接复制 {available_files[0].name}")
            else:
                # 多个流，需要合并
                cmd.extend([
                    "-c:v", "copy",  # 视频流复制
                    "-c:a", "copy",  # 音频流复制
                    str(self.output_filepath)
                ])
                print(f"    📝 合并模式: 合并 {len(available_files)} 个流")
            
            print(f"    🔧 FFmpeg 命令: {' '.join(cmd)}")
        
        # 执行合并/转换
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise Exception(f"FFmpeg 处理失败: {result.stderr}")
        
        # 清理临时文件
        for temp_file in self._temp_files:
            if temp_file.exists():
                temp_file.unlink()
        
        print(f"✅ [合并完成] 输出文件: {self.output_filepath}")
    
    def _get_quality_desc(self, quality_id: int) -> str:
        """获取画质描述"""
        quality_map = {
            127: "8K 超高清", 120: "4K 超清", 116: "1080P60", 
            80: "1080P 高清", 64: "720P 高清", 32: "480P 清晰", 16: "360P 流畅"
        }
        return quality_map.get(quality_id, f"质量{quality_id}")
    
    def _get_audio_quality_desc(self, quality_id: int) -> str:
        """获取音质描述"""
        quality_map = {
            30280: "320kbps", 30232: "128kbps", 30216: "64kbps"
        }
        return quality_map.get(quality_id, f"音质{quality_id}")
    
    def get_status(self) -> TaskStatus:
        """获取任务状态"""
        return self.status
    
    def get_selected_streams_info(self) -> Dict[str, str]:
        """获取选中的流信息"""
        if not self.selected_video and not self.selected_audio:
            return {}
        
        info = {}
        if self.selected_video:
            info["selected_video_stream_info"] = f"[{self.selected_video['codec'].upper()}] [{self.selected_video['width']}x{self.selected_video['height']}] <{self._get_quality_desc(self.selected_video['quality'])}>"
        
        if self.selected_audio:
            info["selected_audio_stream_info"] = f"[{self.selected_audio['codec'].upper()}] <{self._get_audio_quality_desc(self.selected_audio['quality'])}>"
        
        return info

    def _build_result_info(self):
        """构建结果信息"""
        result_info = {}
        
        # 添加输出文件路径（如果有）
        if hasattr(self, 'output_filepath') and self.output_filepath:
            result_info["output_filepath"] = str(self.output_filepath)
        else:
            result_info["output_filepath"] = f"{self._output_dir}/{self._filename} (仅下载附加文件)"
        
        # 安全地添加流信息
        if self.selected_video:
            result_info["selected_video_stream_info"] = f"[{self.selected_video['codec'].upper()}] [{self.selected_video['width']}x{self.selected_video['height']}] <{self._get_quality_desc(self.selected_video['quality'])}>"
        else:
            result_info["selected_video_stream_info"] = "无视频流"
        
        if self.selected_audio:
            result_info["selected_audio_stream_info"] = f"[{self.selected_audio['codec'].upper()}] <{self._get_audio_quality_desc(self.selected_audio['quality'])}>"
        else:
            result_info["selected_audio_stream_info"] = "无音频流"
        
        # 添加附加文件信息
        additional_files = []
        if self.danmaku_data:
            additional_files.append("弹幕")
        if self.cover_data:
            additional_files.append("封面")
        if additional_files:
            result_info["additional_files"] = ", ".join(additional_files)
        
        return result_info

    async def _save_additional_files(self):
        """保存弹幕和封面"""
        if self.danmaku_data:
            print(f"📝 [弹幕保存] 正在保存弹幕...")
            
            # 根据弹幕数据类型和格式保存
            if self.danmaku_data['source_type'] == 'xml':
                danmaku_path = self._output_dir / f"{self._filename}.xml"
                with open(danmaku_path, 'w', encoding='utf-8') as f:
                    f.write(self.danmaku_data['data'][0])
            else:  # protobuf
                if len(self.danmaku_data['data']) == 1:
                    danmaku_path = self._output_dir / f"{self._filename}.pb"
                    with open(danmaku_path, 'wb') as f:
                        f.write(self.danmaku_data['data'][0])
                else:
                    # 多个分段
                    for i, segment in enumerate(self.danmaku_data['data']):
                        danmaku_path = self._output_dir / f"{self._filename}_danmaku_{i:02d}.pb"
                        with open(danmaku_path, 'wb') as f:
                            f.write(segment)
            
            print(f"✅ [弹幕保存] 弹幕保存完成")
        
        if self.cover_data:
            print(f"🖼️ [封面保存] 正在保存封面...")
            # 从 URL 获取文件扩展名，默认为 jpg
            cover_ext = "jpg"
            if self.video_info.get('pic'):
                pic_url = self.video_info['pic']
                if '.' in pic_url:
                    cover_ext = pic_url.split('.')[-1].split('?')[0]
            
            cover_path = self._output_dir / f"{self._filename}.{cover_ext}"
            with open(cover_path, 'wb') as f:
                f.write(self.cover_data)
            print(f"✅ [封面保存] 封面保存完成 ({cover_path})")


class YuttoPlus:
    """主下载器类"""
    
    def __init__(self, **config):
        """初始化下载器
        
        Args:
            sessdata: B站 SESSDATA cookie
            default_output_dir: 默认下载目录
            default_quality: 默认视频质量
            default_audio_quality: 默认音频质量
            default_video_codec: 默认视频编码偏好
            default_audio_codec: 默认音频编码偏好
            default_output_format: 默认输出格式
            overwrite: 是否覆盖已存在文件
        """
        self.config = DownloadConfig(**config)
        print(f"🚀 [初始化] YuttoPlus 已初始化")
        print(f"    📁 输出目录: {self.config.default_output_dir}")
        print(f"    🎥 默认画质: {self.config.default_quality}")
        print(f"    🔊 默认音质: {self.config.default_audio_quality}")
        
        # 验证用户登录状态
        if self.config.sessdata:
            self._validate_user_info()
        else:
            print("ℹ️ [登录状态] 未提供 SESSDATA，无法下载高清视频、字幕等资源")
    
    def _validate_user_info(self):
        """验证用户信息（同步方法，用于初始化时调用）"""
        try:
            # 在新的事件循环中运行异步验证
            import threading
            
            result = {"done": False, "user_info": None, "error": None}
            
            def validation_thread():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    async def validate():
                        async with BilibiliAPIClient(self.config.sessdata) as client:
                            return await client.get_user_info()
                    
                    user_info = loop.run_until_complete(validate())
                    result["user_info"] = user_info
                    result["done"] = True
                    
                except Exception as e:
                    result["error"] = str(e)
                    result["done"] = True
                finally:
                    loop.close()
            
            thread = threading.Thread(target=validation_thread, daemon=True)
            thread.start()
            thread.join(timeout=10)  # 10秒超时
            
            if result["done"] and result["user_info"]:
                user_info = result["user_info"]
                if user_info["is_login"]:
                    if user_info["vip_status"]:
                        print("🎖️ [登录状态] ✅ 成功以大会员身份登录～")
                    else:
                        print("👤 [登录状态] ✅ 登录成功，以非大会员身份登录")
                        print("⚠️ [提示] 注意无法下载会员专享剧集和最高画质")
                else:
                    print("❌ [登录状态] SESSDATA 无效或已过期，请检查后重试")
            elif result["error"]:
                print(f"⚠️ [登录状态] 验证失败: {result['error']}")
            else:
                print("⚠️ [登录状态] 验证超时，将继续使用提供的 SESSDATA")
                
        except Exception as e:
            print(f"⚠️ [登录状态] 验证过程出错: {e}")
    
    def create_download_task(self, url: str, **kwargs) -> DownloadTask:
        """创建下载任务
        
        Args:
            url: B站视频链接
            **kwargs: 覆盖默认配置的参数
        
        Returns:
            DownloadTask: 下载任务实例
        """
        print(f"📋 [创建任务] 目标URL: {url}")
        if kwargs:
            print(f"    ⚙️  任务配置: {kwargs}")
        
        return DownloadTask(url, self.config, kwargs) 