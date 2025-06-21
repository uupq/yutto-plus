#!/usr/bin/env python3
"""
Yutto-Batch: 精简版B站批量下载工具
"""

import sys
import asyncio
from typing import Optional
from pathlib import Path

from batch_downloader import BatchDownloader
from utils.logger import Logger


def print_help():
    """打印帮助信息"""
    help_text = """
Yutto-Batch - 精简版B站批量下载工具

用法:
    python main.py <url> [选项]

支持的URL类型:
    - 投稿视频: https://www.bilibili.com/video/BV1xx411c7mD
    - 番剧: https://www.bilibili.com/bangumi/play/ss12345
    - 课程: https://www.bilibili.com/cheese/play/ss12345
    - 收藏夹: https://space.bilibili.com/123456/favlist?fid=789012
    - 视频列表: https://space.bilibili.com/123456/lists/789012?type=series
    - 视频合集: https://space.bilibili.com/123456/lists/789012?type=season
    - 个人空间: https://space.bilibili.com/123456
    - 稍后再看: https://www.bilibili.com/watchlater

选项:
    -h, --help          显示此帮助信息
    -o, --output DIR    指定下载目录 (默认: ./downloads)
    -c, --cookie STR    设置SESSDATA cookie
    
示例:
    python main.py "https://www.bilibili.com/video/BV1xx411c7mD"
    python main.py "https://space.bilibili.com/123456/favlist?fid=789012" -o ./my_downloads
"""
    print(help_text)


def parse_args():
    """解析命令行参数"""
    args = sys.argv[1:]
    
    if not args or '-h' in args or '--help' in args:
        print_help()
        sys.exit(0)
    
    url = args[0]
    output_dir = Path("./downloads")
    sessdata = None
    extra_args = []
    
    i = 1
    while i < len(args):
        if args[i] in ['-o', '--output'] and i + 1 < len(args):
            output_dir = Path(args[i + 1])
            i += 2
        elif args[i] in ['-c', '--cookie'] and i + 1 < len(args):
            sessdata = args[i + 1]
            i += 2
        else:
            # 未识别的参数传递给yutto
            extra_args.append(args[i])
            i += 1
    
    return url, output_dir, sessdata, extra_args


async def main():
    """主函数"""
    try:
        url, output_dir, sessdata, extra_args = parse_args()
        
        # 只需要URL用于记录在CSV中
        original_url = url
        
        # 创建输出目录
        output_dir.mkdir(parents=True, exist_ok=True)
        
        Logger.info(f"URL: {url}")
        Logger.info(f"输出目录: {output_dir}")
        if extra_args:
            Logger.info(f"额外参数传递给yutto: {' '.join(extra_args)}")
        
        # 创建批量下载器
        downloader = BatchDownloader(
            output_dir=output_dir,
            sessdata=sessdata,
            extra_args=extra_args,
            original_url=original_url
        )
        
        # 开始批量下载
        await downloader.download_from_url(url)
        
        Logger.info("下载完成！")
        
    except KeyboardInterrupt:
        Logger.info("用户中断下载")
        sys.exit(1)
    except Exception as e:
        Logger.error(f"下载失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main()) 