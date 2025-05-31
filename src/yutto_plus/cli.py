#!/usr/bin/env python3
"""
yutto-plus CLI - B站视频下载器命令行工具
基于纯 HTTP API 实现的现代化下载器
"""

import argparse
import sys
import time
from pathlib import Path

from . import YuttoPlus, TaskStatus, ConfigManager


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
        
        # 验证所有URL
        for url in args.urls:
            if not ('bilibili.com' in url or 'b23.tv' in url):
                print(f"❌ 错误: 无效的B站视频链接: {url}")
                sys.exit(1)
        
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
        audio_bitrate=args.audio_bitrate
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
    for url in args.urls:
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
            "audio_bitrate": args.audio_bitrate
        }
        tasks.append((url, task_config))
    
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
                print("✅ 下载完成!")
                print(f"📁 文件路径: {result_info['output_filepath']}")
                print(f"📺 视频流: {result_info['selected_video_stream_info']}")
                print(f"🔊 音频流: {result_info['selected_audio_stream_info']}")
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
        'sessdata': 'sessdata'
    }
    
    # 只有当命令行参数是默认值时，才使用配置文件的值
    parser = parse_args.__wrapped__ if hasattr(parse_args, '__wrapped__') else None
    
    for config_key, args_attr in config_to_args_mapping.items():
        if config_key in config:
            config_value = config[config_key]
            current_value = getattr(args, args_attr, None)
            
            # 特殊处理enable_resume（配置文件中是enable_resume，命令行是no_resume）
            if config_key == 'enable_resume':
                # 如果命令行没有指定--no-resume，使用配置文件的enable_resume设置
                if not args.no_resume:  # 默认情况下no_resume是False
                    args.no_resume = not config_value
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


if __name__ == "__main__":
    main() 