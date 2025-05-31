"""
YuttoPlus - Modern Bilibili Video Downloader
功能强大的B站视频下载器，支持并行下载和Web界面
"""

from .core import (
    YuttoPlus,
    DownloadTask,
    DownloadConfig,
    BilibiliAPIClient,
    TaskStatus,
    TaskProgressInfo,
    OverallProgressInfo,
    ProgressMonitor,
    TaskManager,
    get_display_width,
    align_text
)

from .config import ConfigManager

__version__ = "2.0.0"
__author__ = "YuttoPlus Team"
__description__ = "Modern Bilibili Video Downloader with Parallel Downloads"

__all__ = [
    "YuttoPlus",
    "DownloadTask", 
    "DownloadConfig",
    "BilibiliAPIClient",
    "TaskStatus",
    "TaskProgressInfo", 
    "OverallProgressInfo",
    "ProgressMonitor",
    "TaskManager",
    "ConfigManager",
    "get_display_width",
    "align_text"
] 