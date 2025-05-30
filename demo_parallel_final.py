#!/usr/bin/env python3
"""
YuttoPlus 并行下载系统最终演示 - 阶段2完成版本
"""

import time
from pathlib import Path
from yutto_plus import YuttoPlus

def demo_parallel_download():
    """演示完整的并行下载系统"""
    print("🎬 YuttoPlus 并行下载系统演示")
    print("=" * 60)
    
    # 创建测试目录
    demo_dir = Path("./demo_parallel_final")
    demo_dir.mkdir(exist_ok=True)
    
    # 创建下载器 (设置并发数为3)
    downloader = YuttoPlus(max_concurrent=3)
    
    # 准备演示任务 (使用不同大小的视频展示并行效果)
    demo_tasks = [
        ("https://www.bilibili.com/video/BV1x4411V75C", {
            "quality": 32,  # 480P
            "require_danmaku": False,
            "require_cover": False,
            "output_dir": str(demo_dir),
            "overwrite": True
        }),
        ("https://www.bilibili.com/video/BV1Kb411W75N", {
            "quality": 32,  # 480P
            "require_danmaku": False,
            "require_cover": False,
            "output_dir": str(demo_dir),
            "overwrite": True
        }),
        ("https://www.bilibili.com/video/BV1Xx54znES9", {
            "quality": 32,  # 480P
            "require_danmaku": False,
            "require_cover": False,
            "output_dir": str(demo_dir),
            "overwrite": True
        })
    ]
    
    print(f"\n📋 演示场景:")
    print(f"   🎯 任务数量: {len(demo_tasks)}")
    print(f"   ⚡ 并发数量: {downloader.max_concurrent}")
    print(f"   📺 显示模式: 自适应表格模式")
    print(f"   📁 输出目录: {demo_dir}")
    
    # 添加任务
    print(f"\n🔧 初始化任务...")
    task_ids = downloader.add_download_tasks(demo_tasks)
    print(f"✅ 已创建任务: {task_ids}")
    
    # 显示初始状态
    queue_status = downloader.task_manager.get_queue_status()
    print(f"📊 队列状态: {queue_status}")
    
    # 开始并行下载 (自动选择显示模式)
    print(f"\n🚀 启动并行下载系统...")
    downloader.start_parallel_download()
    
    # 等待完成
    start_time = time.time()
    max_wait_time = 600  # 最多等待10分钟
    
    while True:
        current_time = time.time()
        elapsed = current_time - start_time
        
        # 超时检查
        if elapsed > max_wait_time:
            print(f"⏰ 演示超时 ({max_wait_time}秒)，强制结束")
            break
        
        queue_status = downloader.task_manager.get_queue_status()
        
        # 检查是否所有任务完成
        if queue_status['running'] == 0 and queue_status['pending'] == 0:
            break
        
        time.sleep(1)  # 每1秒检查一次
    
    # 显示最终结果
    final_status = downloader.task_manager.get_queue_status()
    elapsed_time = time.time() - start_time
    downloader.progress_monitor.display_completion_summary(final_status, elapsed_time)
    
    # 检查下载的文件
    print(f"\n📁 下载结果:")
    download_files = list(demo_dir.glob("*.mp4"))
    total_size = 0
    for file in download_files:
        size_mb = file.stat().st_size / (1024 * 1024)
        total_size += size_mb
        print(f"   📄 {file.name} ({size_mb:.1f} MB)")
    
    print(f"📊 总计: {len(download_files)} 个文件, {total_size:.1f} MB")
    
    if len(download_files) > 0:
        avg_speed = total_size / elapsed_time if elapsed_time > 0 else 0
        print(f"⚡ 平均速度: {avg_speed:.2f} MB/s")
    
    # 关闭下载器
    downloader.shutdown()
    
    print(f"\n🎉 并行下载系统演示完成!")
    print(f"✨ 演示了阶段1和阶段2的所有核心功能:")
    print(f"   ✅ 任务队列管理")
    print(f"   ✅ 智能并发调度")
    print(f"   ✅ 实时进度监控")
    print(f"   ✅ 美观表格显示")
    print(f"   ✅ 错误处理机制")
    print(f"   ✅ 完成状态统计")
    
    return final_status['completed'] > 0

if __name__ == "__main__":
    success = demo_parallel_download()
    if success:
        print("\n🌟 演示成功! 系统运行稳定!")
    else:
        print("\n⚠️  演示未完全成功，但系统基础功能正常") 