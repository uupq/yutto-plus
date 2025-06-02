#!/usr/bin/env python3
"""
yutto-plus CLI - B站视频下载器命令行工具
基于纯 HTTP API 实现的现代化下载器
"""

import argparse
import sys
import time
import re
from pathlib import Path
from typing import Tuple, Optional, Dict

from . import YuttoPlus, TaskStatus, ConfigManager


def parse_url_with_parts(url_string: str) -> Tuple[str, Optional[str]]:
    """
    解析URL字符串，提取URL和分P参数

    Args:
        url_string: 可能包含分P参数的URL字符串

    Returns:
        tuple: (clean_url, parts_selection)

    Examples:
        parse_url_with_parts("https://www.bilibili.com/video/BV123|p=1,3,5")
        -> ("https://www.bilibili.com/video/BV123", "1,3,5")

        parse_url_with_parts("https://www.bilibili.com/video/BV123")
        -> ("https://www.bilibili.com/video/BV123", None)
    """
    # 使用正则表达式匹配URL末尾的分P参数
    # 模式: |p=分P选择 (必须在字符串末尾，分P选择不能为空)
    pattern = r'^(.+?)\|p=([^|]+)$'

    match = re.match(pattern, url_string.strip())
    if match:
        clean_url = match.group(1).strip()
        parts_selection = match.group(2).strip()

        # 验证URL的有效性
        if not clean_url or not ('bilibili.com' in clean_url or 'b23.tv' in clean_url):
            raise ValueError(f"无效的B站视频链接: {clean_url}")

        # 验证分P参数的基本格式（详细验证在下载器中进行）
        if not parts_selection.strip():
            raise ValueError(f"分P选择不能为空")
        if not re.match(r'^[0-9,~\-\$\s]+$', parts_selection):
            raise ValueError(f"无效的分P选择格式: {parts_selection}")

        return clean_url, parts_selection
    else:
        # 没有分P参数，返回原URL
        clean_url = url_string.strip()

        # 验证URL的有效性
        if not clean_url or not ('bilibili.com' in clean_url or 'b23.tv' in clean_url):
            raise ValueError(f"无效的B站视频链接: {clean_url}")

        return clean_url, None


def validate_parts_selection(parts_selection: str) -> bool:
    """
    验证分P选择参数的格式

    Args:
        parts_selection: 分P选择字符串

    Returns:
        bool: 是否有效
    """
    if not parts_selection:
        return False

    # 允许的字符：数字、逗号、波浪号、减号、美元符号、空格
    if not re.match(r'^[0-9,~\-\$\s]+$', parts_selection):
        return False

    # 基本格式检查（详细验证在下载器中进行）
    # 这里只做基础的语法检查
    try:
        # 移除空格
        clean_parts = parts_selection.replace(' ', '')

        # 特殊情况：单独的$符号
        if clean_parts == '$':
            return True

        # 检查是否有连续的特殊字符
        if re.search(r'[,~\-]{2,}', clean_parts):
            return False

        # 检查是否以逗号开头或结尾
        if clean_parts.startswith(',') or clean_parts.endswith(','):
            return False

        return True
    except:
        return False


def get_episodes_info_sync(url: str, episodes_selection: Optional[str]) -> Optional[Dict]:
    """
    同步获取视频的分P信息

    Args:
        url: 视频URL
        episodes_selection: 分P选择参数

    Returns:
        Dict: 包含selected_parts和count的字典，如果获取失败返回None
    """
    try:
        import asyncio
        import sys
        from pathlib import Path

        # 确保能够导入模块
        current_dir = Path(__file__).parent
        if str(current_dir) not in sys.path:
            sys.path.insert(0, str(current_dir))

        from yutto_plus.api import BilibiliAPIClient
        from yutto_plus.core import parse_episodes_selection

        async def get_video_info():
            async with BilibiliAPIClient() as client:
                video_info = await client.get_video_info(url)
                return video_info

        # 运行异步函数获取视频信息
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            video_info = loop.run_until_complete(get_video_info())
        finally:
            loop.close()

        if not video_info or 'pages' not in video_info:
            return None

        total_pages = len(video_info['pages'])

        if episodes_selection:
            selected_indices = parse_episodes_selection(episodes_selection, total_pages)
            selected_parts = [i+1 for i in selected_indices]
        else:
            # 默认下载全部
            selected_parts = list(range(1, total_pages + 1))

        return {
            'selected_parts': selected_parts,
            'count': len(selected_parts),
            'total_pages': total_pages
        }

    except Exception:
        return None


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='yutto-plus - 现代化 B站视频下载器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 单个视频下载
  %(prog)s "https://www.bilibili.com/video/BV1LWjXzvEX1/"
  %(prog)s -q 127 -o "./Downloads" "https://www.bilibili.com/video/BV1LWjXzvEX1/"
  %(prog)s --audio-only -af mp3 -ab 192k "https://www.bilibili.com/video/BV1LWjXzvEX1/"

  # 多P视频下载
  %(prog)s -p "1,3,5~8" "https://www.bilibili.com/video/BV1unjgzqEms/"  # 下载指定分P
  %(prog)s -p "~3" "https://www.bilibili.com/video/BV1unjgzqEms/"       # 下载前3P
  %(prog)s -p "-2~" "https://www.bilibili.com/video/BV1unjgzqEms/"      # 下载后2P
  %(prog)s -p "~-2" "https://www.bilibili.com/video/BV1unjgzqEms/"      # 除了最后2P
  %(prog)s --no-folder "https://www.bilibili.com/video/BV1unjgzqEms/"   # 不创建文件夹

  # URL级别分P选择（新功能）
  %(prog)s "https://www.bilibili.com/video/BV1111111111|p=1,3,5" "https://www.bilibili.com/video/BV2222222222|p=2~4"
  %(prog)s -p "1~3" "https://www.bilibili.com/video/BV1111111111|p=5" "https://www.bilibili.com/video/BV2222222222"

  # 并行下载多个视频
  %(prog)s -c 3 "https://www.bilibili.com/video/BV1LWjXzvEX1/" "https://www.bilibili.com/video/BV1234567890/"
  %(prog)s -c 2 --parallel-display simple "url1" "url2" "url3"
  
  # 启动Web界面
  %(prog)s --webui                    # 启动Web UI
  %(prog)s --webui --port 8080        # 指定端口启动Web UI
  
  # 使用配置文件
  %(prog)s --create-config high_quality  # 创建高清下载配置
  %(prog)s --config yutto-plus-high_quality.json "url1" "url2"
  %(prog)s --config my_config.json -c 4 "url1" "url2"  # 配置文件+命令行参数
  
  # 其他选项
  %(prog)s --no-danmaku --no-cover "https://www.bilibili.com/video/BV1LWjXzvEX1/"
  %(prog)s --no-resume "https://www.bilibili.com/video/BV1LWjXzvEX1/"

支持的视频质量:
  127: 8K 超高清    120: 4K 超清      116: 1080P60    112: 1080P+
  80:  1080P 高清   64:  720P 高清    32:  480P 清晰  16:  360P 流畅

支持的音频质量:
  30251: Hi-Res 无损  30280: 320kbps  30232: 128kbps  30216: 64kbps

并行下载功能:
  使用 -c/--concurrent 指定并发数量 (默认: 1)
  使用 --parallel-display 选择显示模式 (table/simple/silent)
  支持表格刷新显示，动态任务管理，智能调度

配置文件功能:
  支持JSON和YAML格式的配置文件
  使用 --create-config 创建示例配置文件
  使用 --list-configs 查看可用模板
  配置文件可以设置所有参数，命令行参数优先级更高

Web界面功能:
  使用 --webui 启动现代化Web界面
  支持并行下载、配置文件管理、实时进度监控
  使用 --port 指定Web服务器端口 (默认: 12001)
  使用 --no-browser 禁止自动打开浏览器

多P视频支持:
  自动检测多P视频，为多P视频创建专门文件夹
  使用 -p/--episodes 选择要下载的分P，支持范围和列表语法
  支持语法: "1,3,5~8", "~3", "-2~", "~-2", "~", "$" 等
  使用 --no-folder 禁止为多P视频创建文件夹

  URL级别分P选择（新功能）:
  在URL末尾使用 |p=分P选择 为单个视频指定分P
  语法: "URL|p=1,3,5" 或 "URL|p=2~4" 或 "URL|p=~-2"
  URL级别配置优先级高于全局 -p 参数
  支持混合使用：全局配置 + URL级别配置

断点续传功能:
  默认启用断点续传，下载中断后重新运行可从断点继续
  使用 --no-resume 禁用断点续传，强制重新下载
  使用 -w/--overwrite 覆盖现有文件（同时禁用断点续传）
        """
    )
    
    # 位置参数（Web模式下可选）
    parser.add_argument(
        'urls',
        nargs='*',  # 改为可选，Web模式下不需要URL
        help='B站视频链接，支持多个链接进行并行下载'
    )
    
    # Web界面参数
    parser.add_argument(
        '--webui',
        action='store_true',
        help='启动Web界面'
    )
    
    parser.add_argument(
        '--port',
        type=int,
        default=12001,
        help='Web界面端口 (默认: 12001)'
    )
    
    parser.add_argument(
        '--no-browser',
        action='store_true',
        help='启动Web界面时不自动打开浏览器'
    )
    
    # 基础参数
    parser.add_argument(
        '-q', '--quality',
        type=int,
        default=80,
        choices=[16, 32, 64, 74, 80, 100, 112, 116, 120, 125, 126, 127],
        help='视频质量 (默认: 80 - 1080P)'
    )
    
    parser.add_argument(
        '-aq', '--audio-quality',
        type=int,
        default=30280,
        choices=[30216, 30232, 30280, 30251],
        help='音频质量 (默认: 30280 - 320kbps)'
    )
    
    parser.add_argument(
        '-o', '--output',
        type=str,
        default='./Downloads',
        help='输出目录 (默认: ./Downloads)'
    )
    
    parser.add_argument(
        '-f', '--format',
        choices=['mp4', 'mkv', 'mov'],
        default='mp4',
        help='输出格式 (默认: mp4)'
    )
    
    parser.add_argument(
        '-w', '--overwrite',
        action='store_true',
        help='覆盖已存在文件'
    )
    
    parser.add_argument(
        '--no-resume',
        action='store_true',
        help='禁用断点续传，总是重新下载'
    )
    
    # 高级参数
    parser.add_argument(
        '--video-codec',
        choices=['avc', 'hevc', 'av1'],
        default='avc',
        help='视频编码偏好 (默认: avc)'
    )
    
    parser.add_argument(
        '--sessdata',
        type=str,
        help='B站登录凭证'
    )
    
    # 资源选择参数
    parser.add_argument(
        '--audio-only',
        action='store_true',
        help='仅下载音频'
    )
    
    parser.add_argument(
        '--no-video',
        action='store_true',
        help='不下载视频'
    )
    
    parser.add_argument(
        '--no-danmaku',
        action='store_true',
        help='不下载弹幕'
    )
    
    parser.add_argument(
        '--no-cover',
        action='store_true',
        help='不下载封面'
    )
    
    parser.add_argument(
        '-df', '--danmaku-format',
        choices=['xml', 'ass', 'protobuf'],
        default='ass',
        help='弹幕格式 (默认: ass)'
    )
    
    parser.add_argument(
        '-ab', '--audio-bitrate',
        choices=['320k', '256k', '192k', '128k', '96k'],
        default='192k',
        help='仅音频模式的比特率 (默认: 192k)'
    )
    
    parser.add_argument(
        '-af', '--audio-format',
        choices=['mp3', 'wav', 'flac', 'm4a', 'aac'],
        default='mp3',
        help='音频格式 (默认: mp3)'
    )
    
    # 输出控制
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='安静模式，减少输出'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='详细模式，显示调试信息'
    )
    
    # 并行下载参数
    parser.add_argument(
        '-c', '--concurrent',
        type=int,
        default=1,
        help='并发下载数量 (默认: 1)'
    )
    
    parser.add_argument(
        '--parallel-display',
        choices=['table', 'simple', 'silent'],
        default='table',
        help='并行模式显示类型 (默认: table)'
    )
    
    # 配置文件参数
    parser.add_argument(
        '--config',
        type=str,
        help='配置文件路径 (支持JSON/YAML格式)'
    )
    
    parser.add_argument(
        '--create-config',
        choices=['default', 'high_quality', 'audio_only', 'batch_download'],
        help='创建示例配置文件并退出'
    )
    
    parser.add_argument(
        '--list-configs',
        action='store_true',
        help='列出可用的配置模板并退出'
    )

    # 多P视频参数
    parser.add_argument(
        '-p', '--episodes',
        type=str,
        help='选择要下载的分P，支持范围和列表，如 "1,3,5~8" 或 "~3,10,-2~,~-2"'
    )

    parser.add_argument(
        '--no-folder',
        action='store_true',
        help='多P视频不创建文件夹，直接保存到输出目录'
    )

    # UP主投稿视频下载参数
    parser.add_argument(
        '--uploader',
        type=str,
        help='UP主空间URL或UID，下载该UP主的所有投稿视频 (例如: https://space.bilibili.com/123456 或 123456)'
    )

    parser.add_argument(
        '--update-uploader',
        action='store_true',
        help='更新已存在的UP主视频列表，检查新投稿。如果没有指定--uploader，则更新当前目录下所有符合格式的UP主文件夹'
    )

    parser.add_argument(
        '--list-only',
        action='store_true',
        help='仅获取并显示UP主视频列表，不进行下载'
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='强制更新，忽略CSV文件的保存时间检查'
    )

    parser.add_argument(
        '--delete-uploader',
        type=str,
        help='删除指定目录下所有UP主文件夹中的视频文件（保留CSV记录）'
    )

    return parser.parse_args()


def format_size(bytes_size):
    """格式化文件大小"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} TB"


def format_speed(speed_bps):
    """格式化下载速度"""
    return format_size(speed_bps) + "/s"


def main():
    """主函数"""
    try:
        args = parse_args()
        config_manager = ConfigManager()
        
        # 处理WebUI启动
        if args.webui:
            start_webui(args)
            return
        
        # 处理配置文件相关的特殊操作
        if args.create_config:
            output_file = f"yutto-plus-{args.create_config}.json"
            config_manager.create_sample_config(output_file, args.create_config)
            print(f"\n🎉 配置文件已创建: {output_file}")
            print(f"💡 使用方式: python yutto-plus.py --config {output_file} [URLs...]")
            return
        
        if args.list_configs:
            print("📋 可用的配置模板:")
            for style, desc in config_manager.list_builtin_configs().items():
                print(f"  {style}: {desc}")
            print(f"\n💡 创建配置文件: python yutto-plus.py --create-config [模板名称]")
            return
        
        # 处理UP主投稿视频下载
        if args.uploader or args.update_uploader:
            handle_uploader_download(args, config_manager)
            return

        # 处理UP主文件删除
        if args.delete_uploader:
            handle_uploader_delete(args, config_manager)
            return

        # 验证URL（非WebUI模式下必需）
        if not args.urls:
            print("❌ 错误: 请提供有效的B站视频链接")
            print("💡 提示: 使用 --webui 启动Web界面，或提供视频链接")
            sys.exit(1)
        
        # 加载配置文件（如果指定）
        config = {}
        if args.config:
            try:
                config = config_manager.load_config(args.config)
                if not config_manager.validate_config(config):
                    print("❌ 配置文件验证失败")
                    sys.exit(1)
                print(f"✅ 已加载配置文件: {args.config}")
            except Exception as e:
                print(f"❌ 配置文件错误: {e}")
                sys.exit(1)
        
        # 命令行参数覆盖配置文件参数
        args = merge_config_with_args(config, args)
        
        # 输出横幅
        if not args.quiet:
            print("🚀 yutto-plus - 现代化 B站视频下载器")
            print("=" * 50)
            if config:
                description = config.get('description', '')
                if description:
                    print(f"📝 配置: {description}")
        
        # 解析和验证所有URL
        parsed_urls = []
        for url_string in args.urls:
            try:
                clean_url, url_parts = parse_url_with_parts(url_string)
                parsed_urls.append((clean_url, url_parts))

                # 如果URL包含分P参数，显示解析结果
                if url_parts and not args.quiet:
                    print(f"🔍 解析URL: {clean_url}")
                    print(f"   📺 分P选择: {url_parts}")

            except ValueError as e:
                print(f"❌ 错误: {e}")
                sys.exit(1)

        # 更新args.urls为解析后的URL列表（保持向后兼容）
        args.urls = [url for url, _ in parsed_urls]
        args.parsed_urls = parsed_urls  # 添加解析结果

        # 立即进行分P预分析和确认显示
        if not args.quiet:
            print("\n📋 分P选择确认:")
            print("=" * 30)

            for i, (clean_url, url_parts) in enumerate(parsed_urls):
                # 确定最终的分P选择：URL级别 > 全局参数
                final_episodes_selection = url_parts if url_parts else args.episodes

                print(f"📺 视频 {i+1}: {clean_url}")

                # 显示分P选择参数
                if final_episodes_selection:
                    source = "URL级别" if url_parts else "全局参数"
                    print(f"   🎯 分P选择: {final_episodes_selection} ({source})")
                else:
                    print(f"   🎯 分P选择: 全部分P (默认)")

                # 立即获取视频信息并显示具体分P列表
                try:
                    print(f"   🔍 正在获取视频信息...")

                    # 使用新的分P确认函数
                    import asyncio
                    from yutto_plus.core import BilibiliAPIClient

                    async def get_confirmation():
                        async with BilibiliAPIClient() as client:
                            return await client.get_episodes_confirmation(clean_url, final_episodes_selection)

                    # 运行异步函数
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        selected_parts = loop.run_until_complete(get_confirmation())
                        print(f"   ✅ 分P确认完成")
                    finally:
                        loop.close()

                except Exception as e:
                    print(f"   ❌ 获取分P信息失败: {str(e)}")
                    print(f"   📋 将在下载时重新获取分P信息")

                print()  # 空行分隔

            print("=" * 30)
        
        # 判断是单个下载还是并行下载
        if len(args.urls) == 1 and args.concurrent == 1:
            # 单个下载模式
            single_download_mode(args)
        else:
            # 并行下载模式
            parallel_download_mode(args)
        
        if not args.quiet:
            print("\n🎉 任务完成!")
    
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断下载")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


def single_download_mode(args):
    """单个下载模式"""
    url = args.urls[0]

    # 获取URL级别的分P参数（如果有）
    url_parts = None
    if hasattr(args, 'parsed_urls') and args.parsed_urls:
        _, url_parts = args.parsed_urls[0]

    # 确定最终的分P选择：URL级别 > 全局参数
    final_episodes_selection = url_parts if url_parts else args.episodes

    # 创建下载器
    downloader = YuttoPlus(
        sessdata=args.sessdata,
        default_output_dir=args.output,
        default_quality=args.quality,
        default_audio_quality=args.audio_quality,
        default_video_codec=args.video_codec,
        default_output_format=args.format,
        overwrite=args.overwrite,
        enable_resume=not args.no_resume
    )

    # 处理资源选择逻辑
    require_video, require_audio, require_danmaku, require_cover = get_requirements(args)

    # 验证参数逻辑
    if not any([require_video, require_audio, require_danmaku, require_cover]):
        print("❌ 错误: 没有选择任何下载内容")
        sys.exit(1)

    # 创建下载任务
    if not args.quiet:
        print(f"📋 创建下载任务...")
        print(f"🔗 URL: {url}")
        print(f"🎯 质量: {args.quality} (视频) / {args.audio_quality} (音频)")
        print(f"📁 输出: {args.output}")

        # 显示分P选择信息
        if final_episodes_selection:
            source = "URL级别" if url_parts else "全局参数"
            print(f"📺 分P选择: {final_episodes_selection} ({source})")
        else:
            print(f"📺 分P选择: 全部分P (默认)")

        # 显示将要下载的内容
        download_items = get_download_items(args, require_video, require_audio, require_danmaku, require_cover)
        print(f"📦 内容: {', '.join(download_items)}")
        print()

    task = downloader.create_download_task(
        url,
        quality=args.quality,
        audio_quality=args.audio_quality,
        output_dir=args.output,
        output_format=args.format,
        require_video=require_video,
        require_audio=require_audio,
        require_danmaku=require_danmaku,
        require_cover=require_cover,
        danmaku_format=args.danmaku_format,
        audio_format=args.audio_format,
        audio_only=args.audio_only,
        audio_bitrate=args.audio_bitrate,
        episodes_selection=final_episodes_selection,
        create_folder_for_multi_p=not args.no_folder
    )
    
    # 设置回调并运行单个任务
    setup_single_task_callbacks(task, args)
    
    # 等待完成
    while True:
        status = task.get_status()
        if status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
            break
        time.sleep(0.1)


def parallel_download_mode(args):
    """并行下载模式"""
    # 创建下载器
    downloader = YuttoPlus(
        sessdata=args.sessdata,
        default_output_dir=args.output,
        default_quality=args.quality,
        default_audio_quality=args.audio_quality,
        default_video_codec=args.video_codec,
        default_output_format=args.format,
        overwrite=args.overwrite,
        enable_resume=not args.no_resume,
        max_concurrent=args.concurrent
    )
    
    # 处理资源选择逻辑
    require_video, require_audio, require_danmaku, require_cover = get_requirements(args)
    
    # 验证参数逻辑
    if not any([require_video, require_audio, require_danmaku, require_cover]):
        print("❌ 错误: 没有选择任何下载内容")
        sys.exit(1)
    
    if not args.quiet:
        print(f"📋 并行下载模式:")
        print(f"   🎯 任务数量: {len(args.urls)}")
        print(f"   ⚡ 并发数量: {args.concurrent}")
        print(f"   📺 显示模式: {args.parallel_display}")
        print(f"   🎯 质量: {args.quality} (视频) / {args.audio_quality} (音频)")
        print(f"   📁 输出: {args.output}")
        
        # 显示将要下载的内容
        download_items = get_download_items(args, require_video, require_audio, require_danmaku, require_cover)
        print(f"   📦 内容: {', '.join(download_items)}")
        print()
    
    # 创建任务列表
    tasks = []
    for i, url in enumerate(args.urls):
        # 获取URL级别的分P参数（如果有）
        url_parts = None
        if hasattr(args, 'parsed_urls') and args.parsed_urls and i < len(args.parsed_urls):
            _, url_parts = args.parsed_urls[i]

        # 确定最终的分P选择：URL级别 > 全局参数
        final_episodes_selection = url_parts if url_parts else args.episodes

        task_config = {
            "quality": args.quality,
            "audio_quality": args.audio_quality,
            "output_dir": args.output,
            "output_format": args.format,
            "require_video": require_video,
            "require_audio": require_audio,
            "require_danmaku": require_danmaku,
            "require_cover": require_cover,
            "danmaku_format": args.danmaku_format,
            "audio_format": args.audio_format,
            "audio_only": args.audio_only,
            "audio_bitrate": args.audio_bitrate,
            "episodes_selection": final_episodes_selection,
            "create_folder_for_multi_p": not args.no_folder
        }
        tasks.append((url, task_config))

        # 在详细模式下显示每个任务的分P配置，并立即获取视频信息显示具体分P
        if not args.quiet:
            if final_episodes_selection:
                source = "URL级别" if url_parts else "全局参数"
                print(f"   📺 任务 {i+1} 分P选择: {final_episodes_selection} ({source})")
            else:
                print(f"   📺 任务 {i+1} 分P选择: 全部分P (默认)")

            # 立即获取视频信息并显示具体分P列表
            try:
                episodes_info = get_episodes_info_sync(url, final_episodes_selection)
                if episodes_info:
                    print(f"   📋 将要下载的分P: P{episodes_info['selected_parts']} (共 {episodes_info['count']} 个)")
                else:
                    print(f"   📋 将在下载时确定具体分P")
            except Exception as e:
                print(f"   📋 获取分P信息失败: {str(e)[:50]}...")
    
    # 添加任务并开始下载
    task_ids = downloader.add_download_tasks(tasks)
    
    if not args.quiet:
        print(f"✅ 创建任务: {task_ids}")
        print(f"\n🚀 启动并行下载...")
    
    # 启动并行下载
    display_mode = args.parallel_display if not args.quiet else 'silent'
    downloader.start_parallel_download(display_mode=display_mode)
    
    # 等待完成
    start_time = time.time()
    while True:
        queue_status = downloader.task_manager.get_queue_status()
        
        # 检查是否所有任务完成
        if queue_status['running'] == 0 and queue_status['pending'] == 0:
            break
        
        time.sleep(1)
    
    # 显示最终结果
    final_status = downloader.task_manager.get_queue_status()
    elapsed_time = time.time() - start_time
    tasks_info = downloader.get_tasks_summary_info()
    
    downloader.progress_monitor.display_completion_summary(final_status, elapsed_time, tasks_info)
    
    # 关闭下载器
    downloader.shutdown()


def get_requirements(args):
    """获取资源需求设置"""
    if args.audio_only:
        # 仅音频模式
        require_video = False
        require_audio = True
        require_danmaku = not args.no_danmaku
        require_cover = not args.no_cover
    else:
        # 正常模式（默认下载视频+音频）
        require_video = not args.no_video
        require_audio = True  # 只要不是audio_only模式，总是需要音频
        require_danmaku = not args.no_danmaku
        require_cover = not args.no_cover
    
    return require_video, require_audio, require_danmaku, require_cover


def get_download_items(args, require_video, require_audio, require_danmaku, require_cover):
    """获取下载项目列表"""
    download_items = []
    if require_video:
        download_items.append("视频")
    if require_audio:
        if args.audio_only:
            download_items.append(f"音频({args.audio_format})")
        else:
            download_items.append("音频")
    if require_danmaku:
        download_items.append(f"弹幕({args.danmaku_format})")
    if require_cover:
        download_items.append("封面")
    return download_items


def setup_single_task_callbacks(task, args):
    """设置单个任务的回调函数"""
    last_percentage = 0
    last_status = None
    
    def on_progress(current_bytes, total_bytes, speed_bps, item_name):
        nonlocal last_percentage
        if args.quiet:
            return
            
        percentage = (current_bytes / total_bytes * 100) if total_bytes > 0 else 0
        
        # 只在进度有明显变化时更新（减少终端输出频率）
        if abs(percentage - last_percentage) >= 1:
            current_size = format_size(current_bytes)
            total_size = format_size(total_bytes)
            speed = format_speed(speed_bps)
            
            # 使用 \r 实现同行更新，确保进度不超过100%
            display_percentage = min(100.0, percentage)
            print(f"\r📊 进度: {display_percentage:5.1f}% | {current_size}/{total_size} | ⚡ {speed}    ", end='', flush=True)
            last_percentage = percentage
    
    def on_stream_info(stream_info):
        if args.quiet:
            return
            
        # 检查是否是状态更新
        if 'status' in stream_info:
            status = stream_info['status']
            if status == 'downloading':
                print(f"\n📥 开始下载...")
            elif status == 'merging':
                if args.audio_only:
                    print(f"\n🎵 正在转换音频格式...")
                else:
                    print(f"\n🔄 正在合并音视频...")
        else:
            # 流信息
            print(f"🎬 流信息:")
            if 'selected_video_stream_info' in stream_info:
                print(f"  📺 视频: {stream_info['selected_video_stream_info']}")
            if 'selected_audio_stream_info' in stream_info:
                print(f"  🔊 音频: {stream_info['selected_audio_stream_info']}")
            print()
    
    def on_completion(success, result_info, error_message):
        nonlocal last_status
        if not args.quiet:
            print()  # 换行

        if success:
            if not args.quiet:
                if result_info.get('type') == 'multi_p':
                    # 多P视频结果
                    print("✅ 多P视频下载完成!")
                    print(f"📁 输出目录: {result_info['output_dir']}")
                    print(f"📺 视频标题: {result_info['video_title']}")
                    print(f"📊 下载统计: {len(result_info['downloaded_parts'])}/{result_info['total_parts']} 个分P")

                    if result_info['downloaded_parts']:
                        print("✅ 成功下载的分P:")
                        for part in result_info['downloaded_parts']:
                            print(f"   P{part['index']:02d}: {part['title']}")

                    if result_info['failed_parts']:
                        print("❌ 失败的分P:")
                        for part in result_info['failed_parts']:
                            print(f"   P{part['index']:02d}: {part['title']} ({part['error']})")
                else:
                    # 单P视频结果
                    print("✅ 下载完成!")
                    print(f"📁 文件路径: {result_info['output_filepath']}")
                    if 'selected_video_stream_info' in result_info:
                        print(f"📺 视频流: {result_info['selected_video_stream_info']}")
                    if 'selected_audio_stream_info' in result_info:
                        print(f"🔊 音频流: {result_info['selected_audio_stream_info']}")
            else:
                if result_info.get('type') == 'multi_p':
                    print(f"✅ 多P视频: {result_info['output_dir']}")
                else:
                    print(f"✅ {result_info['output_filepath']}")
        else:
            print(f"❌ 下载失败: {error_message}")
            sys.exit(1)
    
    # 启动下载
    task.start(
        progress_callback=on_progress,
        stream_info_callback=on_stream_info,
        completion_callback=on_completion
    )
    
    # 状态监控
    while True:
        status = task.get_status()
        
        # 状态变化时显示
        if status != last_status and not args.quiet:
            if status == TaskStatus.EXTRACTING:
                print("🔍 正在获取视频信息...")
            elif status == TaskStatus.DOWNLOADING:
                pass  # 在 stream_info 回调中处理
            elif status == TaskStatus.MERGING:
                pass  # 在 stream_info 回调中处理
            elif status == TaskStatus.COMPLETED:
                break
            elif status == TaskStatus.FAILED:
                break
                
            last_status = status
        
        if status in [TaskStatus.COMPLETED, TaskStatus.FAILED]:
            break
            
        time.sleep(0.1)


def merge_config_with_args(config: dict, args):
    """将配置文件参数与命令行参数合并（命令行参数优先）"""
    # 创建一个参数映射，将配置文件的键映射到args属性
    config_to_args_mapping = {
        'quality': 'quality',
        'audio_quality': 'audio_quality',
        'output_dir': 'output',
        'format': 'format',
        'overwrite': 'overwrite',
        'enable_resume': 'no_resume',  # 注意这个是反向的
        'concurrent': 'concurrent',
        'parallel_display': 'parallel_display',
        'audio_only': 'audio_only',
        'no_video': 'no_video',
        'no_danmaku': 'no_danmaku',
        'no_cover': 'no_cover',
        'danmaku_format': 'danmaku_format',
        'audio_format': 'audio_format',
        'audio_bitrate': 'audio_bitrate',
        'video_codec': 'video_codec',
        'quiet': 'quiet',
        'verbose': 'verbose',
        'sessdata': 'sessdata',
        'episodes_selection': 'episodes',
        'create_folder_for_multi_p': 'no_folder'  # 注意这个是反向的
    }

    # 忽略的配置项（不会产生警告）
    ignored_config_keys = {
        'description',  # 配置文件描述信息
        # 可以在这里添加其他需要忽略的配置项
    }
    
    # 只有当命令行参数是默认值时，才使用配置文件的值
    parser = parse_args.__wrapped__ if hasattr(parse_args, '__wrapped__') else None
    
    for config_key, args_attr in config_to_args_mapping.items():
        if config_key in config:
            config_value = config[config_key]
            current_value = getattr(args, args_attr, None)
            
            # 特殊处理反向参数
            if config_key == 'enable_resume':
                # 如果命令行没有指定--no-resume，使用配置文件的enable_resume设置
                if not args.no_resume:  # 默认情况下no_resume是False
                    args.no_resume = not config_value
            elif config_key == 'create_folder_for_multi_p':
                # 如果命令行没有指定--no-folder，使用配置文件的create_folder_for_multi_p设置
                if not args.no_folder:  # 默认情况下no_folder是False
                    args.no_folder = not config_value
            else:
                # 对于其他参数，只有当命令行参数是默认值时才使用配置文件的值
                # 这里简化处理：除了一些特殊情况，都直接使用配置文件的值
                if config_key in ['quality', 'audio_quality', 'output_dir', 'format', 'concurrent', 'parallel_display',
                                 'danmaku_format', 'audio_format', 'audio_bitrate', 'video_codec']:
                    # 对于这些参数，如果是默认值则使用配置文件
                    default_values = {
                        'quality': 80,
                        'audio_quality': 30280,
                        'output': './Downloads',
                        'format': 'mp4',
                        'concurrent': 1,
                        'parallel_display': 'table',
                        'danmaku_format': 'ass',
                        'audio_format': 'mp3',
                        'audio_bitrate': '192k',
                        'video_codec': 'avc'
                    }
                    
                    if current_value == default_values.get(args_attr):
                        setattr(args, args_attr, config_value)
                
                elif config_key in ['audio_only', 'no_video', 'no_danmaku', 'no_cover', 'overwrite', 'quiet', 'verbose']:
                    # 对于布尔参数，如果配置文件设为True，则设置args
                    if config_value:
                        setattr(args, args_attr, True)
                
                elif config_key == 'sessdata':
                    # 对于sessdata，如果命令行没有指定且配置文件有值，则使用配置文件
                    if not current_value and config_value:
                        setattr(args, args_attr, config_value)

    # 检查是否有未识别的配置项
    for config_key in config:
        if config_key not in config_to_args_mapping and config_key not in ignored_config_keys:
            print(f"⚠️  未知配置项: {config_key}")

    return args


def start_webui(args):
    """启动Web界面"""
    try:
        print("🚀 启动 YuttoPlus Web UI v2.0")
        print("=" * 50)
        
        # 动态导入WebUI模块
        webui_path = Path(__file__).parent.parent.parent / "webui"
        if not webui_path.exists():
            print("❌ 错误: 找不到WebUI目录")
            print("💡 请确保webui目录存在")
            sys.exit(1)
        
        # 添加webui目录到路径
        sys.path.insert(0, str(webui_path))
        
        try:
            from app import socketio, app, find_available_port, open_browser_delayed
            import threading
        except ImportError as e:
            print(f"❌ 错误: 无法导入WebUI模块: {e}")
            print("💡 请确保安装了Flask和Flask-SocketIO:")
            print("   pip install flask flask-socketio")
            sys.exit(1)
        
        # 查找可用端口
        if args.port != 12001:
            # 用户指定了端口，直接使用
            port = args.port
            try:
                import socket
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('', port))
            except OSError:
                print(f"❌ 错误: 端口 {port} 已被占用")
                sys.exit(1)
        else:
            # 自动查找可用端口
            port = find_available_port()
            if not port:
                print("❌ 无法找到可用端口")
                sys.exit(1)
        
        print(f"🌐 Web UI 地址: http://localhost:{port}")
        print("📋 功能特性:")
        print("   • 🔥 并行下载支持")
        print("   • ⚙️ 配置文件管理")
        print("   • 📊 实时进度监控")
        print("   • 🖥️ 现代化界面")
        print("   • 🔄 多会话支持")
        print("\n💡 使用提示:")
        print("   • 在浏览器中打开上述地址")
        print("   • 支持同时下载多个视频")
        print("   • 可以加载预设配置文件")
        print("   • 按Ctrl+C退出服务器")
        
        # 延迟打开浏览器（如果未禁用）
        if not args.no_browser:
            threading.Thread(
                target=open_browser_delayed, 
                args=(f"http://localhost:{port}",), 
                daemon=True
            ).start()
            print("\n🌐 浏览器将自动打开...")
        else:
            print("\n🌐 请手动在浏览器中打开上述地址")
        
        print()  # 空行
        
        # 启动服务器
        socketio.run(app, host='0.0.0.0', port=port, debug=False)
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Web服务器已停止")
    except Exception as e:
        print(f"\n❌ 启动WebUI时发生错误: {e}")
        if hasattr(args, 'verbose') and args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


def handle_uploader_download(args, config_manager):
    """处理UP主投稿视频下载"""
    import asyncio
    from yutto_plus.core import parse_up_space_url, UploaderVideoManager

    # 检查是否是批量更新模式
    if args.update_uploader and not args.uploader:
        # 批量更新当前目录下所有符合格式的UP主文件夹
        print("🔄 批量更新模式：扫描当前目录下的UP主文件夹")
        asyncio.run(batch_update_uploaders(args, config_manager))
        return

    # 解析UP主UID
    uid = None
    if args.uploader.isdigit():
        # 直接是UID
        uid = int(args.uploader)
    else:
        # 尝试从URL解析UID
        uid = parse_up_space_url(args.uploader)
        if uid is None:
            print(f"❌ 错误: 无法从URL解析UP主UID: {args.uploader}")
            print("💡 支持的格式: https://space.bilibili.com/UID 或直接输入UID")
            sys.exit(1)

    # 加载配置文件（如果指定）
    config = {}
    if args.config:
        try:
            config = config_manager.load_config(args.config)
            if not config_manager.validate_config(config):
                print("❌ 配置文件验证失败")
                sys.exit(1)
            print(f"✅ 已加载配置文件: {args.config}")
        except Exception as e:
            print(f"❌ 配置文件错误: {e}")
            sys.exit(1)

    # 命令行参数覆盖配置文件参数
    args = merge_config_with_args(config, args)

    # 输出横幅
    if not args.quiet:
        print("🚀 yutto-plus - UP主投稿视频批量下载")
        print("=" * 50)
        if config:
            description = config.get('description', '')
            if description:
                print(f"📝 配置: {description}")
        print(f"👤 UP主UID: {uid}")
        print(f"📁 输出目录: {args.output}")

    # 运行异步下载
    asyncio.run(download_uploader_videos(uid, args))


async def download_uploader_videos(uid: int, args):
    """异步下载UP主的所有投稿视频"""
    from yutto_plus.core import UploaderVideoManager

    # 创建UP主视频管理器
    # 确保输出目录路径正确展开
    output_dir = Path(args.output).expanduser()
    manager = UploaderVideoManager(
        uid=uid,
        output_dir=output_dir,
        sessdata=args.sessdata or ""
    )

    try:
        # 获取视频列表
        update_check = args.update_uploader
        videos = await manager.get_uploader_videos(update_check=update_check)

        if not videos:
            print("📋 没有找到投稿视频")
            return

        # 显示视频列表统计
        total_videos = len(videos)
        downloaded_count = sum(1 for v in videos if v.get('downloaded', '').lower() == 'true')
        pending_count = total_videos - downloaded_count

        if not args.quiet:
            print(f"\n📊 视频统计:")
            print(f"   📺 总视频数: {total_videos}")
            print(f"   ✅ 已下载: {downloaded_count}")
            print(f"   ⏳ 待下载: {pending_count}")

        # 如果只是列表模式，显示视频列表并退出
        if args.list_only:
            print(f"\n📋 UP主投稿视频列表:")
            print("-" * 80)
            for i, video in enumerate(videos[:20], 1):  # 只显示前20个
                status = "✅" if video.get('downloaded', '').lower() == 'true' else "⏳"
                print(f"{i:3d}. {status} {video.get('title', '未知标题')[:60]}")
                print(f"     🔗 {video.get('url', '')}")
                print(f"     ⏱️ {video.get('duration', '未知时长')}")
                print()

            if total_videos > 20:
                print(f"... 还有 {total_videos - 20} 个视频（完整列表请查看CSV文件）")

            print(f"💾 完整列表已保存到: {manager.csv_path}")
            return

        # 过滤出需要下载的视频
        videos_to_download = [v for v in videos if v.get('downloaded', '').lower() != 'true']

        if not videos_to_download:
            print("🎉 所有视频都已下载完成！")
            return

        if not args.quiet:
            print(f"\n🚀 开始下载 {len(videos_to_download)} 个视频...")

        # 使用并行下载模式
        urls = [video['url'] for video in videos_to_download]

        # 创建临时args对象用于并行下载
        download_args = type('Args', (), {})()
        for attr in dir(args):
            if not attr.startswith('_'):
                setattr(download_args, attr, getattr(args, attr))

        download_args.urls = urls
        download_args.parsed_urls = [(url, None) for url in urls]  # 没有URL级别的分P参数

        # 设置输出目录为UP主专用目录
        user_dir = await manager.get_user_directory()
        download_args.output = str(user_dir)

        if not args.quiet:
            print(f"📁 视频将保存到: {user_dir}")

        # 执行并行下载（在新的事件循环中运行）
        import asyncio
        import threading

        def run_download():
            # 在新线程中运行同步下载
            parallel_download_mode(download_args)

        # 启动下载线程
        download_thread = threading.Thread(target=run_download, daemon=False)
        download_thread.start()

        # 等待下载完成
        download_thread.join()

        # 更新CSV文件中的下载状态
        await update_download_status(manager, videos_to_download)

    except Exception as e:
        print(f"❌ 下载过程中发生错误: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


async def update_download_status(manager: 'UploaderVideoManager', downloaded_videos: list):
    """更新CSV文件中的下载状态"""
    try:
        # 重新加载CSV文件
        all_videos = await manager._load_videos_from_csv()

        # 创建URL到视频的映射
        url_to_video = {v['url']: v for v in all_videos}

        # 更新下载状态
        for video in downloaded_videos:
            url = video['url']
            if url in url_to_video:
                url_to_video[url]['downloaded'] = 'True'
                # 这里可以添加更多状态更新逻辑

        # 保存更新后的CSV
        await manager._save_videos_to_csv(list(url_to_video.values()))

        print(f"💾 已更新下载状态到: {manager.csv_path}")

    except Exception as e:
        print(f"⚠️ 更新下载状态失败: {e}")


def handle_uploader_delete(args, config_manager):
    """处理UP主文件删除"""
    import os
    import re
    import shutil
    from pathlib import Path

    # 获取删除目录
    delete_path = args.delete_uploader
    if not delete_path:
        print("❌ 错误: 请指定要删除的目录路径")
        sys.exit(1)

    # 展开路径
    abs_path = Path(delete_path).expanduser().resolve()

    if not abs_path.exists() or not abs_path.is_dir():
        print(f"❌ 错误: 删除路径 '{abs_path}' 不存在或不是目录")
        sys.exit(1)

    print(f"🔍 扫描目录以查找UP主文件夹: {abs_path}")

    # 查找符合条件的文件夹
    folders_to_process = []
    for item in abs_path.iterdir():
        if item.is_dir():
            # 检查是否符合 UID-用户名 格式
            if re.match(r'^\d+-.*$', item.name):
                csv_file = item / "video_urls.csv"
                if csv_file.exists():
                    folders_to_process.append(item)

    if not folders_to_process:
        print("📋 没有找到符合条件的UP主文件夹（格式：UID-用户名，且包含video_urls.csv）")
        return

    # 显示将要处理的文件夹
    print(f"\n📁 找到 {len(folders_to_process)} 个UP主文件夹:")
    for folder in folders_to_process:
        print(f"  - {folder.name}")

    print(f"\n⚠️ 警告: 这将删除 {len(folders_to_process)} 个文件夹中的所有文件和子文件夹")
    print("📋 但会保留 video_urls.csv 文件")

    # 第一次确认
    response1 = input("\n是否继续？输入 'yes' 继续，其他任何内容取消: ")
    if response1.lower() != 'yes':
        print("❌ 删除操作已取消")
        return

    # 最终确认
    print("\n🚨 最终警告 🚨")
    print("此操作无法撤销！所有视频文件和子文件夹将被永久删除。")
    response2 = input("您确定要继续吗？输入 'DELETE'（大写）确认: ")
    if response2 != 'DELETE':
        print("❌ 删除操作已取消")
        return

    # 开始删除
    print("\n🗑️ 开始删除...")
    deleted_items_count = 0
    error_count = 0
    folders_with_content = 0
    folders_empty_except_csv = 0

    for folder in folders_to_process:
        print(f"\n📂 处理文件夹: {folder.name}")
        try:
            items = list(folder.iterdir())
            print(f"   发现 {len(items)} 个项目")

            # 统计除了CSV之外的项目
            non_csv_items = [item for item in items if item.name.lower() != "video_urls.csv"]
            if non_csv_items:
                folders_with_content += 1
                item_names = [item.name for item in non_csv_items[:5]]
                if len(non_csv_items) > 5:
                    item_names.append("...")
                print(f"   要删除的项目 ({len(non_csv_items)}): {', '.join(item_names)}")
            else:
                folders_empty_except_csv += 1
                print(f"   没有要删除的项目（只有video_urls.csv）")
                continue

            # 删除项目
            for item in items:
                if item.name.lower() == "video_urls.csv":
                    continue

                try:
                    if item.is_file() or item.is_symlink():
                        item.unlink()
                        print(f"   - 已删除文件: {item.name}")
                        deleted_items_count += 1
                    elif item.is_dir():
                        shutil.rmtree(item)
                        print(f"   - 已删除文件夹: {item.name}")
                        deleted_items_count += 1
                    else:
                        print(f"   - 跳过未知类型: {item.name}")

                except FileNotFoundError:
                    print(f"   - 跳过不存在的文件: {item.name}")
                except PermissionError as e:
                    print(f"   - 权限错误，无法删除 {item.name}: {e}")
                    error_count += 1
                except Exception as e:
                    print(f"   - 删除 {item.name} 时出错: {e}")
                    error_count += 1

        except Exception as e:
            print(f"   - 访问文件夹 {folder.name} 时出错: {e}")
            error_count += 1

    # 显示删除总结
    print("\n📊 删除总结")
    print("=" * 40)
    print(f"处理的文件夹总数: {len(folders_to_process)}")
    print(f"有内容需要删除的文件夹: {folders_with_content}")
    print(f"只有video_urls.csv的文件夹: {folders_empty_except_csv}")
    print(f"成功删除的项目数: {deleted_items_count}")
    if error_count > 0:
        print(f"遇到的错误数: {error_count}")
    print("=" * 40)
    print("🎉 删除操作完成！")


async def batch_update_uploaders(args, config_manager):
    """批量更新当前目录下所有符合格式的UP主文件夹"""
    import asyncio
    import os
    import re
    from pathlib import Path
    from datetime import datetime, timedelta
    from yutto_plus.core import UploaderVideoManager

    # 获取扫描目录：优先使用 -o 参数指定的目录，否则使用当前工作目录
    if hasattr(args, 'output') and args.output:
        scan_dir = Path(args.output).expanduser()
    else:
        scan_dir = Path.cwd()

    print(f"🔍 扫描目录: {scan_dir}")

    if not scan_dir.exists() or not scan_dir.is_dir():
        print(f"❌ 错误: 扫描目录 '{scan_dir}' 不存在或不是目录")
        return

    # 查找符合条件的文件夹
    folders_to_update = []
    for item in scan_dir.iterdir():
        if item.is_dir():
            # 检查是否符合 UID-用户名 格式
            match = re.match(r'^(\d+)-(.+)$', item.name)
            if match:
                csv_file = item / "video_urls.csv"
                if csv_file.exists():
                    uid = int(match.group(1))
                    username = match.group(2)
                    folders_to_update.append({
                        'path': item,
                        'uid': uid,
                        'username': username,
                        'csv_path': csv_file
                    })

    if not folders_to_update:
        print("📋 没有找到符合条件的UP主文件夹（格式：UID-用户名，且包含video_urls.csv）")
        return

    print(f"\n📁 找到 {len(folders_to_update)} 个UP主文件夹:")
    for folder_info in folders_to_update:
        print(f"  - {folder_info['path'].name} (UID: {folder_info['uid']})")

    # 加载配置文件（如果指定）
    config = {}
    if args.config:
        try:
            config = config_manager.load_config(args.config)
            if not config_manager.validate_config(config):
                print("❌ 配置文件验证失败")
                return
            print(f"✅ 已加载配置文件: {args.config}")
        except Exception as e:
            print(f"❌ 配置文件错误: {e}")
            return

    # 命令行参数覆盖配置文件参数
    merged_args = merge_config_with_args(config, args)

    print(f"\n🚀 开始批量更新...")
    updated_count = 0
    failed_count = 0

    for i, folder_info in enumerate(folders_to_update, 1):
        print(f"\n--- 处理文件夹 {i}/{len(folders_to_update)}: {folder_info['path'].name} ---")

        try:
            # 检查CSV文件的最后保存时间（除非使用--force）
            if not merged_args.force:
                last_save_time = await get_csv_save_time(folder_info['csv_path'])
                if last_save_time:
                    hours_since_save = (datetime.now() - last_save_time).total_seconds() / 3600
                    if hours_since_save < 12:
                        print(f"⏰ CSV文件在 {hours_since_save:.1f} 小时前保存，跳过更新（可使用 --force 强制更新）")
                        continue

            # 更新单个UP主，传递现有用户名避免API调用
            success = await update_single_uploader(
                folder_info['uid'],
                folder_info['path'].parent,  # 使用父目录作为输出目录
                merged_args,
                existing_username=folder_info['username']  # 传递现有用户名
            )

            if success:
                updated_count += 1
                print(f"✅ {folder_info['path'].name} 更新完成")
            else:
                failed_count += 1
                print(f"❌ {folder_info['path'].name} 更新失败")

            # 在处理下一个文件夹前稍作延迟，避免API频率限制
            if i < len(folders_to_update):
                print("⏳ 等待 5 秒...")
                await asyncio.sleep(5)

        except Exception as e:
            failed_count += 1
            print(f"❌ 处理 {folder_info['path'].name} 时出错: {e}")

    # 显示总结
    print(f"\n📊 批量更新总结:")
    print(f"   📁 扫描到的文件夹: {len(folders_to_update)}")
    print(f"   ✅ 成功更新: {updated_count}")
    print(f"   ❌ 更新失败: {failed_count}")
    print(f"   ⏭️ 跳过更新: {len(folders_to_update) - updated_count - failed_count}")


async def get_csv_save_time(csv_path):
    """获取CSV文件的保存时间"""
    from datetime import datetime

    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('# SaveTime:'):
                    try:
                        time_str = line.strip().split('# SaveTime: ')[1]
                        return datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
                    except (IndexError, ValueError):
                        break
    except Exception:
        pass
    return None


async def update_single_uploader(uid, output_dir, args, existing_username=None):
    """更新单个UP主的视频列表并下载新视频"""
    try:
        from yutto_plus.core import UploaderVideoManager

        # 创建UP主视频管理器，如果有现有用户名则直接使用
        manager = UploaderVideoManager(
            uid=uid,
            output_dir=output_dir,
            sessdata=args.sessdata or "",
            username=existing_username  # 传递现有用户名，避免重复API调用
        )

        # 强制更新检查
        videos = await manager.get_uploader_videos(update_check=True)

        if not videos:
            print(f"📋 UID {uid}: 没有找到投稿视频")
            return True

        # 显示统计信息
        total_videos = len(videos)
        downloaded_count = sum(1 for v in videos if v.get('downloaded', '').lower() == 'true')
        new_count = sum(1 for v in videos if v.get('downloaded', '').lower() != 'true')

        print(f"📊 UID {uid}: 总视频 {total_videos}, 已下载 {downloaded_count}, 新增/待下载 {new_count}")

        # 如果有新视频需要下载，立即开始下载
        if new_count > 0:
            print(f"🚀 开始下载 {new_count} 个新视频...")

            # 获取需要下载的视频URL列表
            new_videos = [v for v in videos if v.get('downloaded', '').lower() != 'true']
            video_urls = [v['url'] for v in new_videos]

            # 获取用户目录
            user_directory = await manager.get_user_directory()

            # 开始下载
            success = await download_uploader_videos(video_urls, str(user_directory), args)

            if success:
                print(f"✅ UID {uid}: 新视频下载完成")
            else:
                print(f"⚠️ UID {uid}: 部分视频下载可能失败")
        else:
            print(f"✅ UID {uid}: 没有新视频需要下载")

        return True

    except Exception as e:
        print(f"❌ 更新 UID {uid} 失败: {e}")
        return False


async def download_uploader_videos(video_urls, output_dir, args):
    """下载UP主的视频列表"""
    try:
        import asyncio
        from yutto_plus.core import YuttoPlus

        # 创建下载器实例
        downloader = YuttoPlus(
            max_concurrent=args.concurrent or 2,
            default_output_dir=output_dir,
            default_quality=args.quality or 80,
            default_audio_quality=args.audio_quality or 30280,
            default_video_codec=args.video_codec or 'avc',
            default_output_format=args.format or 'mp4',
            overwrite=args.overwrite or False,
            enable_resume=args.enable_resume if hasattr(args, 'enable_resume') else True,
            sessdata=args.sessdata or ""
        )

        # 准备下载任务
        tasks = []
        for url in video_urls:
            task_config = {
                'quality': args.quality or 80,
                'audio_quality': args.audio_quality or 30280,
                'video_codec': args.video_codec or 'avc',
                'output_format': args.format or 'mp4',
                'output_dir': output_dir,
                'overwrite': args.overwrite or False,
                'enable_resume': getattr(args, 'enable_resume', True),
                'episodes_selection': '',  # UP主下载通常不需要分P选择
                'create_folder_for_multi_p': getattr(args, 'create_folder_for_multi_p', True),
                'no_danmaku': getattr(args, 'no_danmaku', False),
                'no_cover': getattr(args, 'no_cover', False),
                'danmaku_format': getattr(args, 'danmaku_format', 'ass'),
                'audio_format': getattr(args, 'audio_format', 'mp3'),
                'audio_bitrate': getattr(args, 'audio_bitrate', '192k')
            }
            tasks.append((url, task_config))

        # 添加任务到下载器
        task_ids = downloader.add_download_tasks(tasks)

        # 启动下载
        downloader.start_parallel_download(display_mode='table')

        # 等待所有任务完成
        while True:
            await asyncio.sleep(1)
            queue_status = downloader.task_manager.get_queue_status()

            if queue_status['running'] == 0 and queue_status['pending'] == 0:
                break

        # 获取最终状态
        final_status = downloader.task_manager.get_queue_status()
        success_count = final_status['completed']
        total_count = len(tasks)

        print(f"📊 下载完成: {success_count}/{total_count} 个视频成功")

        # YuttoPlus 不需要手动关闭，移除这行
        # await downloader.close()

        return success_count > 0

    except Exception as e:
        print(f"❌ 下载视频失败: {e}")
        return False


if __name__ == "__main__":
    main()