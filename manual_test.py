#!/usr/bin/env python3
"""
手动测试分P选择语法
"""

import re

def parse_url_with_parts(url_string: str):
    """WebUI的URL解析函数"""
    pattern = r'^(.+?)\|p=([^|]+)$'
    match = re.match(pattern, url_string.strip())
    if match:
        clean_url = match.group(1).strip()
        parts_selection = match.group(2).strip()
        if not clean_url or not ('bilibili.com' in clean_url or 'b23.tv' in clean_url):
            raise ValueError(f"无效的B站视频链接: {clean_url}")
        if not parts_selection.strip():
            raise ValueError(f"分P选择不能为空")
        if not re.match(r'^[0-9,~\-\$\s]+$', parts_selection):
            raise ValueError(f"无效的分P选择格式: {parts_selection}")
        return clean_url, parts_selection
    else:
        clean_url = url_string.strip()
        if not clean_url or not ('bilibili.com' in clean_url or 'b23.tv' in clean_url):
            raise ValueError(f"无效的B站视频链接: {clean_url}")
        return clean_url, None

def parse_episodes_selection(episodes_str: str, total_episodes: int):
    """CLI的分P解析函数"""
    if not episodes_str or episodes_str.strip() == "":
        return list(range(total_episodes))

    episodes_str = episodes_str.strip()
    episodes_str = episodes_str.replace('$', str(total_episodes))
    selected_indices = set()

    parts = episodes_str.split(',')
    for part in parts:
        part = part.strip()
        if not part:
            continue

        if '~' in part:
            if part.startswith('~') and not part.endswith('~'):
                end_str = part[1:]
                start_idx = 0
                if end_str.startswith('-'):
                    end_num = int(end_str)
                    end_idx = total_episodes + end_num - 1
                else:
                    end_idx = int(end_str) - 1 if end_str else total_episodes - 1
            elif part.endswith('~') and not part.startswith('~'):
                start_str = part[:-1]
                start_num = int(start_str)
                if start_num < 0:
                    start_idx = total_episodes + start_num
                else:
                    start_idx = start_num - 1
                end_idx = total_episodes - 1
            elif part == '~':
                start_idx = 0
                end_idx = total_episodes - 1
            else:
                start_str, end_str = part.split('~', 1)
                start_num = int(start_str) if start_str else 1
                end_num = int(end_str) if end_str else total_episodes

                if start_num < 0:
                    start_idx = total_episodes + start_num
                else:
                    start_idx = start_num - 1

                if end_num < 0:
                    end_idx = total_episodes + end_num - 1
                else:
                    end_idx = end_num - 1

            for i in range(max(0, start_idx), min(total_episodes, end_idx + 1)):
                selected_indices.add(i)
        else:
            episode_num = int(part)
            if episode_num < 0:
                idx = total_episodes + episode_num
            else:
                idx = episode_num - 1

            if 0 <= idx < total_episodes:
                selected_indices.add(idx)

    return sorted(list(selected_indices))

def test_complete_workflow():
    """测试完整工作流程"""
    print("🧪 完整工作流程测试")
    print("=" * 50)
    
    test_cases = [
        "https://www.bilibili.com/video/BV1234567890|p=1,3,5~8",
        "https://www.bilibili.com/video/BV1234567890|p=~3",
        "https://www.bilibili.com/video/BV1234567890|p=-2~",
        "https://www.bilibili.com/video/BV1234567890|p=~-2",
        "https://www.bilibili.com/video/BV1234567890|p=~",
        "https://www.bilibili.com/video/BV1234567890",
    ]
    
    total_episodes = 10
    
    for i, test_url in enumerate(test_cases, 1):
        try:
            print(f"{i}. 测试URL: {test_url}")
            
            # 步骤1：解析URL
            clean_url, parts_selection = parse_url_with_parts(test_url)
            print(f"   解析URL: {clean_url}")
            print(f"   分P参数: {parts_selection}")
            
            # 步骤2：解析分P选择
            if parts_selection:
                selected_indices = parse_episodes_selection(parts_selection, total_episodes)
            else:
                selected_indices = list(range(total_episodes))
            
            # 转换为1基索引显示
            selected_parts = [x + 1 for x in selected_indices]
            print(f"   选择分P: P{selected_parts}")
            print(f"   状态: ✅ 成功")
            
        except Exception as e:
            print(f"   状态: ❌ 失败")
            print(f"   错误: {e}")
        
        print()

if __name__ == "__main__":
    test_complete_workflow()
    print("🎉 手动测试完成！")
