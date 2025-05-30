#!/usr/bin/env python3
"""
YuttoDownloader - B站视频下载器
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
        
        # 进度跟踪
        self._progress_callback = None
        self._completion_callback = None
        self._download_thread = None
        
        # 多流进度管理
        self._stream_progress = {}  # 存储每个流的进度信息
        self._total_size = 0  # 所有流的总大小
        self._last_report_time = 0  # 上次报告时间
        
    def start(self, progress_callback: Optional[Callable] = None, 
              completion_callback: Optional[Callable] = None):
        """开始下载"""
        self._progress_callback = progress_callback
        self._completion_callback = completion_callback
        
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
        
        # 计算总体进度
        total_current = sum(p['current'] for p in self._stream_progress.values())
        total_size = sum(p['total'] for p in self._stream_progress.values())
        
        # 计算平均速度
        total_speed = sum(p['speed'] for p in self._stream_progress.values())
        
        # 限制报告频率（每0.5秒最多报告一次）
        current_time = time.time()
        if current_time - self._last_report_time >= 0.5:
            if self._progress_callback and total_size > 0:
                self._progress_callback(
                    current_bytes=total_current,
                    total_bytes=total_size,
                    speed_bps=total_speed,
                    item_name=f"下载中 - {self.video_info['title']}"
                )
            self._last_report_time = current_time
            
            # 打印调试信息
            percentage = (total_current / total_size * 100) if total_size > 0 else 0
            speed_mb = total_speed / (1024 * 1024)
            active_streams = [k for k, v in self._stream_progress.items() if v['current'] < v['total']]
            print(f"    📊 [总体进度] {percentage:.1f}% | ⚡ {speed_mb:.2f} MB/s | 🔄 活跃流: {len(active_streams)}")
    
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
                
                # 获取播放地址
                page = self.video_info['pages'][0]
                cid = page['cid']
                
                videos, audios = await client.get_playurl(
                    self.video_info['aid'],
                    self.video_info['bvid'],
                    cid
                )
                
                # 选择最佳流
                self.selected_video = self._select_best_video(videos)
                self.selected_audio = self._select_best_audio(audios)
                
                print(f"🎯 [流选择] 已选择最佳流:")
                if self.selected_video:
                    print(f"    🎥 视频: {self.selected_video['codec'].upper()} {self.selected_video['width']}x{self.selected_video['height']}")
                if self.selected_audio:
                    print(f"    🔊 音频: {self.selected_audio['codec'].upper()} 质量:{self.selected_audio['quality']}")
                
                # 2. 开始下载
                self.status = TaskStatus.DOWNLOADING
                await self._download_streams(client)
                
                # 3. 合并文件
                self.status = TaskStatus.MERGING
                await self._merge_streams()
                
                # 4. 完成
                self.status = TaskStatus.COMPLETED
                print(f"🎉 [下载完成] 文件已保存到: {self.output_filepath}")
                
                if self._completion_callback:
                    result_info = {
                        "output_filepath": str(self.output_filepath)
                    }
                    
                    # 安全地添加流信息
                    if self.selected_video:
                        result_info["selected_video_stream_info"] = f"[{self.selected_video['codec'].upper()}] [{self.selected_video['width']}x{self.selected_video['height']}] <{self._get_quality_desc(self.selected_video['quality'])}>"
                    else:
                        result_info["selected_video_stream_info"] = "无视频流"
                    
                    if self.selected_audio:
                        result_info["selected_audio_stream_info"] = f"[{self.selected_audio['codec'].upper()}] <{self._get_audio_quality_desc(self.selected_audio['quality'])}>"
                    else:
                        result_info["selected_audio_stream_info"] = "无音频流"
                    
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
    
    async def _download_streams(self, client: BilibiliAPIClient):
        """下载视频和音频流"""
        output_dir = Path(self.task_config.get('output_dir', self.config.default_output_dir))
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 清理文件名
        filename = re.sub(r'[<>:"/\\|?*]', '_', self.video_info['title'])
        
        tasks = []
        temp_files = []
        
        # 下载视频流
        if self.selected_video:
            video_path = output_dir / f"{filename}_video.m4s"
            temp_files.append(video_path)
            tasks.append(self._download_single_stream(
                client, self.selected_video['url'], video_path, "视频流"
            ))
        
        # 下载音频流
        if self.selected_audio:
            audio_path = output_dir / f"{filename}_audio.m4s"
            temp_files.append(audio_path)
            tasks.append(self._download_single_stream(
                client, self.selected_audio['url'], audio_path, "音频流"
            ))
        
        # 并发下载
        await asyncio.gather(*tasks)
        
        # 设置临时文件路径
        self._temp_files = temp_files
        self._filename = filename
        self._output_dir = output_dir
    
    async def _download_single_stream(self, client: BilibiliAPIClient, url: str, 
                                    output_path: Path, stream_type: str):
        """下载单个流"""
        print(f"📥 [开始下载] {stream_type}: {output_path.name}")
        
        # 获取文件大小
        head_response = await client.session.head(url)
        total_size = int(head_response.headers.get('content-length', 0))
        
        # 生成流ID
        stream_id = f"{stream_type}_{output_path.name}"
        
        # 初始化流进度
        self._stream_progress[stream_id] = {
            'current': 0,
            'total': total_size,
            'speed': 0
        }
        
        # 开始下载
        current_size = 0
        start_time = time.time()
        last_speed_calc = start_time
        
        async with client.session.stream('GET', url) as response:
            response.raise_for_status()
            
            with open(output_path, 'wb') as f:
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    f.write(chunk)
                    current_size += len(chunk)
                    
                    # 计算速度
                    current_time = time.time()
                    if current_time > last_speed_calc:
                        speed = current_size / (current_time - start_time)
                    else:
                        speed = 0
                    
                    # 更新进度（使用新的统一进度管理）
                    self._update_stream_progress(stream_id, current_size, total_size, speed)
                    
                    last_speed_calc = current_time
        
        print(f"✅ [完成下载] {stream_type}")
    
    async def _merge_streams(self):
        """合并音视频流"""
        print(f"🔄 [文件合并] 正在合并音视频...")
        
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
        
        # 执行合并
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise Exception(f"FFmpeg 合并失败: {result.stderr}")
        
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


class YuttoDownloader:
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
        print(f"🚀 [初始化] YuttoDownloader 已初始化")
        print(f"    📁 输出目录: {self.config.default_output_dir}")
        print(f"    🎥 默认画质: {self.config.default_quality}")
        print(f"    🔊 默认音质: {self.config.default_audio_quality}")
    
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