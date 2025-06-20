"""
批量下载器
"""

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Optional, List

from utils.types import VideoListData, VideoInfo, DownloadOptions
from utils.fetcher import Fetcher
from utils.logger import Logger
from extractors import extract_video_list


class BatchDownloader:
    """批量下载器"""
    
    def __init__(self, output_dir: Path, sessdata: Optional[str] = None, extra_args: Optional[List[str]] = None):
        """初始化批量下载器"""
        self.output_dir = output_dir
        self.sessdata = sessdata
        self.extra_args = extra_args or []
        self.fetcher = Fetcher(sessdata=sessdata)
    
    async def download_from_url(self, url: str) -> None:
        """从URL开始批量下载"""
        async with self.fetcher:
            try:
                # 提取视频列表
                video_list = await extract_video_list(self.fetcher, url)
                
                Logger.info(f"找到 {len(video_list['videos'])} 个视频")
                Logger.custom(video_list["title"], "批量下载")
                
                # 创建输出目录
                self.output_dir.mkdir(parents=True, exist_ok=True)
                
                # 批量下载
                await self._download_videos(video_list["videos"])
                
            except Exception as e:
                Logger.error(f"批量下载失败: {e}")
                raise
    
    async def _download_videos(self, videos: list[VideoInfo]) -> None:
        """下载视频列表"""
        for i, video in enumerate(videos, 1):
            try:
                Logger.info(f"[{i}/{len(videos)}] 开始下载: {video['name']}")
                
                # 创建视频目录
                video_dir = self.output_dir / video["path"].parent
                video_dir.mkdir(parents=True, exist_ok=True)
                
                # 下载视频（这里简化处理，只输出信息）
                await self._download_single_video(video, video_dir)
                
                Logger.info(f"[{i}/{len(videos)}] 下载完成: {video['name']}")
                
            except Exception as e:
                Logger.error(f"下载视频 {video['name']} 失败: {e}")
                continue
    
    async def _download_single_video(self, video: VideoInfo, output_dir: Path) -> None:
        """调用原版yutto下载单个视频"""
        
        # 构建yutto命令
        yutto_cmd = ["yutto"]
        
        # 视频URL
        video_url = str(video['avid'].to_url())
        yutto_cmd.append(video_url)
        
        # 输出目录
        yutto_cmd.extend(["-d", str(output_dir)])
        
        # 如果有SESSDATA，添加-c参数
        if self.sessdata:
            yutto_cmd.extend(["-c", self.sessdata])
        
        # 添加用户额外参数
        yutto_cmd.extend(self.extra_args)
        
        try:
            Logger.debug(f"执行命令: {' '.join(yutto_cmd)}")
            
            # 执行yutto命令
            process = await asyncio.create_subprocess_exec(
                *yutto_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=Path(__file__).parent
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                Logger.debug(f"yutto输出: {stdout.decode('utf-8', errors='ignore')}")
            else:
                Logger.error(f"yutto错误: {stderr.decode('utf-8', errors='ignore')}")
                raise Exception(f"yutto下载失败，返回码: {process.returncode}")
                
        except Exception as e:
            Logger.error(f"调用yutto失败: {e}")
            raise 