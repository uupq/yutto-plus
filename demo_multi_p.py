#!/usr/bin/env python3
"""
多P视频下载功能演示脚本
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from yutto_plus.core import YuttoPlus, DownloadConfig

def demo_multi_p_download():
    """演示多P视频下载功能"""
    print("🎬 多P视频下载功能演示")
    print("=" * 50)
    
    # 创建下载配置
    config = DownloadConfig(
        default_output_dir="./demo_downloads",
        episodes_selection="~3",  # 默认下载前3个分P
        create_folder_for_multi_p=True,
        require_danmaku=False,  # 演示时不下载弹幕
        require_cover=False,    # 演示时不下载封面
    )
    
    # 创建下载器
    downloader = YuttoPlus(max_concurrent=1, **config.__dict__)
    
    # 测试URL（请确保这些是有效的多P视频）
    test_urls = [
        "https://www.bilibili.com/video/BV1unjgzqEms",  # 多P视频示例
        # 可以添加更多测试URL
    ]
    
    print(f"📋 配置信息:")
    print(f"   输出目录: {config.default_output_dir}")
    print(f"   分P选择: {config.episodes_selection}")
    print(f"   创建文件夹: {config.create_folder_for_multi_p}")
    print()
    
    for i, url in enumerate(test_urls, 1):
        print(f"🎯 测试 {i}: {url}")
        
        try:
            # 创建下载任务
            task = downloader.create_download_task(
                url,
                episodes_selection="~2",  # 只下载前2个分P用于演示
                require_video=True,
                require_audio=True,
                require_danmaku=False,
                require_cover=False,
            )
            
            print(f"✅ 任务创建成功: {task.task_id}")
            print(f"📺 视频URL: {task.url}")
            
            # 设置回调函数
            def on_progress(current_bytes, total_bytes, speed_mbps, eta_seconds):
                if total_bytes > 0:
                    progress = (current_bytes / total_bytes) * 100
                    print(f"📥 下载进度: {progress:.1f}% ({speed_mbps:.1f} MB/s, ETA: {eta_seconds:.0f}s)")
            
            def on_completion(success, result_info, error_message):
                if success:
                    if result_info.get('type') == 'multi_p':
                        print(f"🎉 多P视频下载完成!")
                        print(f"📁 输出目录: {result_info['output_dir']}")
                        print(f"📊 下载统计: {len(result_info['downloaded_parts'])}/{result_info['total_parts']} 个分P")
                    else:
                        print(f"🎉 单P视频下载完成!")
                        print(f"📁 文件路径: {result_info['output_filepath']}")
                else:
                    print(f"❌ 下载失败: {error_message}")
            
            # 启动下载（这里只是演示，实际下载需要异步环境）
            print(f"🚀 准备启动下载任务...")
            print(f"💡 实际下载请使用: python yutto-plus-cli.py -p '~2' '{url}'")
            print(f"💡 回调函数已准备就绪，可通过 task.start(on_progress, on_completion) 启动")
            
        except Exception as e:
            print(f"❌ 任务创建失败: {e}")
        
        print("-" * 30)

def demo_episodes_selection():
    """演示分P选择功能"""
    print("\n🎯 分P选择功能演示")
    print("=" * 50)
    
    from yutto_plus.core import parse_episodes_selection
    
    examples = [
        ("1,3,5", 10, "选择第1、3、5个分P"),
        ("1~3", 10, "选择第1到第3个分P"),
        ("~3", 10, "选择前3个分P"),
        ("-2~", 10, "选择后2个分P"),
        ("1,5~8,10", 10, "选择第1、5到8、10个分P"),
        ("$", 10, "选择最后一个分P"),
        ("", 10, "选择全部分P"),
    ]
    
    for selection, total, description in examples:
        try:
            result = parse_episodes_selection(selection, total)
            result_display = [i+1 for i in result]  # 转换为从1开始的编号显示
            print(f"📋 '{selection}' -> {result_display} ({description})")
        except Exception as e:
            print(f"❌ '{selection}' -> 错误: {e}")

def demo_file_structure():
    """演示文件结构"""
    print("\n📁 文件结构演示")
    print("=" * 50)
    
    print("多P视频文件结构（默认）:")
    print("Downloads/")
    print("└── 视频标题/")
    print("    ├── P01_第一集标题.mp4")
    print("    ├── P02_第二集标题.mp4")
    print("    ├── P03_第三集标题.mp4")
    print("    ├── P01_第一集标题.xml")
    print("    ├── P02_第二集标题.xml")
    print("    └── 视频标题_cover.jpg")
    print()
    
    print("多P视频文件结构（使用 --no-folder）:")
    print("Downloads/")
    print("├── P01_第一集标题.mp4")
    print("├── P02_第二集标题.mp4")
    print("├── P03_第三集标题.mp4")
    print("└── ...")
    print()
    
    print("单P视频文件结构:")
    print("Downloads/")
    print("├── 视频标题.mp4")
    print("├── 视频标题.xml")
    print("└── 视频标题_cover.jpg")

if __name__ == "__main__":
    print("🚀 yutto-plus 多P视频功能演示")
    print("=" * 60)
    
    demo_episodes_selection()
    demo_file_structure()
    demo_multi_p_download()
    
    print("\n🎯 实际使用示例:")
    print("# 下载多P视频的前3个分P")
    print("python yutto-plus-cli.py -p '~3' 'https://www.bilibili.com/video/BV1unjgzqEms'")
    print()
    print("# 下载指定分P")
    print("python yutto-plus-cli.py -p '1,3,5~8' 'https://www.bilibili.com/video/BV1unjgzqEms'")
    print()
    print("# 不创建文件夹")
    print("python yutto-plus-cli.py --no-folder 'https://www.bilibili.com/video/BV1unjgzqEms'")
    print()
    print("📖 更多信息请查看 MULTI_P_GUIDE.md")
