#!/usr/bin/env python3
"""
yutto-plus CLI - B站视频下载器命令行工具
基于纯 HTTP API 实现的现代化下载器
"""

import argparse
import sys
import time
from pathlib import Path
from yutto_plus import YuttoPlus, TaskStatus


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='yutto-plus - 现代化 B站视频下载器',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  %(prog)s "https://www.bilibili.com/video/BV1LWjXzvEX1/"
  %(prog)s -q 127 -o "./Downloads" "https://www.bilibili.com/video/BV1LWjXzvEX1/"
  %(prog)s --audio-only -af mp3 -ab 192k "https://www.bilibili.com/video/BV1LWjXzvEX1/"
  %(prog)s --no-danmaku --no-cover "https://www.bilibili.com/video/BV1LWjXzvEX1/"
  %(prog)s --no-resume "https://www.bilibili.com/video/BV1LWjXzvEX1/"

支持的视频质量:
  127: 8K 超高清    120: 4K 超清      116: 1080P60    112: 1080P+
  80:  1080P 高清   64:  720P 高清    32:  480P 清晰  16:  360P 流畅

支持的音频质量:
  30251: Hi-Res 无损  30280: 320kbps  30232: 128kbps  30216: 64kbps

断点续传功能:
  默认启用断点续传，下载中断后重新运行可从断点继续
  使用 --no-resume 禁用断点续传，强制重新下载
  使用 -w/--overwrite 覆盖现有文件（同时禁用断点续传）
        """
    )
    
    # 位置参数
    parser.add_argument(
        'url',
        help='B站视频链接'
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
        
        # 输出横幅
        if not args.quiet:
            print("🚀 yutto-plus - 现代化 B站视频下载器")
            print("=" * 50)
        
        # 验证URL
        if not args.url or not ('bilibili.com' in args.url or 'b23.tv' in args.url):
            print("❌ 错误: 请提供有效的B站视频链接")
            sys.exit(1)
        
        # 创建下载器
        downloader = YuttoPlus(
            sessdata=args.sessdata,
            default_output_dir=args.output,
            default_quality=args.quality,
            default_audio_quality=args.audio_quality,
            default_video_codec=args.video_codec,
            default_output_format=args.format,
            overwrite=args.overwrite,
            enable_resume=not args.no_resume  # 如果指定--no-resume则禁用断点续传
        )
        
        # 处理资源选择逻辑
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
        
        # 验证参数逻辑
        if not any([require_video, require_audio, require_danmaku, require_cover]):
            print("❌ 错误: 没有选择任何下载内容")
            sys.exit(1)
        
        # 创建下载任务
        if not args.quiet:
            print(f"📋 创建下载任务...")
            print(f"🔗 URL: {args.url}")
            print(f"🎯 质量: {args.quality} (视频) / {args.audio_quality} (音频)")
            print(f"📁 输出: {args.output}")
            
            # 显示将要下载的内容
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
            print(f"📦 内容: {', '.join(download_items)}")
            print()
        
        task = downloader.create_download_task(
            args.url,
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
        
        # 进度状态
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
        
        # 等待完成
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


if __name__ == "__main__":
    main() 