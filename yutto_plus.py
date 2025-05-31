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
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass
from enum import Enum
import subprocess
from collections import deque
from concurrent.futures import ThreadPoolExecutor


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"       # 等待中
    QUEUED = "queued"         # 已排队
    EXTRACTING = "extracting" # 信息提取中
    DOWNLOADING = "downloading" # 下载中
    MERGING = "merging"       # 合并中
    COMPLETED = "completed"   # 已完成
    FAILED = "failed"         # 失败
    PAUSED = "paused"         # 已暂停
    CANCELLED = "cancelled"   # 已取消


@dataclass
class TaskProgressInfo:
    """任务进度信息"""
    task_id: str
    status: TaskStatus
    video_info: Optional[Dict] = None
    progress_percentage: float = 0.0
    current_bytes: int = 0
    total_bytes: int = 0
    download_speed: float = 0.0
    eta_seconds: int = 0
    selected_streams: Optional[Dict] = None
    error_message: Optional[str] = None


@dataclass
class OverallProgressInfo:
    """整体进度信息"""
    total_tasks: int
    pending_tasks: int
    running_tasks: int
    completed_tasks: int
    failed_tasks: int
    overall_progress: float
    total_speed: float
    eta_seconds: int


class TaskManager:
    """任务管理器 - 负责任务队列管理和调度"""
    
    def __init__(self, max_concurrent: int):
        self.max_concurrent = max_concurrent
        self.pending_queue = deque()          # 等待队列: (task_id, DownloadTask)
        self.running_tasks = {}              # 正在执行的任务: {task_id: DownloadTask}
        self.completed_tasks = {}            # 已完成任务: {task_id: (success, result_info, error)}
        self.failed_tasks = {}               # 失败任务: {task_id: error_message}
        self.paused_tasks = {}               # 暂停任务: {task_id: DownloadTask}
        self.thread_pool = ThreadPoolExecutor(max_workers=max_concurrent)
        self._lock = threading.Lock()        # 线程安全锁
        
    def add_task(self, task_id: str, download_task: 'DownloadTask'):
        """添加任务到队列"""
        with self._lock:
            self.pending_queue.append((task_id, download_task))
            print(f"📋 任务已添加到队列: {task_id}")
    
    def start_next_task(self) -> bool:
        """启动下一个等待的任务，返回是否启动了新任务"""
        with self._lock:
            return self._start_next_task_unlocked()
    
    def _start_next_task_unlocked(self) -> bool:
        """内部方法：启动下一个等待的任务（不获取锁）"""
        # 检查是否还有并发容量
        if len(self.running_tasks) >= self.max_concurrent:
            return False
        
        # 检查是否有等待的任务
        if not self.pending_queue:
            return False
        
        # 取出下一个任务
        task_id, download_task = self.pending_queue.popleft()
        self.running_tasks[task_id] = download_task
        
        # 更新任务状态为已排队
        download_task.status = TaskStatus.QUEUED
        
        print(f"🚀 启动任务: {task_id}")
        return True
    
    def on_task_completed(self, task_id: str, success: bool, result_info: Dict = None, error: str = None):
        """任务完成回调"""
        with self._lock:
            if task_id in self.running_tasks:
                download_task = self.running_tasks.pop(task_id)
                
                if success:
                    self.completed_tasks[task_id] = (success, result_info, error)
                    print(f"✅ 任务完成: {task_id}")
                else:
                    self.failed_tasks[task_id] = error
                    print(f"❌ 任务失败: {task_id} - {error}")
                
                # 尝试启动下一个任务 (使用内部方法避免死锁)
                if self._start_next_task_unlocked():
                    # 如果成功启动了新任务，需要实际启动它
                    # 获取刚启动的任务
                    for new_task_id, new_download_task in list(self.running_tasks.items()):
                        if new_download_task.status == TaskStatus.QUEUED:
                            # 启动这个任务
                            new_download_task.start()
                            break
    
    def get_queue_status(self) -> Dict:
        """获取队列状态统计"""
        with self._lock:
            return {
                'pending': len(self.pending_queue),
                'running': len(self.running_tasks),
                'completed': len(self.completed_tasks),
                'failed': len(self.failed_tasks),
                'paused': len(self.paused_tasks),
                'total': len(self.pending_queue) + len(self.running_tasks) + len(self.completed_tasks) + len(self.failed_tasks)
            }
    
    def pause_task(self, task_id: str) -> bool:
        """暂停指定任务"""
        with self._lock:
            if task_id in self.running_tasks:
                download_task = self.running_tasks.pop(task_id)
                self.paused_tasks[task_id] = download_task
                download_task.status = TaskStatus.PAUSED
                # TODO: 实现任务暂停逻辑
                return True
            return False
    
    def resume_task(self, task_id: str) -> bool:
        """恢复指定任务"""
        with self._lock:
            if task_id in self.paused_tasks:
                download_task = self.paused_tasks.pop(task_id)
                self.pending_queue.appendleft((task_id, download_task))
                return True
            return False
    
    def get_running_tasks(self) -> Dict[str, 'DownloadTask']:
        """获取当前运行的任务"""
        with self._lock:
            return self.running_tasks.copy()
    
    def shutdown(self):
        """关闭任务管理器"""
        self.thread_pool.shutdown(wait=True)


def get_display_width(text):
    """计算字符串的实际显示宽度（中文字符计为2，英文计为1）"""
    width = 0
    for char in text:
        if ord(char) > 127:  # 非ASCII字符（包括中文、emoji等）
            width += 2
        else:
            width += 1
    return width

def align_text(text, target_width, align='left'):
    """正确对齐包含中英文混合的文本
    
    Args:
        text: 要对齐的文本
        target_width: 目标显示宽度
        align: 对齐方式 ('left', 'right', 'center')
    
    Returns:
        对齐后的文本
    """
    current_width = get_display_width(text)
    
    if current_width >= target_width:
        # 截断过长的文本，需要考虑中英文混合的情况
        truncated = ""
        truncated_width = 0
        for char in text:
            char_width = 2 if ord(char) > 127 else 1
            if truncated_width + char_width <= target_width:
                truncated += char
                truncated_width += char_width
            else:
                break
        return truncated
    
    padding_needed = target_width - current_width
    
    if align == 'left':
        return text + ' ' * padding_needed
    elif align == 'right':
        return ' ' * padding_needed + text
    elif align == 'center':
        left_padding = padding_needed // 2
        right_padding = padding_needed - left_padding
        return ' ' * left_padding + text + ' ' * right_padding
    
    return text

class ProgressMonitor:
    """进度监控和显示管理"""
    
    def __init__(self, max_tasks_display: int = 3):
        self.max_tasks_display = max_tasks_display
        self.display_mode = 'table'  # 'table' | 'simple' | 'silent'
        self.last_update_time = 0
        self.update_interval = 0.5  # 更新间隔(秒)
        
        # 显示状态
        self._last_display_lines = 0  # 上次显示的行数
        self._first_display = True    # 是否为第一次显示
    
    def set_display_mode(self, mode: str):
        """设置显示模式"""
        if mode in ['table', 'simple', 'silent']:
            self.display_mode = mode
        else:
            raise ValueError(f"不支持的显示模式: {mode}")
    
    def should_update(self) -> bool:
        """判断是否应该更新显示"""
        import time
        current_time = time.time()
        if current_time - self.last_update_time >= self.update_interval:
            self.last_update_time = current_time
            return True
        return False
    
    def update_progress(self, tasks_progress: Dict[str, TaskProgressInfo], overall_progress: OverallProgressInfo):
        """更新进度显示"""
        if self.display_mode == 'silent':
            return
        
        if not self.should_update():
            return
        
        if self.display_mode == 'table':
            self._display_table_refresh(tasks_progress, overall_progress)
        elif self.display_mode == 'simple':
            self._display_simple(tasks_progress, overall_progress)
    
    def _clear_previous_display(self):
        """清除之前的显示内容"""
        if not self._first_display and self._last_display_lines > 0:
            # 向上移动光标并清除行
            for _ in range(self._last_display_lines):
                print('\033[A\033[K', end='')
        self._first_display = False
    
    def _display_table_refresh(self, tasks_progress: Dict[str, TaskProgressInfo], overall_progress: OverallProgressInfo):
        """表格模式显示（刷新式，避免界面跳动）"""
        # 清除之前的显示
        self._clear_previous_display()
        
        display_lines = []
        
        # 主进度行
        display_lines.append(f"📊 整体状态: {overall_progress.completed_tasks}/{overall_progress.total_tasks} 完成 | "
                           f"运行中: {overall_progress.running_tasks} | "
                           f"总进度: {overall_progress.overall_progress:.1f}% | "
                           f"速度: {overall_progress.total_speed/(1024*1024):.1f} MB/s")
        
        # 如果有预计完成时间，显示它
        if overall_progress.eta_seconds > 0:
            eta_minutes = overall_progress.eta_seconds // 60
            eta_seconds = overall_progress.eta_seconds % 60
            display_lines.append(f"⏱️  预计剩余时间: {eta_minutes:02d}:{eta_seconds:02d}")
        
        # 只显示活跃的任务（运行中或者排队中）
        active_tasks = {tid: prog for tid, prog in tasks_progress.items() 
                       if prog.status in [TaskStatus.QUEUED, TaskStatus.EXTRACTING, 
                                         TaskStatus.DOWNLOADING, TaskStatus.MERGING]}
        
        if active_tasks:
            display_lines.append("")  # 空行
            display_lines.append("📋 正在进行的任务:")
            
            # 根据实际任务数量调整表格大小
            task_count = len(active_tasks)
            display_count = min(task_count, self.max_tasks_display)
            
            # 表格头部
            display_lines.append("┌─" + "─" * 10 + "┬─" + "─" * 35 + "┬─" + "─" * 10 + "┬─" + "─" * 18 + "┐")
            display_lines.append("│ 任务ID    │ 标题                               │ 状态      │ 进度              │")
            display_lines.append("├─" + "─" * 10 + "┼─" + "─" * 35 + "┼─" + "─" * 10 + "┼─" + "─" * 18 + "┤")
            
            # 显示任务行
            active_items = list(active_tasks.items())[:display_count]
            for task_id, progress in active_items:
                # 处理标题长度 - 根据实际显示宽度截断
                title = "未知标题"
                if progress.video_info and 'title' in progress.video_info:
                    full_title = progress.video_info['title']
                    if get_display_width(full_title) > 31:  # 为"..."留3个字符空间
                        # 逐字符截断直到合适长度
                        truncated = ""
                        for char in full_title:
                            if get_display_width(truncated + char + "...") <= 31:
                                truncated += char
                            else:
                                break
                        title = truncated + "..."
                    else:
                        title = full_title
                
                # 状态显示
                status_icons = {
                    TaskStatus.QUEUED: "📋 排队",
                    TaskStatus.EXTRACTING: "🔍 分析",
                    TaskStatus.DOWNLOADING: "📥 下载",
                    TaskStatus.MERGING: "🔄 合并"
                }
                status_display = status_icons.get(progress.status, str(progress.status.value))
                
                # 进度显示
                if progress.status == TaskStatus.DOWNLOADING and progress.total_bytes > 0:
                    progress_text = f"{progress.progress_percentage:5.1f}%"
                    speed_text = f"{progress.download_speed/(1024*1024):5.1f}MB/s"
                    progress_display = f"{progress_text} {speed_text}"
                else:
                    progress_display = f"{progress.progress_percentage:5.1f}%"
                
                # 使用正确的对齐函数
                aligned_id = align_text(task_id, 9, 'left')
                aligned_title = align_text(title, 34, 'left')  # 目标显示宽度34
                aligned_status = align_text(status_display, 9, 'left')  # 状态列
                aligned_progress = align_text(progress_display, 17, 'left')
                
                task_line = f"│ {aligned_id} │ {aligned_title} │ {aligned_status} │ {aligned_progress} │"
                display_lines.append(task_line)
            
            # 表格底部
            display_lines.append("└─" + "─" * 10 + "┴─" + "─" * 35 + "┴─" + "─" * 10 + "┴─" + "─" * 18 + "┘")
        
        # 如果没有活跃任务，显示处理中状态
        elif overall_progress.running_tasks == 0 and overall_progress.pending_tasks == 0:
            if overall_progress.total_tasks > 0:
                display_lines.append("")
                display_lines.append("✅ 所有任务已完成!")
        
        # 输出所有行
        for line in display_lines:
            print(line)
        
        # 记录显示的行数
        self._last_display_lines = len(display_lines)
    
    def _display_table(self, tasks_progress: Dict[str, TaskProgressInfo], overall_progress: OverallProgressInfo):
        """原有的表格模式显示（兼容性保留）"""
        # 重定向到新的刷新式显示
        self._display_table_refresh(tasks_progress, overall_progress)
    
    def _display_simple(self, tasks_progress: Dict[str, TaskProgressInfo], overall_progress: OverallProgressInfo):
        """简单模式显示"""
        print(f"📊 总进度: {overall_progress.overall_progress:.1f}% | "
              f"完成: {overall_progress.completed_tasks}/{overall_progress.total_tasks} | "
              f"速度: {overall_progress.total_speed/(1024*1024):.2f} MB/s")
        
        # 显示运行中的任务
        running_tasks = [(tid, prog) for tid, prog in tasks_progress.items() 
                        if prog.status in [TaskStatus.DOWNLOADING, TaskStatus.EXTRACTING, TaskStatus.MERGING]]
        
        for task_id, progress in running_tasks[:2]:  # 最多显示2个运行中的任务
            title = "未知"
            if progress.video_info and 'title' in progress.video_info:
                title = progress.video_info['title'][:30]
            
            status_icon = "📥" if progress.status == TaskStatus.DOWNLOADING else "🔍"
            print(f"  {status_icon} {task_id}: {title} ({progress.progress_percentage:.1f}%)")
    
    def display_completion_summary(self, final_status: Dict, elapsed_time: float, tasks_info: Dict = None):
        """显示完成总结"""
        # 清除之前的显示
        self._clear_previous_display()
        
        print("=" * 60)
        print("🎉 所有任务已完成!")
        print(f"⏱️  总用时: {elapsed_time:.1f} 秒")
        print(f"📊 结果统计:")
        print(f"   ✅ 成功: {final_status.get('completed', 0)}")
        print(f"   ❌ 失败: {final_status.get('failed', 0)}")
        print(f"   📊 总计: {final_status.get('total', 0)}")
        
        # 显示详细的任务信息（如果提供）
        if tasks_info:
            completed_tasks = tasks_info.get('completed', [])
            failed_tasks = tasks_info.get('failed', [])
            
            if completed_tasks:
                print(f"\n✅ 成功完成的任务:")
                for task_info in completed_tasks:
                    bv_id = task_info.get('bv_id', '未知')
                    title = task_info.get('title', '未知标题')
                    # 限制标题显示长度
                    if len(title) > 50:
                        title = title[:47] + "..."
                    print(f"   📄 {bv_id}: {title}")
            
            if failed_tasks:
                print(f"\n❌ 失败的任务:")
                for task_info in failed_tasks:
                    bv_id = task_info.get('bv_id', '未知')
                    title = task_info.get('title', '未知标题')
                    error = task_info.get('error', '未知错误')
                    # 限制标题显示长度
                    if len(title) > 40:
                        title = title[:37] + "..."
                    print(f"   ❌ {bv_id}: {title} ({error})")
        
        # 重置显示状态
        self._last_display_lines = 0
        self._first_display = True


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
    
    def __init__(self, url: str, config: DownloadConfig, task_config: Dict[str, Any] = None, 
                 task_id: str = None, parent_manager = None, silent_mode: bool = False):
        self.url = url
        self.config = config
        self.task_config = task_config or {}
        self.task_id = task_id or f"task_{int(time.time())}"
        self.parent_manager = parent_manager  # 指向 YuttoPlus
        self.silent_mode = silent_mode       # 是否静默（不直接输出）
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
        
    def _print_if_not_silent(self, message: str):
        """只在非静默模式下输出"""
        if not self.silent_mode:
            print(message)
    
    def _report_progress(self, progress_info: Dict):
        """向父管理器报告进度"""
        if self.parent_manager:
            self.parent_manager.on_task_progress(self.task_id, progress_info)
            
    def _report_status_change(self, new_status: TaskStatus):
        """报告状态变化"""
        old_status = self.status
        self.status = new_status
        if self.parent_manager:
            self.parent_manager.on_task_status_change(self.task_id, old_status, new_status)
            
    def _report_completion(self, success: bool, result_info: Dict = None, error: str = None):
        """报告任务完成"""
        if self.parent_manager:
            self.parent_manager.on_task_completed(self.task_id, success, result_info, error)
    
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
            # 向父管理器报告进度
            if self.parent_manager:
                progress_info = {
                    'current_bytes': total_current,
                    'total_bytes': total_size,
                    'speed_bps': total_speed
                }
                self._report_progress(progress_info)
            
            # 原有的回调
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
            self._report_status_change(TaskStatus.EXTRACTING)
            self._print_if_not_silent(f"🔍 正在分析视频: {self.url}")
            
            async with BilibiliAPIClient(self.config.sessdata) as client:
                self.video_info = await client.get_video_info(self.url)
                
                self._print_if_not_silent(f"✅ 视频解析成功: {self.video_info['title']}")
                self._print_if_not_silent(f"👤 UP主: {self.video_info['uploader']}")
                
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
                
                self._print_if_not_silent(f"🎯 流选择完成:")
                if self.selected_video:
                    self._print_if_not_silent(f"    📹 视频: {self.selected_video['codec'].upper()} {self.selected_video['width']}x{self.selected_video['height']}")
                if self.selected_audio:
                    self._print_if_not_silent(f"    🔊 音频: {self.selected_audio['codec'].upper()} 质量:{self.selected_audio['quality']}")
                
                # 下载弹幕
                if require_danmaku:
                    self._print_if_not_silent(f"📝 正在下载弹幕...")
                    self.danmaku_data = await client.get_danmaku(
                        self.video_info['aid'],
                        cid,
                        user_info
                    )
                    self._print_if_not_silent(f"✅ 弹幕下载完成 ({self.danmaku_data['source_type']} 格式)")
                
                # 下载封面
                if require_cover:
                    self._print_if_not_silent(f"🖼️ 正在下载封面...")
                    self.cover_data = await client.get_cover_data(self.video_info['pic'])
                    self._print_if_not_silent(f"✅ 封面下载完成 ({len(self.cover_data)} 字节)")
                
                # 立即通知流信息可用
                if self._stream_info_callback:
                    stream_info = self.get_selected_streams_info()
                    if stream_info:
                        self._stream_info_callback(stream_info)
                
                # 2. 开始下载媒体文件
                if require_video or require_audio:
                    self._report_status_change(TaskStatus.DOWNLOADING)
                    await self._download_streams(client)
                    
                    # 3. 合并文件
                    self._report_status_change(TaskStatus.MERGING)
                    
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
                self._report_status_change(TaskStatus.COMPLETED)
                self._print_if_not_silent(f"🎉 下载完成")
                
                # 通知完成
                result_info = self._build_result_info()
                self._report_completion(True, result_info, None)
                
                if self._completion_callback:
                    self._completion_callback(True, result_info, None)
                    
        except Exception as e:
            self.error_message = str(e)
            self.status = TaskStatus.FAILED
            self._print_if_not_silent(f"❌ 下载失败: {self.error_message}")
            
            # 通知失败
            self._report_completion(False, None, self.error_message)
            
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
            print(f"❌ 网络错误: {e}")
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
        print(f"🔄 正在合并音视频...")
        
        # 检查是否为仅音频模式
        audio_only = self.task_config.get('audio_only', False)
        audio_format = self.task_config.get('audio_format', 'mp3')
        
        if audio_only and len(self._temp_files) == 1:
            # 仅音频模式，需要转换格式
            print(f"🎵 转换为 {audio_format.upper()} 格式")
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
                print(f"    📝 单流模式: 直接复制")
            else:
                # 多个流，需要合并
                cmd.extend([
                    "-c:v", "copy",  # 视频流复制
                    "-c:a", "copy",  # 音频流复制
                    str(self.output_filepath)
                ])
                print(f"    📝 合并模式: 合并 {len(available_files)} 个流")
        
        # 执行合并/转换
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise Exception(f"FFmpeg 处理失败: {result.stderr}")
        
        # 清理临时文件
        for temp_file in self._temp_files:
            if temp_file.exists():
                temp_file.unlink()
        
        print(f"✅ 合并完成: {self.output_filepath.name}")
    
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
            print(f"📝 正在保存弹幕...")
            
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
            
            print(f"✅ 弹幕保存完成")
        
        if self.cover_data:
            print(f"🖼️ 正在保存封面...")
            # 从 URL 获取文件扩展名，默认为 jpg
            cover_ext = "jpg"
            if self.video_info.get('pic'):
                pic_url = self.video_info['pic']
                if '.' in pic_url:
                    cover_ext = pic_url.split('.')[-1].split('?')[0]
            
            cover_path = self._output_dir / f"{self._filename}.{cover_ext}"
            with open(cover_path, 'wb') as f:
                f.write(self.cover_data)
            print(f"✅ 封面保存完成: {cover_path.name}")


class YuttoPlus:
    """主下载器类"""
    
    def __init__(self, max_concurrent: int = 3, **config):
        """初始化下载器"""
        self.config = DownloadConfig(**config)
        
        # 并行管理
        self.max_concurrent = max_concurrent
        self.task_manager = TaskManager(max_concurrent)
        self.active_tasks = {}                # {task_id: DownloadTask}
        self.task_counter = 0                 # 任务ID计数器
        
        # 进度监控
        self.progress_monitor = ProgressMonitor(max_tasks_display=max_concurrent)
        self.tasks_progress = {}              # {task_id: TaskProgressInfo}
        self.completed_tasks_info = []        # 完成任务的详细信息
        self.failed_tasks_info = []           # 失败任务的详细信息
        
        print(f"🚀 YuttoPlus 已初始化 (并发数: {max_concurrent})")
        print(f"📁 输出目录: {self.config.default_output_dir}")
        
        # 验证用户登录状态
        if self.config.sessdata:
            self._validate_user_info()
        else:
            print("ℹ️ 未提供 SESSDATA，无法下载高清视频等资源")
    
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
                        print("🎖️ ✅ 成功以大会员身份登录")
                    else:
                        print("👤 ✅ 登录成功，以非大会员身份登录")
                        print("⚠️ 注意无法下载会员专享剧集和最高画质")
                else:
                    print("❌ SESSDATA 无效或已过期，请检查后重试")
            elif result["error"]:
                print(f"⚠️ 验证失败: {result['error']}")
            else:
                print("⚠️ 验证超时，将继续使用提供的 SESSDATA")
                
        except Exception as e:
            print(f"⚠️ 验证过程出错: {e}")
    
    def create_download_task(self, url: str, **kwargs) -> DownloadTask:
        """创建下载任务 (兼容原有API)
        
        Args:
            url: B站视频链接
            **kwargs: 覆盖默认配置的参数
        
        Returns:
            DownloadTask: 下载任务实例
        """
        print(f"📋 创建任务: {url}")
        if kwargs:
            print(f"⚙️ 任务配置: {kwargs}")
        
        return DownloadTask(url, self.config, kwargs)
    
    def add_download_tasks(self, urls_with_configs: List[Tuple[str, Dict]]) -> List[str]:
        """添加多个下载任务，返回任务ID列表"""
        task_ids = []
        
        for url, task_config in urls_with_configs:
            # 生成任务ID
            self.task_counter += 1
            task_id = f"task_{self.task_counter:03d}"
            
            # 创建任务
            download_task = DownloadTask(
                url=url,
                config=self.config,
                task_config=task_config,
                task_id=task_id,
                parent_manager=self,
                silent_mode=True  # 并行模式下默认静默
            )
            
            # 添加到活跃任务和任务管理器
            self.active_tasks[task_id] = download_task
            self.task_manager.add_task(task_id, download_task)
            task_ids.append(task_id)
        
        print(f"📊 已添加 {len(task_ids)} 个任务到队列")
        return task_ids
    
    def start_parallel_download(self, display_mode: str = 'auto') -> None:
        """开始并行下载"""
        print(f"🚀 开始并行下载 (显示模式: {display_mode})")
        
        # 设置显示模式
        if display_mode == 'auto':
            # 根据任务数量自动选择
            total_tasks = len(self.active_tasks)
            if total_tasks <= 1:
                self.progress_monitor.set_display_mode('simple')
            elif total_tasks <= 3:
                self.progress_monitor.set_display_mode('table')
            else:
                self.progress_monitor.set_display_mode('simple')
        else:
            self.progress_monitor.set_display_mode(display_mode)
        
        # 启动初始任务
        started_count = 0
        for _ in range(self.max_concurrent):
            if self.task_manager.start_next_task():
                started_count += 1
        
        print(f"📥 启动了 {started_count} 个初始任务")
        
        # 开始执行启动的任务
        for task_id, download_task in self.task_manager.get_running_tasks().items():
            download_task.start()
        
        print()  # 为进度显示留空行
    
    def on_task_progress(self, task_id: str, progress_info: Dict):
        """任务进度回调"""
        # 更新任务进度信息
        if task_id in self.tasks_progress:
            task_progress = self.tasks_progress[task_id]
            # 更新下载进度
            if 'current_bytes' in progress_info:
                task_progress.current_bytes = progress_info['current_bytes']
            if 'total_bytes' in progress_info:
                task_progress.total_bytes = progress_info['total_bytes']
            if 'speed_bps' in progress_info:
                task_progress.download_speed = progress_info['speed_bps']
            
            # 计算进度百分比
            if task_progress.total_bytes > 0:
                task_progress.progress_percentage = (task_progress.current_bytes / task_progress.total_bytes) * 100
        
        # 触发进度显示更新
        self._update_progress_display()
    
    def on_task_status_change(self, task_id: str, old_status: TaskStatus, new_status: TaskStatus):
        """任务状态变化回调"""
        # 更新任务进度信息中的状态
        if task_id not in self.tasks_progress:
            # 创建新的进度信息
            self.tasks_progress[task_id] = TaskProgressInfo(
                task_id=task_id,
                status=new_status
            )
        else:
            self.tasks_progress[task_id].status = new_status
        
        # 如果任务有视频信息，更新到进度信息中
        if task_id in self.active_tasks:
            task = self.active_tasks[task_id]
            if hasattr(task, 'video_info') and task.video_info:
                self.tasks_progress[task_id].video_info = task.video_info
        
        # 输出状态变化（仅在非table模式下）
        if self.progress_monitor.display_mode != 'table':
            print(f"📌 任务 {task_id}: {old_status.value} → {new_status.value}")
        
        # 触发进度显示更新
        self._update_progress_display()
    
    def on_task_completed(self, task_id: str, success: bool, result_info: Dict = None, error: str = None):
        """任务完成回调"""
        # 更新任务进度信息
        if task_id in self.tasks_progress:
            task_progress = self.tasks_progress[task_id]
            if success:
                task_progress.status = TaskStatus.COMPLETED
                task_progress.progress_percentage = 100.0
                
                # 收集成功任务信息
                if task_id in self.active_tasks:
                    task = self.active_tasks[task_id]
                    if hasattr(task, 'video_info') and task.video_info:
                        self.completed_tasks_info.append({
                            'task_id': task_id,
                            'bv_id': task.video_info.get('bvid', '未知'),
                            'title': task.video_info.get('title', '未知标题'),
                            'url': task.url
                        })
            else:
                task_progress.status = TaskStatus.FAILED
                task_progress.error_message = error
                
                # 收集失败任务信息
                if task_id in self.active_tasks:
                    task = self.active_tasks[task_id]
                    # 提取BV号
                    bv_id = "未知"
                    try:
                        import re
                        bv_match = re.search(r'BV([a-zA-Z0-9]+)', task.url)
                        if bv_match:
                            bv_id = f"BV{bv_match.group(1)}"
                    except:
                        pass
                    
                    title = "未知标题"
                    if hasattr(task, 'video_info') and task.video_info:
                        title = task.video_info.get('title', '未知标题')
                    
                    self.failed_tasks_info.append({
                        'task_id': task_id,
                        'bv_id': bv_id,
                        'title': title,
                        'url': task.url,
                        'error': error or '未知错误'
                    })
        
        # 通知任务管理器
        self.task_manager.on_task_completed(task_id, success, result_info, error)
        
        # 从活跃任务中移除
        if task_id in self.active_tasks:
            del self.active_tasks[task_id]
        
        # 触发进度显示更新
        self._update_progress_display()
    
    def _update_progress_display(self):
        """更新进度显示"""
        overall_progress = self.get_overall_progress()
        self.progress_monitor.update_progress(self.tasks_progress, overall_progress)
    
    def get_overall_progress(self) -> OverallProgressInfo:
        """获取整体进度信息"""
        queue_status = self.task_manager.get_queue_status()
        
        # 计算整体进度和速度
        total_progress = 0.0
        total_speed = 0.0
        total_bytes = 0
        current_bytes = 0
        
        for task in self.active_tasks.values():
            if hasattr(task, '_stream_progress') and task._stream_progress:
                for progress in task._stream_progress.values():
                    current_bytes += progress['current']
                    total_bytes += progress['total']
                    total_speed += progress['speed']
        
        if total_bytes > 0:
            total_progress = (current_bytes / total_bytes) * 100
        
        # 估算剩余时间
        eta_seconds = 0
        if total_speed > 0 and total_bytes > current_bytes:
            eta_seconds = int((total_bytes - current_bytes) / total_speed)
        
        return OverallProgressInfo(
            total_tasks=queue_status['total'],
            pending_tasks=queue_status['pending'],
            running_tasks=queue_status['running'],
            completed_tasks=queue_status['completed'],
            failed_tasks=queue_status['failed'],
            overall_progress=total_progress,
            total_speed=total_speed,
            eta_seconds=eta_seconds
        )
    
    def get_tasks_summary_info(self) -> Dict:
        """获取任务详细信息总结"""
        return {
            'completed': self.completed_tasks_info,
            'failed': self.failed_tasks_info
        }
    
    def pause_all_tasks(self) -> None:
        """暂停所有任务"""
        # TODO: 实现暂停逻辑
        print("⏸️ 暂停所有任务功能待实现")
    
    def resume_all_tasks(self) -> None:
        """恢复所有任务"""
        # TODO: 实现恢复逻辑
        print("▶️ 恢复所有任务功能待实现")
    
    def shutdown(self):
        """关闭下载器"""
        print("🔚 正在关闭下载器...")
        self.task_manager.shutdown()
        print("✅ 下载器已关闭") 
    
    def stop_progress_monitoring(self):
        """停止进度监控"""
        self.progress_monitor.display_mode = 'silent'
    
    def start_progress_monitoring(self):
        """开始进度监控"""
        self.progress_monitor.display_mode = 'table'
    
    def wait_for_completion(self):
        """等待下载完成"""
        # 等待下载完成
        max_wait_time = 3600  # 最多等待1小时
        start_time = time.time()
        
        while True:
            current_time = time.time()
            elapsed = current_time - start_time
            
            # 超时检查
            if elapsed > max_wait_time:
                print(f"\n⏰ 下载超时 ({max_wait_time}秒)，强制结束")
                break
            
            queue_status = self.task_manager.get_queue_status()
            
            # 检查是否所有任务完成
            if queue_status['running'] == 0 and queue_status['pending'] == 0:
                break
            
            time.sleep(2)  # 每2秒检查一次
        
        # 停止进度监控
        self.stop_progress_monitoring()
        
        # 显示最终结果
        final_status = self.task_manager.get_queue_status()
        elapsed_time = time.time() - start_time
        tasks_info = self.get_tasks_summary_info()
        
        self.progress_monitor.display_completion_summary(final_status, elapsed_time, tasks_info)