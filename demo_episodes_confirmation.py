#!/usr/bin/env python3
"""
演示分P确认显示功能
展示CLI和WebUI如何显示分P选择确认信息
"""

import sys
from pathlib import Path

def demo_episodes_parsing():
    """演示分P解析功能"""
    print("🎬 分P选择语法演示")
    print("=" * 60)
    
    # 导入解析函数
    sys.path.insert(0, str(Path(__file__).parent / "src"))
    from yutto_plus.core import parse_episodes_selection
    
    # 演示用例
    demo_cases = [
        ("无参数", "", "下载所有分P"),
        ("~", "~", "明确指定下载所有分P"),
        ("1,3,5", "1,3,5", "下载指定分P"),
        ("1~5", "1~5", "下载范围分P"),
        ("~3", "~3", "下载前3个分P"),
        ("3~", "3~", "下载从第3个分P开始"),
        ("-2~", "-2~", "下载后2个分P"),
        ("~-2", "~-2", "除了最后两个其他全下载"),
        ("1,3,5~8", "1,3,5~8", "混合语法")
    ]
    
    total_episodes = 10
    
    print(f"📺 假设视频有 {total_episodes} 个分P")
    print()
    
    for i, (name, syntax, description) in enumerate(demo_cases, 1):
        try:
            # 解析分P选择
            selected_indices = parse_episodes_selection(syntax, total_episodes)
            selected_parts = [x + 1 for x in selected_indices]
            
            print(f"{i:2d}. {name}")
            print(f"    语法: {syntax if syntax else '(空)'}")
            print(f"    说明: {description}")
            print(f"    结果: P{selected_parts} (共 {len(selected_parts)} 个)")
            print()
            
        except Exception as e:
            print(f"{i:2d}. {name}")
            print(f"    语法: {syntax}")
            print(f"    错误: {e}")
            print()

def demo_url_parsing():
    """演示URL解析功能"""
    print("🔗 URL级别分P选择演示")
    print("=" * 60)
    
    # 导入解析函数
    sys.path.insert(0, str(Path(__file__).parent / "webui"))
    from app import parse_url_with_parts
    
    demo_urls = [
        "https://www.bilibili.com/video/BV1234567890",
        "https://www.bilibili.com/video/BV1234567890|p=1,3,5",
        "https://www.bilibili.com/video/BV1234567890|p=~3",
        "https://www.bilibili.com/video/BV1234567890|p=3~",
        "https://www.bilibili.com/video/BV1234567890|p=-2~",
        "https://www.bilibili.com/video/BV1234567890|p=~-2",
        "https://www.bilibili.com/video/BV1234567890|p=1,3,5~8",
        "https://www.bilibili.com/video/BV1234567890|p=~"
    ]
    
    for i, url in enumerate(demo_urls, 1):
        try:
            clean_url, parts_selection = parse_url_with_parts(url)
            
            print(f"{i}. URL解析演示")
            print(f"   输入: {url}")
            print(f"   视频URL: {clean_url}")
            print(f"   分P参数: {parts_selection if parts_selection else '(无，下载全部)'}")
            print()
            
        except Exception as e:
            print(f"{i}. URL解析演示")
            print(f"   输入: {url}")
            print(f"   错误: {e}")
            print()

def demo_cli_output_format():
    """演示CLI输出格式"""
    print("💻 CLI分P确认显示格式")
    print("=" * 60)
    
    examples = [
        {
            'scenario': '单个下载 - 指定分P',
            'command': 'yutto-plus-cli.py -p "1,3,5~8" "https://www.bilibili.com/video/BV123"',
            'output': [
                '📋 创建下载任务...',
                '🔗 URL: https://www.bilibili.com/video/BV123',
                '📺 分P选择: 1,3,5~8 (全局参数)',
                '📺 将要下载的分P: P[1, 3, 5, 6, 7, 8] (共 6 个)',
                '📦 内容: 视频, 音频, 弹幕, 封面'
            ]
        },
        {
            'scenario': '单个下载 - 默认全部',
            'command': 'yutto-plus-cli.py "https://www.bilibili.com/video/BV123"',
            'output': [
                '📋 创建下载任务...',
                '🔗 URL: https://www.bilibili.com/video/BV123',
                '📺 分P选择: 全部分P (默认)',
                '📺 将要下载的分P: P[1, 2, 3, 4, 5] (共 5 个)',
                '📦 内容: 视频, 音频, 弹幕, 封面'
            ]
        },
        {
            'scenario': 'URL级别分P选择',
            'command': 'yutto-plus-cli.py "https://www.bilibili.com/video/BV123|p=~-2"',
            'output': [
                '🔍 解析URL: https://www.bilibili.com/video/BV123',
                '   📺 分P选择: ~-2',
                '📋 创建下载任务...',
                '📺 分P选择: ~-2 (URL级别)',
                '📺 将要下载的分P: P[1, 2, 3] (共 3 个)'
            ]
        },
        {
            'scenario': '并行下载 - 混合分P',
            'command': 'yutto-plus-cli.py -c 2 -p "~3" "URL1" "URL2"',
            'output': [
                '📋 并行下载模式:',
                '   🎯 任务数量: 2',
                '   ⚡ 并发数量: 2',
                '   📺 任务 1 分P选择: ~3 (全局参数)',
                '   📺 任务 2 分P选择: ~3 (全局参数)',
                '✅ 创建任务: [\'task_001\', \'task_002\']'
            ]
        }
    ]
    
    for i, example in enumerate(examples, 1):
        print(f"{i}. {example['scenario']}")
        print(f"   命令: {example['command']}")
        print(f"   输出:")
        for line in example['output']:
            print(f"     {line}")
        print()

def demo_webui_display():
    """演示WebUI显示格式"""
    print("🌐 WebUI分P确认显示格式")
    print("=" * 60)
    
    print("1. 单个下载页面")
    print("   输入: https://www.bilibili.com/video/BV123|p=1,3,5~8")
    print("   后端日志:")
    print("     🔍 解析URL: https://www.bilibili.com/video/BV123")
    print("     📺 分P选择: 1,3,5~8")
    print("     📋 分P选择参数: 1,3,5~8")
    print("     📺 将要下载的分P: P[1, 3, 5, 6, 7, 8] (共 6 个)")
    print()
    
    print("2. 精准并行下载页面")
    print("   URL配置:")
    print("     URL 1: https://www.bilibili.com/video/BV123")
    print("     分P选择: ~3")
    print("     URL 2: https://www.bilibili.com/video/BV456|p=-2~")
    print("   后端日志:")
    print("     📺 将要下载的分P: P[1, 2, 3] (共 3 个)")
    print("     📺 将要下载的分P: P[9, 10] (共 2 个)")
    print()
    
    print("3. 前端显示")
    print("   - 下载开始时显示确认信息")
    print("   - 进度条显示当前下载的分P")
    print("   - 任务列表显示多P标识: 📺 3/5P")
    print("   - 状态恢复时显示分P信息")

def main():
    """主函数"""
    print("🎬 分P确认显示功能演示")
    print("展示用户如何清楚看到将要下载的分P")
    print()
    
    # 运行各项演示
    demo_episodes_parsing()
    demo_url_parsing()
    demo_cli_output_format()
    demo_webui_display()
    
    print("=" * 60)
    print("🎉 演示完成！")
    print()
    print("📋 功能总结:")
    print("✅ CLI显示分P选择参数和确认信息")
    print("✅ WebUI后端日志显示分P解析结果")
    print("✅ 支持完整的分P选择语法")
    print("✅ 单P和多P视频都有确认显示")
    print("✅ URL级别和全局参数都有来源标识")
    print()
    print("🚀 用户现在可以清楚知道将要下载哪些分P！")

if __name__ == "__main__":
    main()
