#!/usr/bin/env python3
"""
调试分P确认显示问题
直接测试分P确认显示是否被调用
"""

import sys
import time
from pathlib import Path

def test_direct_episodes_display():
    """直接测试分P确认显示逻辑"""
    print("🔍 直接测试分P确认显示逻辑")
    print("=" * 50)
    
    # 导入解析函数
    sys.path.insert(0, str(Path(__file__).parent / "src"))
    from yutto_plus.core import parse_episodes_selection
    
    # 模拟多P视频的分P确认显示
    episodes_selection = "~-1"
    total_pages = 2
    
    print(f"🧪 测试参数:")
    print(f"   episodes_selection: {episodes_selection}")
    print(f"   total_pages: {total_pages}")
    print()
    
    print(f"🎬 模拟多P视频分P确认显示:")
    if episodes_selection:
        selected_indices = parse_episodes_selection(episodes_selection, total_pages)
        selected_parts = [i+1 for i in selected_indices]
        print(f"📋 分P选择参数: {episodes_selection}")
        print(f"📺 将要下载的分P: P{selected_parts} (共 {len(selected_indices)} 个)")
    else:
        selected_parts = list(range(1, total_pages + 1))
        print(f"📋 分P选择参数: 全部分P (默认)")
        print(f"📺 将要下载的分P: P{selected_parts} (共 {total_pages} 个)")
    
    print()
    print(f"🎬 模拟单P视频分P确认显示:")
    if episodes_selection:
        print(f"📋 分P选择参数: {episodes_selection} (单P视频，忽略分P参数)")
    else:
        print(f"📋 分P选择参数: 全部分P (默认)")
    print(f"📺 将要下载的分P: P[1] (共 1 个)")

def test_with_real_downloader():
    """使用真实下载器测试"""
    print("\n🚀 使用真实下载器测试")
    print("=" * 50)
    
    # 导入下载器
    sys.path.insert(0, str(Path(__file__).parent / "src"))
    from yutto_plus.core import YuttoPlusDownloader
    from yutto_plus.config import YuttoPlusConfig
    
    # 创建配置
    config = YuttoPlusConfig()
    config.default_output_dir = "./Downloads"
    config.max_concurrent_downloads = 1
    
    # 创建下载器
    downloader = YuttoPlusDownloader(config)
    
    # 创建测试任务
    test_url = "https://www.bilibili.com/video/BV1ZB75zeEa5"
    task_config = {
        'episodes_selection': '~-1',
        'output_dir': './Downloads',
        'require_video': True,
        'require_audio': True,
        'require_danmaku': False,
        'require_cover': False
    }
    
    print(f"📋 添加测试任务:")
    print(f"   URL: {test_url}")
    print(f"   分P选择: {task_config['episodes_selection']}")
    
    # 添加任务
    tasks = [(test_url, task_config)]
    task_ids = downloader.add_download_tasks(tasks)
    
    print(f"✅ 任务已添加: {task_ids}")
    print(f"📊 活跃任务数: {len(downloader.active_tasks)}")
    
    # 检查任务配置
    for task_id in task_ids:
        if task_id in downloader.active_tasks:
            task = downloader.active_tasks[task_id]
            episodes_selection = task.task_config.get('episodes_selection')
            print(f"🔍 任务 {task_id} 分P配置: {episodes_selection}")

def test_print_visibility():
    """测试print输出是否可见"""
    print("\n🖨️ 测试print输出可见性")
    print("=" * 50)
    
    print("📋 这是一个测试print输出")
    print("📺 这是另一个测试print输出")
    
    # 模拟进度表格刷新
    print("\n🔄 模拟进度表格刷新...")
    for i in range(3):
        time.sleep(1)
        print(f"\r📊 进度: {(i+1)*33:.1f}%", end="", flush=True)
    
    print("\n")
    print("✅ 测试完成")

def main():
    """主函数"""
    print("🐛 分P确认显示调试工具")
    print("检查分P确认显示是否正常工作")
    print()
    
    # 运行各项测试
    test_direct_episodes_display()
    test_print_visibility()
    test_with_real_downloader()
    
    print("\n" + "=" * 50)
    print("🏁 调试总结")
    print("=" * 50)
    print("1. ✅ 直接测试分P确认显示逻辑 - 正常")
    print("2. ✅ 测试print输出可见性 - 正常")
    print("3. 📋 真实下载器测试 - 需要检查任务配置")
    print()
    print("💡 如果上述测试都正常，问题可能在于:")
    print("   - 分P确认显示的时机不对")
    print("   - 被进度表格刷新覆盖")
    print("   - 静默模式影响")
    print("   - 异步执行顺序问题")

if __name__ == "__main__":
    main()
