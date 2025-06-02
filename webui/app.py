#!/usr/bin/env python3
"""
yutto-plus Web UI v2.0
集成并行下载和配置文件功能的现代化 Web 界面
"""

from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit
import json
import yaml
from pathlib import Path
import socket
import webbrowser
import threading
import time
import os
import sys
import requests
import random
import re

# 添加src目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from yutto_plus import YuttoPlus, TaskStatus, ConfigManager

app = Flask(__name__)
app.config['SECRET_KEY'] = 'yutto_plus_secret'
socketio = SocketIO(app, cors_allowed_origins="*")

# 全局实例
downloader = None
config_manager = ConfigManager()
active_downloads = {}  # {session_id: {downloader, tasks}}

# 全局下载器和任务管理
global_downloader = None
global_config = None

# 任务持久化存储 - 改为全局存储
persistent_tasks = {}  # {task_id: {source, task_info, status, session_id}}

def save_task_info(session_id: str, task_id: str, source: str, task_info: dict):
    """保存任务信息到全局持久化存储"""
    persistent_tasks[task_id] = {
        'source': source,  # 'single', 'parallel', 'precise'
        'task_info': task_info,
        'created_at': time.time(),
        'status': 'active',
        'session_id': session_id
    }
    print(f"💾 保存任务信息: {task_id} (来源: {source})")

def get_active_tasks_by_source(source: str):
    """获取指定来源的所有活跃任务"""
    active_tasks = {}
    for task_id, task_data in persistent_tasks.items():
        if task_data['source'] == source and task_data['status'] == 'active':
            active_tasks[task_id] = task_data

    return active_tasks

def mark_task_completed(task_id: str):
    """标记任务为已完成"""
    if task_id in persistent_tasks:
        persistent_tasks[task_id]['status'] = 'completed'
        print(f"✅ 标记任务完成: {task_id}")

def cleanup_completed_tasks():
    """清理已完成的任务"""
    completed_tasks = [task_id for task_id, task_data in persistent_tasks.items()
                      if task_data['status'] == 'completed']
    for task_id in completed_tasks:
        del persistent_tasks[task_id]
    if completed_tasks:
        print(f"🗑️ 清理已完成任务: {len(completed_tasks)} 个")

def parse_url_with_parts(url_string: str):
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

def format_task_title_with_multi_p(progress):
    """格式化任务标题，添加多P信息"""
    if not progress.video_info:
        return '未知标题'

    title = progress.video_info.get('title', '未知标题')

    # 添加多P信息
    if progress.video_info.get('is_multi_p'):
        total_pages = progress.video_info.get('total_pages', 0)
        current_part = progress.video_info.get('current_part')

        if current_part:
            # 显示当前分P信息
            part_index = current_part['index']
            title = f"[{part_index}/{total_pages}P] {title}"
        else:
            # 显示总分P数
            title = f"[{total_pages}P] {title}"

    return title

def ensure_webui_config():
    """确保WebUI配置文件存在"""
    config_dir = Path(__file__).parent.parent / 'configs'
    webui_config_path = config_dir / 'yutto-webui.yaml'
    
    if not webui_config_path.exists():
        # 创建默认WebUI配置文件
        default_config = {
            'description': 'WebUI 默认配置',
            'quality': 80,
            'audio_quality': 30280,
            'output_dir': './Downloads',
            'format': 'mp4',
            'concurrent': 2,
            'parallel_display': 'table',
            'audio_only': False,
            'no_video': False,
            'no_danmaku': False,
            'no_cover': False,
            'danmaku_format': 'ass',
            'audio_format': 'mp3',
            'audio_bitrate': '192k',
            'video_codec': 'avc',
            'overwrite': False,
            'enable_resume': True,
            'quiet': False,
            'verbose': False
        }
        
        with open(webui_config_path, 'w', encoding='utf-8') as f:
            yaml.dump(default_config, f, default_flow_style=False, allow_unicode=True, 
                     indent=2, sort_keys=False)
        
        print(f"✅ 已创建默认WebUI配置文件: {webui_config_path}")
    
    return webui_config_path

def validate_sessdata(sessdata):
    """验证SESSDATA是否有效"""
    if not sessdata:
        return False, "SESSDATA为空"
    
    try:
        # 使用SESSDATA请求B站API验证
        headers = {
            'Cookie': f'SESSDATA={sessdata}',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # 请求用户信息API
        response = requests.get(
            'https://api.bilibili.com/x/web-interface/nav',
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get('code') == 0:
                user_info = data.get('data', {})
                username = user_info.get('uname', '未知用户')
                return True, f"验证成功 - 用户: {username}"
            else:
                return False, f"验证失败: {data.get('message', '未知错误')}"
        else:
            return False, f"请求失败: HTTP {response.status_code}"
            
    except requests.exceptions.Timeout:
        return False, "请求超时"
    except requests.exceptions.RequestException as e:
        return False, f"网络错误: {str(e)}"
    except Exception as e:
        return False, f"验证错误: {str(e)}"

def init_downloader(session_id, config=None):
    """初始化下载器实例，支持全局复用"""
    global global_downloader, global_config

    if config is None:
        # 默认加载WebUI配置文件
        webui_config_path = ensure_webui_config()
        with open(webui_config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

    # 如果全局下载器已存在且配置相同，直接复用
    if global_downloader is not None and global_config == config:
        print(f'🔄 复用现有下载器实例 (会话: {session_id})')
        active_downloads[session_id] = {
            'downloader': global_downloader,
            'tasks': {},
            'config': config
        }

        # 确保WebUI回调已设置
        if not hasattr(global_downloader, '_webui_callback_set'):
            print(f"⚠️ 复用的下载器缺少WebUI回调，需要重新设置")

        return global_downloader

    # 创建新的下载器实例
    downloader_instance = YuttoPlus(
        max_concurrent=config.get('concurrent', 2),
        default_output_dir=config.get('output_dir', './Downloads'),
        default_quality=config.get('quality', 80),
        default_audio_quality=config.get('audio_quality', 30280),
        default_video_codec=config.get('video_codec', 'avc'),
        default_output_format=config.get('format', 'mp4'),
        overwrite=config.get('overwrite', False),
        enable_resume=config.get('enable_resume', True),
        sessdata=config.get('sessdata')
    )

    # 保存为全局下载器
    global_downloader = downloader_instance
    global_config = config

    active_downloads[session_id] = {
        'downloader': downloader_instance,
        'tasks': {},
        'config': config
    }

    print(f'🚀 YuttoPlus 已初始化 (会话: {session_id}, 并发数: {config.get("concurrent", 2)})')
    print(f'📁 输出目录: {config.get("output_dir", "./Downloads")}')

    return downloader_instance

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/config/<path:filename>')
def serve_config(filename):
    """提供配置文件下载"""
    config_dir = Path(__file__).parent.parent / 'configs'
    return send_from_directory(config_dir, filename)

@app.route('/api/configs')
def get_configs():
    """获取可用的配置文件列表"""
    config_files = []
    
    # 查找YAML配置文件
    config_dir = Path(__file__).parent.parent / 'configs'
    
    try:
        # 使用列表推导式和更快的文件处理
        for config_file in sorted(config_dir.glob('yutto-*.yaml')):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    # 只读取必要的字段，减少解析时间
                    config = yaml.safe_load(f)
                
                # 快速检查SESSDATA存在性
                sessdata = config.get('sessdata', '').strip()
                sessdata_status = 'pending' if sessdata else 'none'
                sessdata_message = '存在，可用性待验证' if sessdata else '未配置'
                
                config_files.append({
                    'name': config_file.stem,
                    'filename': config_file.name,
                    'description': config.get('description', '无描述'),
                    'concurrent': config.get('concurrent', 1),
                    'quality': config.get('quality', 80),
                    'audio_only': config.get('audio_only', False),
                    'sessdata_status': sessdata_status,
                    'sessdata_message': sessdata_message
                })
            except Exception as e:
                print(f"⚠️ 跳过无效配置文件 {config_file.name}: {e}")
                continue
                
    except Exception as e:
        print(f"⚠️ 读取配置目录失败: {e}")
    
    return jsonify(config_files)

@app.route('/api/validate-sessdata/<filename>')
def validate_config_sessdata(filename):
    """验证指定配置文件的SESSDATA"""
    config_dir = Path(__file__).parent.parent / 'configs'
    config_path = config_dir / filename
    
    if not config_path.exists():
        return jsonify({'error': '配置文件不存在'}), 404
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        sessdata = config.get('sessdata')
        if not sessdata or not sessdata.strip():
            return jsonify({
                'valid': False,
                'message': '未配置SESSDATA'
            })
        
        # 验证SESSDATA
        is_valid, message = validate_sessdata(sessdata.strip())
        return jsonify({
            'valid': is_valid,
            'message': message
        })
        
    except Exception as e:
        return jsonify({'error': f'验证失败: {str(e)}'}), 500

@app.route('/api/config/<filename>', methods=['GET', 'POST'])
def handle_config_file(filename):
    """处理配置文件的读取和保存"""
    config_dir = Path(__file__).parent.parent / 'configs'
    config_path = config_dir / filename
    
    if request.method == 'GET':
        # 读取配置文件
        if not config_path.exists():
            return jsonify({'error': '配置文件不存在'}), 404
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        return jsonify(config)
    
    elif request.method == 'POST':
        # 保存配置文件
        config_data = request.json
        
        try:
            # 验证配置（跳过SESSDATA验证）
            if not config_manager.validate_config(config_data):
                return jsonify({'error': '配置验证失败'}), 400
            
            # 先保存配置文件，保留注释格式
            save_config_with_comments(config_path, config_data)
            
            # 立即返回成功响应
            return jsonify({
                'success': True,
                'message': '配置已保存',
                'requires_sessdata_validation': bool(config_data.get('sessdata'))
            })
            
        except Exception as e:
            return jsonify({'error': f'保存失败: {str(e)}'}), 500

def save_config_with_comments(config_path, config_data):
    """保存配置文件，保留注释和格式"""
    
    # 配置模板，包含注释
    config_template = f"""# YuttoPlus 配置文件
# 适用场景: {config_data.get('description', '自定义配置')}

description: "{config_data.get('description', '自定义配置')}"

# === 基础设置 ===
quality: {config_data.get('quality', 80)}           # 视频质量: {get_quality_description(config_data.get('quality', 80))}
audio_quality: {config_data.get('audio_quality', 30280)}  # 音频质量: {get_audio_quality_description(config_data.get('audio_quality', 30280))}
output_dir: "{config_data.get('output_dir', './Downloads')}"  # 输出目录
format: "{config_data.get('format', 'mp4')}"         # 输出格式

# === 并行设置 ===
concurrent: {config_data.get('concurrent', 2)}         # 并发下载数量
parallel_display: "{config_data.get('parallel_display', 'table')}"  # 显示模式: table(表格) / simple(简单) / silent(静默)

# === 下载内容 ===
audio_only: {str(config_data.get('audio_only', False)).lower()}     # 是否仅下载音频
no_video: {str(config_data.get('no_video', False)).lower()}       # 是否跳过视频
no_danmaku: {str(config_data.get('no_danmaku', False)).lower()}     # 是否跳过弹幕
no_cover: {str(config_data.get('no_cover', False)).lower()}       # 是否跳过封面

# === 格式设置 ===
danmaku_format: "{config_data.get('danmaku_format', 'ass')}" # 弹幕格式: xml / ass / protobuf
audio_format: "{config_data.get('audio_format', 'mp3')}"   # 音频格式: mp3 / wav / flac / m4a / aac
audio_bitrate: "{config_data.get('audio_bitrate', '192k')}" # 音频比特率
video_codec: "{config_data.get('video_codec', 'avc')}"    # 视频编码: avc / hevc / av1

# === 多P视频设置 ===
create_folder_for_multi_p: {str(config_data.get('create_folder_for_multi_p', True)).lower()}  # 为多P视频创建文件夹"""

    # 添加分P选择配置
    episodes_selection_value = config_data.get('episodes_selection', '')
    if episodes_selection_value:
        config_template += f'\nepisodes_selection: "{episodes_selection_value}"  # 分P选择: {episodes_selection_value}'
    else:
        config_template += '\n# episodes_selection: "1,3,5-8"  # 分P选择 (可选): 支持范围和排除语法'

    config_template += f"""

# === 其他设置 ===
overwrite: {str(config_data.get('overwrite', False)).lower()}      # 是否覆盖现有文件
enable_resume: {str(config_data.get('enable_resume', True)).lower()}   # 是否启用断点续传
quiet: {str(config_data.get('quiet', False)).lower()}          # 是否使用安静模式
verbose: {str(config_data.get('verbose', False)).lower()}        # 是否显示详细信息

# === 登录设置（可选）===
# 请填入你的B站SESSDATA，用于下载高清视频和大会员内容
# 获取方法: 登录B站 -> F12开发者工具 -> Application -> Cookies -> SESSDATA
"""
    
    # 添加SESSDATA配置
    if config_data.get('sessdata'):
        config_template += f'sessdata: "{config_data.get("sessdata")}"\n'
    else:
        config_template += '# sessdata: "你的SESSDATA值"\n'
    
    config_template += """
# === 配置说明 ===
# 画质对照表:
# 127: 8K 超高清 (需要大会员，文件很大)
# 120: 4K 超清 (需要大会员，文件较大)
# 116: 1080P60 (60帧，需要大会员)
# 80:  1080P 高清 (推荐，平衡质量和大小)
# 64:  720P 高清 (较快下载，中等质量)
# 32:  480P 清晰 (快速下载，一般质量)

# 音频质量对照表:
# 30251: Hi-Res 无损 (FLAC格式，文件很大)
# 30280: 320kbps (高质量，推荐)
# 30232: 128kbps (标准质量)
# 30216: 64kbps (节省空间)
"""
    
    # 写入文件
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write(config_template.strip())

def get_quality_description(quality):
    """获取画质描述"""
    quality_map = {
        127: "8K 超高清 (需要大会员)",
        120: "4K 超清 (需要大会员)",
        116: "1080P60 (需要大会员)",
        80: "1080P 高清 (推荐)",
        64: "720P 高清",
        32: "480P 清晰",
        16: "360P 流畅"
    }
    return quality_map.get(quality, f"自定义({quality})")

def get_audio_quality_description(audio_quality):
    """获取音频质量描述"""
    audio_map = {
        30251: "Hi-Res 无损 (FLAC)",
        30280: "320kbps (高质量)",
        30232: "128kbps (标准)",
        30216: "64kbps (节省空间)"
    }
    return audio_map.get(audio_quality, f"自定义({audio_quality})")

@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    session_id = request.sid
    print(f'🌐 [连接] 客户端已连接: {session_id}')
    
    # 为新会话初始化下载器（自动加载WebUI配置）
    downloader_instance = init_downloader(session_id)
    
    # 获取当前配置
    config = active_downloads[session_id]['config']
    
    # 不验证SESSDATA，直接检查是否存在
    sessdata = config.get('sessdata')
    sessdata_configured = bool(sessdata and sessdata.strip())
    sessdata_status = 'pending' if sessdata_configured else 'none'
    sessdata_message = '存在，可用性待验证' if sessdata_configured else '未配置'
    
    # 发送初始配置状态（不包含验证结果）
    emit('config_loaded', {
        'config': config,
        'message': f'已加载WebUI默认配置: {config.get("description", "WebUI配置")}',
        'sessdata_configured': sessdata_configured,
        'sessdata_valid': False,  # 初始不验证
        'sessdata_message': sessdata_message,
        'sessdata_preview': sessdata[:10] + '...' if sessdata else None
    })

@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开连接"""
    session_id = request.sid
    print(f'🔌 [断开] 客户端已断开: {session_id}')

    # 只清理会话数据，不关闭下载器
    if session_id in active_downloads:
        print(f'📋 清理会话数据: {session_id}')
        del active_downloads[session_id]

    # 不清理任务数据，保持任务持久化

@socketio.on('load_config')
def handle_load_config(data):
    """加载配置文件"""
    try:
        session_id = request.sid
        config_filename = data.get('config_file')
        
        if not config_filename:
            emit('error', {'message': '请选择配置文件'})
            return
        
        # 加载配置
        config_dir = Path(__file__).parent.parent / 'configs'
        config_path = config_dir / config_filename
        if not config_path.exists():
            emit('error', {'message': f'配置文件不存在: {config_filename}'})
            return
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        # 验证配置
        if not config_manager.validate_config(config):
            emit('error', {'message': '配置文件验证失败'})
            return
        
        # 关闭旧的下载器
        if session_id in active_downloads:
            try:
                active_downloads[session_id]['downloader'].shutdown()
            except:
                pass
        
        # 使用新配置初始化下载器
        downloader_instance = init_downloader(session_id, config)
        
        emit('config_loaded', {
            'config': config,
            'message': f'配置文件已加载: {config.get("description", config_filename)}',
            'sessdata_configured': bool(config.get('sessdata') and config.get('sessdata').strip()),
            'sessdata_valid': validate_sessdata(config.get('sessdata').strip())[0] if (config.get('sessdata') and config.get('sessdata').strip()) else False,
            'sessdata_message': validate_sessdata(config.get('sessdata').strip())[1] if (config.get('sessdata') and config.get('sessdata').strip()) else '未配置',
            'sessdata_preview': config.get('sessdata', '').strip()[:10] + '...' if (config.get('sessdata') and config.get('sessdata').strip()) else None
        })
        
        print(f'⚙️ [配置] 会话 {session_id} 加载配置: {config.get("description", config_filename)}')
        
    except Exception as e:
        print(f'❌ [错误] 加载配置文件时出错: {e}')
        emit('error', {'message': f'加载配置文件时出错: {str(e)}'})

@socketio.on('start_parallel_download')
def handle_parallel_download_request(data):
    """处理并行下载请求"""
    try:
        session_id = request.sid
        urls = data.get('urls', [])
        custom_config = data.get('config', {})
        source = data.get('source', 'parallel')  # 获取来源标识
        
        if not urls:
            emit('error', {'message': '请输入至少一个有效的 B站视频链接'})
            return
        
        # 获取会话的下载器
        if session_id not in active_downloads:
            init_downloader(session_id)
        
        downloader_instance = active_downloads[session_id]['downloader']
        base_config = active_downloads[session_id]['config']
        
        # 合并配置
        merged_config = {**base_config, **custom_config}
        
        print(f'📥 [并行下载] 会话 {session_id}, URLs: {len(urls)}, 并发: {merged_config.get("concurrent", 2)}')
        
        # 准备任务配置
        tasks = []
        for url_string in urls:
            if url_string.strip():
                try:
                    # 解析URL和分P参数
                    clean_url, url_parts = parse_url_with_parts(url_string)

                    # 如果URL包含分P参数，显示解析结果
                    if url_parts:
                        print(f"🔍 解析URL: {clean_url}")
                        print(f"   📺 分P选择: {url_parts}")

                    task_config = {
                        "quality": merged_config.get('quality', 80),
                        "audio_quality": merged_config.get('audio_quality', 30280),
                        "output_dir": merged_config.get('output_dir', './Downloads'),
                        "output_format": merged_config.get('format', 'mp4'),
                        "require_video": not merged_config.get('no_video', False),
                        "require_audio": True,
                        "require_danmaku": not merged_config.get('no_danmaku', False),
                        "require_cover": not merged_config.get('no_cover', False),
                        "danmaku_format": merged_config.get('danmaku_format', 'ass'),
                        "audio_format": merged_config.get('audio_format', 'mp3'),
                        "audio_only": merged_config.get('audio_only', False),
                        "audio_bitrate": merged_config.get('audio_bitrate', '192k'),
                        "episodes_selection": url_parts  # 添加分P选择参数
                    }
                    tasks.append((clean_url, task_config))

                except ValueError as e:
                    print(f"❌ URL解析错误: {e}")
                    emit('error', {'message': f'URL解析错误: {str(e)}'})
                    return
        
        if not tasks:
            emit('error', {'message': '没有有效的下载链接'})
            return
        
        # 设置进度监控回调
        def setup_progress_callbacks():
            # 检查是否已经设置过回调，避免重复设置
            if hasattr(downloader_instance, '_webui_callback_set'):
                print(f"⚠️ 进度回调已设置，跳过重复设置")
                return

            # 重写下载器的进度回调方法
            original_update_progress = downloader_instance._update_progress_display

            def enhanced_update_progress():
                try:
                    # 调用原始方法
                    original_update_progress()

                    # 发送实时进度到前端
                    overall_progress = downloader_instance.get_overall_progress()
                    tasks_progress = downloader_instance.tasks_progress

                    print(f"📊 发送进度更新: 总任务={overall_progress.total_tasks}, 运行中={overall_progress.running_tasks}, 进度={overall_progress.overall_progress:.1f}%")

                    # 发送整体进度到所有连接的客户端
                    socketio.emit('parallel_progress', {
                        'source': source,  # 传递来源标识
                        'overall': {
                            'total_tasks': overall_progress.total_tasks,
                            'completed_tasks': overall_progress.completed_tasks,
                            'running_tasks': overall_progress.running_tasks,
                            'failed_tasks': overall_progress.failed_tasks,
                            'overall_progress': overall_progress.overall_progress,
                            'total_speed': overall_progress.total_speed / (1024*1024),  # MB/s
                            'eta_seconds': overall_progress.eta_seconds
                        },
                        'tasks': {
                            task_id: {
                                'status': progress.status.value,
                                'title': format_task_title_with_multi_p(progress),
                                'progress_percentage': progress.progress_percentage,
                                'download_speed': progress.download_speed / (1024*1024) if progress.download_speed else 0,
                                'is_multi_p': progress.video_info.get('is_multi_p', False) if progress.video_info else False,
                                'current_part': progress.video_info.get('current_part') if progress.video_info else None,
                                'total_pages': progress.video_info.get('total_pages', 1) if progress.video_info else 1
                            }
                            for task_id, progress in tasks_progress.items()
                        }
                    })  # 广播到所有客户端

                except Exception as e:
                    print(f"❌ 进度回调出错: {e}")

            # 替换方法
            downloader_instance._update_progress_display = enhanced_update_progress
            downloader_instance._webui_callback_set = True  # 标记已设置
            print(f"✅ 已设置WebUI进度回调")
        
        # 添加任务到下载器
        task_ids = downloader_instance.add_download_tasks(tasks)

        # 保存任务信息到持久化存储
        try:
            for i, task_id in enumerate(task_ids):
                # tasks[i] 是一个元组 (url, task_config)
                url, task_config = tasks[i]
                task_info = {
                    'url': url,
                    'title': '未知标题',  # 标题会在下载过程中获取
                    'quality': merged_config.get('quality', 80),
                    'parts': task_config.get('episodes_selection', ''),
                    'created_at': time.time()
                }
                save_task_info(session_id, task_id, source, task_info)
                print(f"💾 已保存任务信息: {task_id} -> {url}")
        except Exception as save_error:
            print(f"⚠️ 保存任务信息时出错: {save_error}")
            print(f"🔍 调试信息: tasks类型={type(tasks)}, 长度={len(tasks)}")
            if tasks:
                print(f"🔍 第一个任务: {tasks[0]}")
            # 继续执行，不中断下载

        # 设置回调
        setup_progress_callbacks()

        # 启动并行下载
        downloader_instance.start_parallel_download(display_mode='silent')

        # 保存任务到会话
        active_downloads[session_id]['tasks'].update({tid: 'running' for tid in task_ids})
        active_downloads[session_id]['source'] = source  # 保存下载来源
        
        # 发送开始确认
        emit('parallel_download_started', {
            'task_ids': task_ids,
            'total_tasks': len(tasks),
            'concurrent': merged_config.get('concurrent', 2),
            'sessdata_configured': bool(merged_config.get('sessdata')),
            'login_status': '已登录会员账户' if merged_config.get('sessdata') else '未登录，只能下载普通清晰度'
        })
        
        # 在后台监控完成状态
        def monitor_completion():
            while True:
                time.sleep(2)
                queue_status = downloader_instance.task_manager.get_queue_status()
                
                if queue_status['running'] == 0 and queue_status['pending'] == 0:
                    # 所有任务完成
                    final_status = downloader_instance.task_manager.get_queue_status()
                    tasks_info = downloader_instance.get_tasks_summary_info()
                    
                    socketio.emit('parallel_download_complete', {
                        'final_status': final_status,
                        'tasks_info': tasks_info,
                        'session_id': session_id
                    }, room=session_id)
                    
                    print(f'🎉 [完成] 会话 {session_id} 并行下载完成')
                    break
        
        # 启动监控线程
        threading.Thread(target=monitor_completion, daemon=True).start()
        
    except Exception as e:
        print(f'❌ [错误] 处理并行下载请求时出错: {e}')
        emit('error', {'message': f'处理并行下载请求时出错: {str(e)}'})

@socketio.on('single_download_request')
def handle_single_download_request(data):
    """处理单个下载请求（保持兼容性）"""
    try:
        url = data.get('url', '').strip()
        quality = int(data.get('quality', 80))
        
        if not url:
            emit('error', {'message': '请输入有效的 B站视频链接'})
            return
        
        # 转换为并行下载请求
        parallel_data = {
            'urls': [url],
            'config': {'quality': quality, 'concurrent': 1},
            'source': 'single'  # 标识为单个下载
        }

        handle_parallel_download_request(parallel_data)
        
    except Exception as e:
        print(f'❌ [错误] 处理单个下载请求时出错: {e}')
        emit('error', {'message': f'处理单个下载请求时出错: {str(e)}'})

@socketio.on('check_active_tasks')
def handle_check_active_tasks(data):
    """检查指定来源的活跃任务"""
    session_id = request.sid
    source = data.get('source', 'single')  # 'single', 'parallel', 'precise'

    print(f"🔍 检查活跃任务: 会话={session_id}, 来源={source}")

    # 获取指定来源的活跃任务
    active_tasks = get_active_tasks_by_source(source)

    if not active_tasks:
        print(f"ℹ️ 没有找到来源为 {source} 的活跃任务")
        emit('active_tasks_result', {
            'source': source,
            'has_active_tasks': False,
            'tasks': {}
        })
        return

    # 检查这些任务是否还在运行
    if global_downloader is not None:
        try:
            # 获取当前进度
            overall_progress = global_downloader.get_overall_progress()
            tasks_progress = global_downloader.tasks_progress

            # 过滤出仍在运行的任务
            running_tasks = {}
            for task_id in active_tasks.keys():
                if task_id in tasks_progress:
                    progress = tasks_progress[task_id]
                    running_tasks[task_id] = {
                        'status': progress.status.value,
                        'title': format_task_title_with_multi_p(progress),
                        'progress_percentage': progress.progress_percentage,
                        'download_speed': progress.download_speed / (1024*1024) if progress.download_speed else 0,
                        'is_multi_p': progress.video_info.get('is_multi_p', False) if progress.video_info else False,
                        'current_part': progress.video_info.get('current_part') if progress.video_info else None,
                        'total_pages': progress.video_info.get('total_pages', 1) if progress.video_info else 1,
                        'task_info': active_tasks[task_id]['task_info']
                    }

            if running_tasks:
                print(f"✅ 找到 {len(running_tasks)} 个运行中的 {source} 任务")

                # 发送任务信息和当前进度
                emit('active_tasks_result', {
                    'source': source,
                    'has_active_tasks': True,
                    'overall': {
                        'total_tasks': overall_progress.total_tasks,
                        'completed_tasks': overall_progress.completed_tasks,
                        'running_tasks': overall_progress.running_tasks,
                        'failed_tasks': overall_progress.failed_tasks,
                        'overall_progress': overall_progress.overall_progress,
                        'total_speed': overall_progress.total_speed / (1024*1024),
                        'eta_seconds': overall_progress.eta_seconds
                    },
                    'tasks': running_tasks
                })

                # 启动定期进度更新（为刷新后的客户端）
                def send_periodic_updates():
                    import time
                    for _ in range(30):  # 最多30次，每次2秒，总共1分钟
                        time.sleep(2)
                        try:
                            if global_downloader is not None:
                                current_progress = global_downloader.get_overall_progress()
                                current_tasks = global_downloader.tasks_progress

                                # 检查是否还有运行中的任务
                                if current_progress.running_tasks == 0:
                                    break

                                # 发送进度更新
                                socketio.emit('parallel_progress', {
                                    'source': source,
                                    'overall': {
                                        'total_tasks': current_progress.total_tasks,
                                        'completed_tasks': current_progress.completed_tasks,
                                        'running_tasks': current_progress.running_tasks,
                                        'failed_tasks': current_progress.failed_tasks,
                                        'overall_progress': current_progress.overall_progress,
                                        'total_speed': current_progress.total_speed / (1024*1024),
                                        'eta_seconds': current_progress.eta_seconds
                                    },
                                    'tasks': {
                                        task_id: {
                                            'status': progress.status.value,
                                            'title': format_task_title_with_multi_p(progress),
                                            'progress_percentage': progress.progress_percentage,
                                            'download_speed': progress.download_speed / (1024*1024) if progress.download_speed else 0,
                                            'is_multi_p': progress.video_info.get('is_multi_p', False) if progress.video_info else False,
                                            'current_part': progress.video_info.get('current_part') if progress.video_info else None,
                                            'total_pages': progress.video_info.get('total_pages', 1) if progress.video_info else 1
                                        }
                                        for task_id, progress in current_tasks.items()
                                        if task_id in running_tasks  # 只发送相关任务
                                    }
                                })
                        except Exception as e:
                            print(f"❌ 定期进度更新出错: {e}")
                            break

                # 在后台线程中启动定期更新
                threading.Thread(target=send_periodic_updates, daemon=True).start()
                print(f"🔄 已启动定期进度更新线程")
            else:
                print(f"ℹ️ {source} 任务已完成或不再运行")
                # 标记任务为已完成
                for task_id in active_tasks.keys():
                    mark_task_completed(session_id, task_id)

                emit('active_tasks_result', {
                    'source': source,
                    'has_active_tasks': False,
                    'tasks': {}
                })

        except Exception as e:
            print(f"❌ 检查任务状态失败: {e}")
            emit('active_tasks_result', {
                'source': source,
                'has_active_tasks': False,
                'tasks': {},
                'error': str(e)
            })
    else:
        print(f"ℹ️ 没有全局下载器实例")
        emit('active_tasks_result', {
            'source': source,
            'has_active_tasks': False,
            'tasks': {}
        })

def find_available_port():
    """查找可用端口（真正随机，大范围）"""
    import time
    
    # 使用时间戳确保真正随机
    random.seed(int(time.time() * 1000) % 10000)
    
    # 使用大端口范围 12001-45321
    start_port = 12001
    end_port = 45321
    
    # 随机选择100个端口进行测试
    available_ports = list(range(start_port, end_port + 1))
    test_ports = random.sample(available_ports, min(100, len(available_ports)))
    
    print(f"🎲 端口范围: {start_port}-{end_port} (共 {end_port - start_port + 1} 个端口)")
    print(f"🎯 随机测试端口样例: {test_ports[:5]}...")
    
    for port in test_ports:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(('', port))
                print(f"✅ 找到可用端口: {port}")
                return port
        except OSError:
            continue
    
    # 如果随机测试失败，回退到顺序查找（从一个随机起点开始）
    print("⚠️ 随机端口查找失败，从随机起点顺序查找")
    random_start = random.randint(start_port, end_port - 1000)
    
    for i in range(1000):  # 最多尝试1000个端口
        port = random_start + i
        if port > end_port:
            port = start_port + (port - end_port - 1)
        
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(('', port))
                print(f"✅ 找到可用端口: {port}")
                return port
        except OSError:
            continue
    
    print("❌ 无法找到可用端口")
    return None

def open_browser_delayed(url, delay=2):
    """延迟打开浏览器"""
    time.sleep(delay)
    webbrowser.open(url)

if __name__ == '__main__':
    print("🚀 启动 YuttoPlus Web UI v2.0")
    
    # 查找可用端口
    port = find_available_port()
    if not port:
        print("❌ 无法找到可用端口")
        exit(1)
    
    print(f"🌐 Web UI 地址: http://localhost:{port}")
    print("📋 新功能:")
    print("   • 并行下载支持")
    print("   • 配置文件管理")
    print("   • 实时进度监控")
    print("   • 多会话支持")
    
    # 延迟打开浏览器
    threading.Thread(target=open_browser_delayed, args=(f"http://localhost:{port}",), daemon=True).start()
    
    # 启动服务器
    socketio.run(app, host='0.0.0.0', port=port, debug=False) 