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
import subprocess
import signal
import atexit

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
active_uploader_processes = {}  # 跟踪UP主相关的子进程 {session_id: [process_list]}

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

def get_active_tasks_by_source(source: str):
    """获取指定来源的所有活跃任务，并验证它们是否真的在运行"""
    active_tasks = {}

    # 首先从持久化存储中获取活跃任务
    for task_id, task_data in persistent_tasks.items():
        if task_data['source'] == source and task_data['status'] == 'active':
            # 验证任务是否真的在全局下载器中运行
            if global_downloader is not None:
                if task_id in global_downloader.tasks_progress:
                    active_tasks[task_id] = task_data
                else:
                    # 任务不在下载器中，标记为已完成
                    print(f"🔄 任务 {task_id} 不在下载器中，标记为已完成")
                    mark_task_completed(task_id)
            else:
                # 没有全局下载器，清理所有持久化任务
                print(f"🔄 没有全局下载器，清理任务 {task_id}")
                mark_task_completed(task_id)

    return active_tasks

def mark_task_completed(task_id: str):
    """标记任务为已完成"""
    if task_id in persistent_tasks:
        persistent_tasks[task_id]['status'] = 'completed'

def cleanup_completed_tasks():
    """清理已完成的任务"""
    completed_tasks = [task_id for task_id, task_data in persistent_tasks.items()
                      if task_data['status'] == 'completed']
    for task_id in completed_tasks:
        del persistent_tasks[task_id]

def cleanup_session_tasks(session_id: str, source: str):
    """清理指定会话和来源的所有任务"""
    tasks_to_remove = []
    for task_id, task_data in persistent_tasks.items():
        if task_data.get('session_id') == session_id and task_data.get('source') == source:
            tasks_to_remove.append(task_id)

    for task_id in tasks_to_remove:
        del persistent_tasks[task_id]
        print(f"🧹 清理持久化任务: {task_id} (会话: {session_id}, 来源: {source})")

    print(f"✅ 已清理 {len(tasks_to_remove)} 个持久化任务")

def parse_url_with_parts(url_string: str):
    """
    解析URL字符串，提取URL和分P参数

    支持的分P语法：
        - 无参数: 下载所有分P
        - ~: 明确指定下载所有分P
        - 1,3,5: 下载指定分P
        - 1~5: 下载范围分P
        - ~3: 下载前3个分P
        - 3~: 下载从第3个分P开始（包括第三个）后面所有分P
        - -2~: 下载后2个分P
        - ~-2: 从P1一直下载到倒数第三个分P(即只有最后两个不下载)
        - 1,3,5~8: 混合语法

    Args:
        url_string: 可能包含分P参数的URL字符串

    Returns:
        tuple: (clean_url, parts_selection)

    Examples:
        parse_url_with_parts("https://www.bilibili.com/video/BV123|p=1,3,5")
        -> ("https://www.bilibili.com/video/BV123", "1,3,5")

        parse_url_with_parts("https://www.bilibili.com/video/BV123|p=~-2")
        -> ("https://www.bilibili.com/video/BV123", "~-2")

        parse_url_with_parts("https://www.bilibili.com/video/BV123")
        -> ("https://www.bilibili.com/video/BV123", None)
    """
    # 使用正则表达式匹配URL末尾的分P参数
    # 模式: |p=分P选择 (必须在字符串末尾)
    pattern = r'^(.+?)\|p=([^|]*)$'

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
        # 更新正则表达式以支持新语法（移除$符号，因为已经不使用）
        if not re.match(r'^[0-9,~\-\s]+$', parts_selection):
            raise ValueError(f"无效的分P选择格式: {parts_selection}")

        return clean_url, parts_selection
    else:
        # 没有分P参数，返回原URL
        clean_url = url_string.strip()

        # 验证URL的有效性
        if not clean_url or not ('bilibili.com' in clean_url or 'b23.tv' in clean_url):
            raise ValueError(f"无效的B站视频链接: {clean_url}")

        return clean_url, None

def get_episodes_confirmation_info(url: str, episodes_selection: str = None):
    """
    获取分P确认信息

    Args:
        url: 视频URL
        episodes_selection: 分P选择参数

    Returns:
        Dict: 包含分P确认信息的字典
    """
    try:
        import asyncio
        import sys
        from pathlib import Path

        # 确保能够导入模块
        current_dir = Path(__file__).parent.parent / "src"
        if str(current_dir) not in sys.path:
            sys.path.insert(0, str(current_dir))

        from yutto_plus.core import BilibiliAPIClient, parse_episodes_selection

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
            return {
                'success': False,
                'message': '无法获取视频信息',
                'url': url,
                'episodes_selection': episodes_selection
            }

        total_pages = len(video_info['pages'])

        if episodes_selection:
            selected_indices = parse_episodes_selection(episodes_selection, total_pages)
            selected_parts = [i+1 for i in selected_indices]

            # 检查是否有有效的分P被选中
            if not selected_parts:
                # 分P选择超出范围，改为下载全部
                selected_parts = list(range(1, total_pages + 1))
                episodes_selection_display = f"{episodes_selection} → 全部分P (自动修正)"
                message = f"分P选择 '{episodes_selection}' 超出范围 (视频只有 {total_pages} 个分P)，已自动修正为下载全部分P"
            else:
                episodes_selection_display = episodes_selection
                message = None
        else:
            # 默认下载全部
            selected_parts = list(range(1, total_pages + 1))
            episodes_selection_display = "全部分P (默认)"
            message = None

        return {
            'success': True,
            'url': url,
            'episodes_selection': episodes_selection_display,
            'selected_parts': selected_parts,
            'count': len(selected_parts),
            'total_pages': total_pages,
            'title': video_info.get('title', '未知标题'),
            'message': message
        }

    except Exception as e:
        return {
            'success': False,
            'message': f'获取分P信息失败: {str(e)}',
            'url': url,
            'episodes_selection': episodes_selection
        }

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
        active_downloads[session_id] = {
            'downloader': global_downloader,
            'tasks': {},
            'config': config
        }
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
        sessdata=config.get('sessdata'),
        vip_strict=config.get('vip_strict', False),
        login_strict=config.get('login_strict', False)
    )

    # 保存为全局下载器
    global_downloader = downloader_instance
    global_config = config

    active_downloads[session_id] = {
        'downloader': downloader_instance,
        'tasks': {},
        'config': config
    }

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
        config_template += '\n# episodes_selection: "1,3,5~8"  # 分P选择 (可选): 支持范围和排除语法'

    config_template += f"""

# === 其他设置 ===
overwrite: {str(config_data.get('overwrite', False)).lower()}      # 是否覆盖现有文件
enable_resume: {str(config_data.get('enable_resume', True)).lower()}   # 是否启用断点续传
quiet: {str(config_data.get('quiet', False)).lower()}          # 是否使用安静模式
verbose: {str(config_data.get('verbose', False)).lower()}        # 是否显示详细信息

# === 严格验证设置 ===
vip_strict: {str(config_data.get('vip_strict', False)).lower()}     # 启用严格大会员验证，非大会员时停止下载
login_strict: {str(config_data.get('login_strict', False)).lower()}   # 启用严格登录验证，未登录时停止下载

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

    # 清理UP主相关的子进程
    cleanup_uploader_processes(session_id)

    # 只清理会话数据，不关闭下载器
    if session_id in active_downloads:
        print(f'📋 清理会话数据: {session_id}')
        del active_downloads[session_id]

def cleanup_uploader_processes(session_id):
    """清理指定会话的UP主相关子进程"""
    if session_id in active_uploader_processes:
        processes = active_uploader_processes[session_id]
        print(f'🧹 清理 {len(processes)} 个UP主相关进程 (会话: {session_id})')

        for process in processes:
            try:
                if process.poll() is None:  # 进程仍在运行
                    print(f'🔪 终止进程 PID: {process.pid}')
                    process.terminate()

                    # 等待进程终止，最多等待5秒
                    try:
                        process.wait(timeout=5)
                        print(f'✅ 进程 {process.pid} 已正常终止')
                    except subprocess.TimeoutExpired:
                        # 强制杀死进程
                        print(f'⚡ 强制杀死进程 {process.pid}')
                        process.kill()
                        process.wait()
                        print(f'💀 进程 {process.pid} 已强制终止')
            except Exception as e:
                print(f'⚠️ 清理进程时出错: {e}')

        # 清理进程列表
        del active_uploader_processes[session_id]

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

@socketio.on('start_precise_download_with_confirmation')
def handle_precise_download_with_confirmation(data):
    """处理精准下载（包含分P确认显示）"""
    session_id = request.sid

    try:
        # 获取URL配置列表
        url_configs = data.get('url_configs', [])
        quality = data.get('quality', 80)
        audio_quality = data.get('audio_quality', 30280)
        concurrent = data.get('concurrent', 2)

        if not url_configs:
            emit('error', {'message': '没有提供URL配置'})
            return

        # 1. 先进行分P确认并显示
        confirmations = []
        final_urls = []

        for url_config in url_configs:
            url_string = url_config.get('url', '').strip()
            episodes_selection = url_config.get('episodes_selection', '').strip()
            index = url_config.get('index', 0)

            if not url_string:
                continue

            try:
                # 解析URL和分P参数
                clean_url, url_parts = parse_url_with_parts(url_string)

                # 确定最终的分P选择：URL级别 > 表单级别
                final_episodes_selection = url_parts if url_parts else (episodes_selection if episodes_selection else None)

                # 获取分P确认信息
                confirmation = get_episodes_confirmation_info(clean_url, final_episodes_selection)
                confirmation['index'] = index
                confirmation['original_url'] = url_string
                confirmations.append(confirmation)

                # 构建最终URL
                if confirmation['success']:
                    final_url = clean_url
                    if final_episodes_selection:
                        final_url = f"{clean_url}|p={final_episodes_selection}"
                    final_urls.append(final_url)

            except Exception as e:
                confirmations.append({
                    'index': index,
                    'success': False,
                    'message': f'解析失败: {str(e)}',
                    'original_url': url_string,
                    'episodes_selection': episodes_selection
                })

        # 2. 发送分P确认信息给前端显示
        emit('episodes_confirmations', {
            'confirmations': confirmations,
            'total_urls': len(url_configs)
        })

        # 3. 如果有有效的URL，开始下载
        if final_urls:
            # 使用现有的并行下载逻辑
            download_data = {
                'urls': final_urls,
                'quality': quality,
                'audio_quality': audio_quality,
                'concurrent': concurrent,
                'source': 'precise'
            }

            # 调用现有的并行下载处理函数
            handle_parallel_download_request(download_data)
        else:
            emit('error', {'message': '没有有效的URL可以下载'})

    except Exception as e:
        print(f"❌ 精准下载失败: {e}")
        emit('error', {'message': f'精准下载失败: {str(e)}'})

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
                        "episodes_selection": url_parts,  # 添加分P选择参数
                        "vip_strict": merged_config.get('vip_strict', False),
                        "login_strict": merged_config.get('login_strict', False)
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
        except Exception as save_error:
            print(f"⚠️ 保存任务信息时出错: {save_error}")
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
            'login_status': '已登录会员账户' if merged_config.get('sessdata') else '未登录，只能下载普通清晰度',
            'source': source  # 添加来源信息
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

                    # 清理当前会话的持久化任务
                    source = active_downloads[session_id].get('source', 'parallel')
                    cleanup_session_tasks(session_id, source)

                    socketio.emit('parallel_download_complete', {
                        'final_status': final_status,
                        'tasks_info': tasks_info,
                        'session_id': session_id,
                        'source': source
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
            else:
                print(f"ℹ️ {source} 任务已完成或不再运行")
                # 标记任务为已完成
                for task_id in active_tasks.keys():
                    mark_task_completed(task_id)

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

@socketio.on('uploader_action')
def handle_uploader_action(data):
    """处理UP主管理操作"""
    session_id = request.sid

    try:
        action = data.get('action')
        uploader = data.get('uploader')
        config_file = data.get('config')
        output_dir = data.get('output_dir')

        emit('uploader_status', {
            'status': 'processing',
            'message': f'正在处理{action}操作...'
        })

        if action == 'delete':
            # 删除操作（旧版本，保留兼容性）
            handle_uploader_delete_action(session_id, config_file, output_dir)
        elif action == 'scan_folders':
            # 扫描文件夹操作（删除）
            handle_uploader_scan_folders(session_id, config_file, output_dir)
        elif action == 'scan_folders_for_update':
            # 扫描文件夹操作（更新）
            handle_uploader_scan_folders_for_update(session_id, config_file, output_dir)
        elif action == 'delete_selected':
            # 删除选中的文件夹
            handle_uploader_delete_selected(session_id, data)
        elif action == 'update_selected':
            # 更新选中的文件夹
            handle_uploader_update_selected(session_id, data)
        elif action in ['download', 'update', 'list']:
            # 下载、更新、列表操作
            handle_uploader_video_action(session_id, action, uploader, config_file, output_dir)
        else:
            emit('uploader_error', {'message': f'未知操作: {action}'})

    except Exception as e:
        emit('uploader_error', {'message': f'处理UP主操作时出错: {str(e)}'})

def handle_uploader_delete_action(session_id, config_file, output_dir):
    """处理UP主删除操作"""
    import subprocess
    import threading

    def run_delete():
        try:
            # 构建命令
            cmd = ['python', 'yutto-plus-cli.py']

            if config_file:
                cmd.extend(['--config', f'configs/{config_file}'])

            cmd.append('--delete-uploader')

            if output_dir:
                cmd.append(output_dir)

            # 模拟用户确认输入
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=Path(__file__).parent.parent
            )

            # 发送确认输入
            output, _ = process.communicate(input="yes\nDELETE\n")

            if process.returncode == 0:
                socketio.emit('uploader_success', {
                    'action': 'delete',
                    'message': '删除操作完成',
                    'output': output
                }, room=session_id)
            else:
                socketio.emit('uploader_error', {
                    'message': f'删除操作失败: {output}'
                }, room=session_id)

        except Exception as e:
            socketio.emit('uploader_error', {
                'message': f'删除操作出错: {str(e)}'
            }, room=session_id)

    # 在后台线程中运行
    threading.Thread(target=run_delete, daemon=True).start()

def handle_uploader_video_action(session_id, action, uploader, config_file, output_dir):
    """处理UP主视频操作（下载、更新、列表）- 使用并行下载机制"""
    import asyncio
    import threading

    def run_action():
        try:
            # 获取会话的下载器
            if session_id not in active_downloads:
                init_downloader(session_id)

            downloader_instance = active_downloads[session_id]['downloader']

            # 加载配置
            config = active_downloads[session_id]['config'].copy()
            if config_file:
                config_path = Path(__file__).parent.parent / 'configs' / config_file
                if config_path.exists():
                    with open(config_path, 'r', encoding='utf-8') as f:
                        file_config = yaml.safe_load(f)
                        config.update(file_config)

            # 设置输出目录 - UP主下载使用专门的目录
            if output_dir:
                config['output_dir'] = output_dir
            else:
                # 如果没有指定输出目录，使用UP主专用目录
                if 'output_dir' not in config or not config['output_dir']:
                    config['output_dir'] = '~/Downloads/upper'
                else:
                    # 如果配置文件中有普通下载目录，转换为UP主目录
                    base_dir = config['output_dir']
                    if base_dir.endswith('/Bilibili'):
                        config['output_dir'] = base_dir.replace('/Bilibili', '/upper')
                    elif not base_dir.endswith('/upper'):
                        config['output_dir'] = str(Path(base_dir).parent / 'upper')

            # 运行异步操作获取视频列表
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                if action == 'list':
                    # 仅列表操作
                    result = loop.run_until_complete(run_uploader_list_action(uploader, session_id, config))
                    if result:
                        socketio.emit('uploader_success', {
                            'action': action,
                            'message': f'{action}操作完成',
                            'output': f'{action}操作成功完成'
                        }, room=session_id)
                    else:
                        socketio.emit('uploader_error', {
                            'message': f'{action}操作失败'
                        }, room=session_id)
                else:
                    # 下载或更新操作 - 获取视频URL列表和用户目录
                    urls, user_directory = loop.run_until_complete(get_uploader_video_urls(uploader, session_id, config, action == 'update'))

                    if not urls:
                        socketio.emit('uploader_success', {
                            'action': action,
                            'message': f'没有找到需要{action}的视频',
                            'output': f'没有找到需要{action}的视频'
                        }, room=session_id)
                        return

                    # 使用并行下载机制，传递用户目录
                    start_uploader_parallel_download(session_id, urls, config, action, user_directory)

            finally:
                loop.close()

        except Exception as e:
            socketio.emit('uploader_error', {
                'message': f'{action}操作出错: {str(e)}'
            }, room=session_id)

    # 在后台线程中运行
    threading.Thread(target=run_action, daemon=True).start()

async def run_uploader_list_action(uploader, session_id, config):
    """运行UP主列表操作"""
    try:
        from yutto_plus.core import UploaderVideoManager, parse_up_space_url

        # 解析UP主UID
        if uploader.startswith('http'):
            uid = parse_up_space_url(uploader)
        else:
            uid = int(uploader)

        # 创建UP主视频管理器
        manager = UploaderVideoManager(
            uid=uid,
            output_dir=Path(config.get('output_dir', './Downloads')),
            sessdata=config.get('sessdata')
        )

        # 获取视频列表
        socketio.emit('uploader_progress', {
            'action': 'list',
            'line': f'🔍 正在获取UP主 {uid} 的投稿视频...'
        }, room=session_id)

        videos = await manager.get_uploader_videos()

        # 发送视频列表信息
        socketio.emit('uploader_progress', {
            'action': 'list',
            'line': f'📺 找到 {len(videos)} 个投稿视频'
        }, room=session_id)

        for i, video in enumerate(videos[:10], 1):  # 只显示前10个
            socketio.emit('uploader_progress', {
                'action': 'list',
                'line': f'   {i}. {video["title"]} ({video["duration"]})'
            }, room=session_id)

        if len(videos) > 10:
            socketio.emit('uploader_progress', {
                'action': 'list',
                'line': f'   ... 还有 {len(videos) - 10} 个视频'
            }, room=session_id)

        return True

    except Exception as e:
        socketio.emit('uploader_progress', {
            'action': 'list',
            'line': f'❌ 获取视频列表失败: {str(e)}'
        }, room=session_id)
        return False

async def get_uploader_video_urls(uploader, session_id, config, is_update=False):
    """获取UP主视频URL列表，并返回正确的用户目录"""
    try:
        from yutto_plus.core import UploaderVideoManager, parse_up_space_url

        # 解析UP主UID
        if uploader.startswith('http'):
            uid = parse_up_space_url(uploader)
        else:
            uid = int(uploader)

        # 创建UP主视频管理器
        manager = UploaderVideoManager(
            uid=uid,
            output_dir=Path(config.get('output_dir', './Downloads')),
            sessdata=config.get('sessdata')
        )

        # 获取视频列表
        action_text = "更新" if is_update else "下载"
        socketio.emit('uploader_progress', {
            'action': 'download' if not is_update else 'update',
            'line': f'🔍 正在获取UP主 {uid} 的投稿视频...'
        }, room=session_id)

        videos = await manager.get_uploader_videos(update_check=is_update)

        if not videos:
            socketio.emit('uploader_progress', {
                'action': 'download' if not is_update else 'update',
                'line': f'📺 没有找到需要{action_text}的视频'
            }, room=session_id)
            return [], None

        # 获取用户专用目录
        user_directory = await manager.get_user_directory()

        # 发送总体信息
        socketio.emit('uploader_progress', {
            'action': 'download' if not is_update else 'update',
            'line': f'📺 找到 {len(videos)} 个需要{action_text}的视频，开始下载...'
        }, room=session_id)

        # 返回URL列表和用户目录
        urls = [video['url'] for video in videos]
        return urls, str(user_directory)

    except Exception as e:
        socketio.emit('uploader_progress', {
            'action': 'download' if not is_update else 'update',
            'line': f'❌ 获取视频列表失败: {str(e)}'
        }, room=session_id)
        return [], None

def start_uploader_parallel_download(session_id, urls, config, action, user_directory=None):
    """启动UP主并行下载"""
    try:
        # 获取会话的下载器
        if session_id not in active_downloads:
            init_downloader(session_id)

        downloader_instance = active_downloads[session_id]['downloader']

        # 合并配置
        merged_config = active_downloads[session_id]['config'].copy()
        merged_config.update(config)

        # 使用用户专用目录作为输出目录
        if user_directory:
            merged_config['output_dir'] = user_directory
            print(f"📁 UP主下载目录: {user_directory}")

        # 准备下载任务
        tasks = []
        for url in urls:
            try:
                clean_url, parts_selection = parse_url_with_parts(url)
                task_config = {
                    'quality': merged_config.get('quality', 80),
                    'audio_quality': merged_config.get('audio_quality', 30280),
                    'video_codec': merged_config.get('video_codec', 'avc'),
                    'output_format': merged_config.get('format', 'mp4'),
                    'output_dir': merged_config.get('output_dir', '~/Downloads/upper'),
                    'overwrite': merged_config.get('overwrite', False),
                    'enable_resume': merged_config.get('enable_resume', True),
                    'episodes_selection': parts_selection,
                    # 添加UP主下载的特殊配置
                    'create_folder_for_multi_p': merged_config.get('create_folder_for_multi_p', True),
                    'no_danmaku': merged_config.get('no_danmaku', False),
                    'no_cover': merged_config.get('no_cover', False),
                    'danmaku_format': merged_config.get('danmaku_format', 'ass'),
                    'audio_format': merged_config.get('audio_format', 'mp3'),
                    'audio_bitrate': merged_config.get('audio_bitrate', '192k'),
                    'vip_strict': merged_config.get('vip_strict', False),
                    'login_strict': merged_config.get('login_strict', False)
                }
                tasks.append((clean_url, task_config))
            except Exception as e:
                print(f"⚠️ 跳过无效URL {url}: {e}")
                continue

        if not tasks:
            socketio.emit('uploader_error', {
                'message': '没有有效的下载链接'
            }, room=session_id)
            return

        # 设置进度监控回调
        def setup_progress_callbacks():
            # 检查是否已经设置过回调，避免重复设置
            if hasattr(downloader_instance, '_webui_callback_set'):
                print(f"⚠️ 进度回调已设置，跳过重复设置")
                return

            # 保存原始的进度回调方法
            if not hasattr(downloader_instance, '_original_update_progress'):
                downloader_instance._original_update_progress = downloader_instance._update_progress_display

            def enhanced_update_progress():
                try:
                    # 调用原始方法
                    downloader_instance._original_update_progress()

                    # 发送实时进度到前端
                    overall_progress = downloader_instance.get_overall_progress()
                    tasks_progress = downloader_instance.tasks_progress

                    # 发送整体进度到所有连接的客户端
                    socketio.emit('parallel_progress', {
                        'source': f'uploader_{action}',  # 传递来源标识
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
                save_task_info(session_id, task_id, f'uploader_{action}', task_info)
        except Exception as save_error:
            print(f"⚠️ 保存任务信息时出错: {save_error}")
            # 继续执行，不中断下载

        # 设置回调
        setup_progress_callbacks()

        # 启动并行下载
        downloader_instance.start_parallel_download(display_mode='silent')

        # 保存任务到会话
        active_downloads[session_id]['tasks'].update({tid: 'running' for tid in task_ids})
        active_downloads[session_id]['source'] = f'uploader_{action}'  # 保存下载来源

        # 发送开始确认
        socketio.emit('parallel_download_started', {
            'task_ids': task_ids,
            'total_tasks': len(tasks),
            'concurrent': merged_config.get('concurrent', 2),
            'sessdata_configured': bool(merged_config.get('sessdata')),
            'login_status': '已登录会员账户' if merged_config.get('sessdata') else '未登录，只能下载普通清晰度',
            'source': f'uploader_{action}'  # 添加来源信息
        }, room=session_id)

        # 恢复原始进度回调的函数
        def restore_original_progress_callback():
            """恢复下载器的原始进度回调方法"""
            try:
                if hasattr(downloader_instance, '_original_update_progress'):
                    downloader_instance._update_progress_display = downloader_instance._original_update_progress
                    delattr(downloader_instance, '_webui_callback_set')
                    print(f"✅ 已恢复下载器的原始进度回调方法")
                else:
                    print(f"⚠️ 没有找到原始进度回调方法")
            except Exception as e:
                print(f"❌ 恢复原始进度回调时出错: {e}")

        # 在后台监控完成状态
        def monitor_completion():
            while True:
                time.sleep(2)
                queue_status = downloader_instance.task_manager.get_queue_status()

                if queue_status['running'] == 0 and queue_status['pending'] == 0:
                    # 所有任务完成，恢复原始进度回调
                    restore_original_progress_callback()

                    final_status = downloader_instance.task_manager.get_queue_status()
                    tasks_info = downloader_instance.get_tasks_summary_info()

                    socketio.emit('parallel_download_complete', {
                        'final_status': final_status,
                        'tasks_info': tasks_info,
                        'session_id': session_id,
                        'source': f'uploader_{action}'
                    }, room=session_id)

                    print(f'🎉 [完成] 会话 {session_id} UP主{action}下载完成')
                    break

        # 启动监控线程
        threading.Thread(target=monitor_completion, daemon=True).start()

    except Exception as e:
        print(f'❌ [错误] 启动UP主{action}下载时出错: {e}')

        # 如果出错，也要恢复原始进度回调
        try:
            if session_id in active_downloads:
                downloader_instance = active_downloads[session_id]['downloader']
                if hasattr(downloader_instance, '_original_update_progress'):
                    downloader_instance._update_progress_display = downloader_instance._original_update_progress
                    delattr(downloader_instance, '_webui_callback_set')
                    print(f"✅ 错误处理中已恢复下载器的原始进度回调方法")
        except Exception as restore_error:
            print(f"❌ 错误处理中恢复原始进度回调时出错: {restore_error}")

        socketio.emit('uploader_error', {
            'message': f'启动{action}下载失败: {str(e)}'
        }, room=session_id)

def handle_uploader_scan_folders(session_id, config_file, output_dir):
    """扫描UP主文件夹"""
    import os
    import re
    import threading

    def run_scan():
        try:
            # 获取扫描目录
            scan_dir = output_dir
            if not scan_dir and config_file:
                # 从配置文件获取
                config_path = Path(__file__).parent.parent / 'configs' / config_file
                if config_path.exists():
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = yaml.safe_load(f)
                        scan_dir = config.get('output_dir', '~/Downloads/upper')

            if not scan_dir:
                scan_dir = '~/Downloads/upper'

            # 展开路径
            abs_path = Path(scan_dir).expanduser().resolve()

            if not abs_path.exists() or not abs_path.is_dir():
                socketio.emit('uploader_folders_scanned', {
                    'success': False,
                    'message': f'目录不存在或不是有效目录: {abs_path}'
                }, room=session_id)
                return

            # 扫描符合条件的文件夹
            folders = []
            for item in abs_path.iterdir():
                if item.is_dir():
                    # 检查是否符合 UID-用户名 格式
                    if re.match(r'^\d+-.*$', item.name):
                        csv_file = item / "video_urls.csv"
                        if csv_file.exists():
                            # 统计文件信息
                            file_count = 0
                            total_size = 0

                            try:
                                for file_item in item.rglob("*"):
                                    if file_item.is_file() and file_item.name.lower() != "video_urls.csv":
                                        file_count += 1
                                        total_size += file_item.stat().st_size

                                # 格式化大小信息
                                if total_size > 1024 * 1024 * 1024:
                                    size_info = f"{total_size / (1024 * 1024 * 1024):.1f} GB"
                                elif total_size > 1024 * 1024:
                                    size_info = f"{total_size / (1024 * 1024):.1f} MB"
                                else:
                                    size_info = f"{total_size / 1024:.1f} KB"

                            except Exception as e:
                                file_count = 0
                                size_info = "未知大小"

                            folders.append({
                                'name': item.name,
                                'path': str(item),
                                'file_count': file_count,
                                'size_info': size_info
                            })

            # 按名称排序
            folders.sort(key=lambda x: x['name'])

            socketio.emit('uploader_folders_scanned', {
                'success': True,
                'folders': folders,
                'scan_dir': str(abs_path)
            }, room=session_id)

        except Exception as e:
            socketio.emit('uploader_folders_scanned', {
                'success': False,
                'message': f'扫描文件夹时出错: {str(e)}'
            }, room=session_id)

    # 在后台线程中运行
    threading.Thread(target=run_scan, daemon=True).start()

def handle_uploader_delete_selected(session_id, data):
    """删除选中的UP主文件夹"""
    import shutil
    import threading

    def run_delete():
        try:
            selected_paths = data.get('selected_paths', [])
            if not selected_paths:
                socketio.emit('uploader_error', {
                    'message': '没有选择要删除的文件夹'
                }, room=session_id)
                return

            deleted_items_count = 0
            error_count = 0
            processed_folders = 0

            for folder_path in selected_paths:
                try:
                    folder = Path(folder_path)
                    if not folder.exists() or not folder.is_dir():
                        socketio.emit('uploader_progress', {
                            'action': 'delete_selected',
                            'line': f'⚠️ 跳过不存在的文件夹: {folder.name}'
                        }, room=session_id)
                        continue

                    socketio.emit('uploader_progress', {
                        'action': 'delete_selected',
                        'line': f'📂 处理文件夹: {folder.name}'
                    }, room=session_id)

                    # 获取所有项目
                    items = list(folder.iterdir())
                    non_csv_items = [item for item in items if item.name.lower() != "video_urls.csv"]

                    if not non_csv_items:
                        socketio.emit('uploader_progress', {
                            'action': 'delete_selected',
                            'line': f'   ℹ️ 没有要删除的项目（只有video_urls.csv）'
                        }, room=session_id)
                        processed_folders += 1
                        continue

                    # 删除项目
                    for item in non_csv_items:
                        try:
                            if item.is_file() or item.is_symlink():
                                item.unlink()
                                socketio.emit('uploader_progress', {
                                    'action': 'delete_selected',
                                    'line': f'   - 已删除文件: {item.name}'
                                }, room=session_id)
                                deleted_items_count += 1
                            elif item.is_dir():
                                shutil.rmtree(item)
                                socketio.emit('uploader_progress', {
                                    'action': 'delete_selected',
                                    'line': f'   - 已删除文件夹: {item.name}'
                                }, room=session_id)
                                deleted_items_count += 1
                        except Exception as e:
                            socketio.emit('uploader_progress', {
                                'action': 'delete_selected',
                                'line': f'   ❌ 删除 {item.name} 时出错: {e}'
                            }, room=session_id)
                            error_count += 1

                    processed_folders += 1

                except Exception as e:
                    socketio.emit('uploader_progress', {
                        'action': 'delete_selected',
                        'line': f'❌ 处理文件夹 {Path(folder_path).name} 时出错: {e}'
                    }, room=session_id)
                    error_count += 1

            # 发送完成信息
            socketio.emit('uploader_success', {
                'action': 'delete_selected',
                'message': f'删除完成！处理了 {processed_folders} 个文件夹，删除了 {deleted_items_count} 个项目' +
                          (f'，遇到 {error_count} 个错误' if error_count > 0 else ''),
                'output': f'删除统计：\n- 处理文件夹: {processed_folders}\n- 删除项目: {deleted_items_count}\n- 错误数量: {error_count}'
            }, room=session_id)

        except Exception as e:
            socketio.emit('uploader_error', {
                'message': f'删除操作出错: {str(e)}'
            }, room=session_id)

    # 在后台线程中运行
    threading.Thread(target=run_delete, daemon=True).start()

def handle_uploader_scan_folders_for_update(session_id, config_file, output_dir):
    """扫描UP主文件夹（更新操作）"""
    import os
    import re
    import threading

    def run_scan():
        try:
            # 获取扫描目录
            scan_dir = output_dir
            if not scan_dir and config_file:
                # 从配置文件获取
                config_path = Path(__file__).parent.parent / 'configs' / config_file
                if config_path.exists():
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = yaml.safe_load(f)
                        scan_dir = config.get('output_dir', '~/Downloads/upper')

            if not scan_dir:
                scan_dir = '~/Downloads/upper'

            # 展开路径
            abs_path = Path(scan_dir).expanduser().resolve()

            if not abs_path.exists() or not abs_path.is_dir():
                socketio.emit('uploader_folders_scanned_for_update', {
                    'success': False,
                    'message': f'目录不存在或不是有效目录: {abs_path}'
                }, room=session_id)
                return

            # 扫描符合条件的文件夹
            folders = []
            for item in abs_path.iterdir():
                if item.is_dir():
                    # 检查是否符合 UID-用户名 格式
                    if re.match(r'^\d+-.*$', item.name):
                        csv_file = item / "video_urls.csv"
                        if csv_file.exists():
                            # 统计文件信息
                            file_count = 0
                            total_size = 0

                            try:
                                for file_item in item.rglob("*"):
                                    if file_item.is_file() and file_item.name.lower() != "video_urls.csv":
                                        file_count += 1
                                        total_size += file_item.stat().st_size

                                # 格式化大小信息
                                if total_size > 1024 * 1024 * 1024:
                                    size_info = f"{total_size / (1024 * 1024 * 1024):.1f} GB"
                                elif total_size > 1024 * 1024:
                                    size_info = f"{total_size / (1024 * 1024):.1f} MB"
                                else:
                                    size_info = f"{total_size / 1024:.1f} KB"

                            except Exception as e:
                                file_count = 0
                                size_info = "未知大小"

                            folders.append({
                                'name': item.name,
                                'path': str(item),
                                'file_count': file_count,
                                'size_info': size_info
                            })

            # 按名称排序
            folders.sort(key=lambda x: x['name'])

            socketio.emit('uploader_folders_scanned_for_update', {
                'success': True,
                'folders': folders,
                'scan_dir': str(abs_path)
            }, room=session_id)

        except Exception as e:
            socketio.emit('uploader_folders_scanned_for_update', {
                'success': False,
                'message': f'扫描文件夹时出错: {str(e)}'
            }, room=session_id)

    # 在后台线程中运行
    threading.Thread(target=run_scan, daemon=True).start()

def handle_uploader_update_selected(session_id, data):
    """更新选中的UP主文件夹 - 使用接口实现三级进度条"""
    import asyncio
    import threading
    import re
    import time

    def run_update():
        try:
            selected_paths = data.get('selected_paths', [])
            if not selected_paths:
                socketio.emit('uploader_error', {
                    'message': '没有选择要更新的文件夹'
                }, room=session_id)
                return

            # 解析UP主信息
            uploader_infos = []
            for folder_path in selected_paths:
                try:
                    folder = Path(folder_path)
                    if not folder.exists() or not folder.is_dir():
                        continue

                    # 从文件夹名称提取UID和用户名
                    folder_name = folder.name
                    uid_match = re.match(r'^(\d+)-(.+)$', folder_name)
                    if not uid_match:
                        continue

                    uid = int(uid_match.group(1))
                    username = uid_match.group(2)

                    uploader_infos.append({
                        'uid': uid,
                        'username': username,
                        'folder_name': folder_name,
                        'output_dir': folder.parent
                    })
                except Exception as e:
                    print(f"⚠️ 解析文件夹 {folder_path} 失败: {e}")
                    continue

            if not uploader_infos:
                socketio.emit('uploader_error', {
                    'message': '没有找到有效的UP主文件夹'
                }, room=session_id)
                return

            # 运行异步更新 - 使用更安全的方式
            try:
                # 尝试获取当前事件循环
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # 如果当前循环正在运行，创建新的线程来运行异步任务
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as executor:
                            future = executor.submit(asyncio.run, run_uploader_batch_update(session_id, uploader_infos))
                            future.result()  # 等待完成
                    else:
                        # 如果当前循环没有运行，直接运行
                        loop.run_until_complete(run_uploader_batch_update(session_id, uploader_infos))
                except RuntimeError:
                    # 没有事件循环，创建新的
                    asyncio.run(run_uploader_batch_update(session_id, uploader_infos))
            except Exception as e:
                print(f"❌ 异步执行出错: {e}")
                import traceback
                print(f"详细错误信息: {traceback.format_exc()}")
                raise

        except Exception as e:
            socketio.emit('uploader_error', {
                'message': f'更新操作出错: {str(e)}'
            }, room=session_id)

    # 在后台线程中运行
    threading.Thread(target=run_update, daemon=True).start()


async def run_uploader_batch_update(session_id, uploader_infos):
    """运行批量UP主更新，带三级进度条"""
    try:
        import asyncio  # 确保导入asyncio

        # 添加当前目录到Python路径
        current_dir = Path(__file__).parent.parent
        if str(current_dir) not in sys.path:
            sys.path.insert(0, str(current_dir))

        from yutto_plus.core import UploaderVideoManager, YuttoPlus

        total_uploaders = len(uploader_infos)
        completed_uploaders = 0
        failed_uploaders = 0

        # 发送初始状态
        socketio.emit('uploader_batch_progress', {
            'action': 'update_selected',
            'level1': {  # UP主总体进度
                'current': 0,
                'total': total_uploaders,
                'percentage': 0,
                'status': '准备开始批量更新...'
            },
            'level2': {  # 当前UP主视频进度
                'current': 0,
                'total': 0,
                'percentage': 0,
                'status': '等待开始...',
                'uploader_name': ''
            },
            'level3': []  # 并行下载进度
        }, room=session_id)

        print(f"🚀 开始批量更新循环，总共需要处理 {total_uploaders} 个UP主")

        for i, uploader_info in enumerate(uploader_infos):
            uid = uploader_info['uid']
            username = uploader_info['username']
            folder_name = uploader_info['folder_name']
            output_dir = uploader_info['output_dir']

            print(f"🔄 开始处理UP主 {i+1}/{total_uploaders}: {folder_name}")

            try:
                # 更新Level1进度
                socketio.emit('uploader_batch_progress', {
                    'action': 'update_selected',
                    'level1': {
                        'current': i,
                        'total': total_uploaders,
                        'percentage': int((i / total_uploaders) * 100),
                        'status': f'正在处理: {folder_name} ({i+1}/{total_uploaders})'
                    },
                    'level2': {
                        'current': 0,
                        'total': 0,
                        'percentage': 0,
                        'status': '正在获取视频列表...',
                        'uploader_name': username
                    },
                    'level3': []
                }, room=session_id)

                # 创建UP主视频管理器
                manager = UploaderVideoManager(
                    uid=uid,
                    output_dir=output_dir,
                    sessdata="",  # 从配置获取
                    username=username
                )

                # 获取视频列表
                videos = await manager.get_uploader_videos(update_check=True)

                if not videos:
                    print(f"⚠️ UP主 {username} 没有视频，跳过")
                    completed_uploaders += 1
                    continue

                # 统计视频信息
                total_videos = len(videos)
                downloaded_count = sum(1 for v in videos if v.get('downloaded', '').lower() == 'true')
                new_count = sum(1 for v in videos if v.get('downloaded', '').lower() != 'true')

                print(f"📊 UP主 {username}: 总视频={total_videos}, 已下载={downloaded_count}, 新增={new_count}")

                # 更新Level2进度
                socketio.emit('uploader_batch_progress', {
                    'action': 'update_selected',
                    'level1': {
                        'current': i,
                        'total': total_uploaders,
                        'percentage': int((i / total_uploaders) * 100),
                        'status': f'正在处理: {folder_name} ({i+1}/{total_uploaders})'
                    },
                    'level2': {
                        'current': downloaded_count,
                        'total': total_videos,
                        'percentage': int((downloaded_count / total_videos) * 100) if total_videos > 0 else 100,
                        'status': f'总视频: {total_videos}, 已下载: {downloaded_count}, 新增: {new_count}',
                        'uploader_name': username
                    },
                    'level3': []
                }, room=session_id)

                # 如果有新视频需要下载
                if new_count > 0:
                    print(f"🚀 开始下载UP主 {username} 的 {new_count} 个新视频...")

                    # 获取需要下载的视频URL列表
                    new_videos = [v for v in videos if v.get('downloaded', '').lower() != 'true']
                    video_urls = [v['url'] for v in new_videos]

                    # 获取用户目录
                    user_directory = await manager.get_user_directory()

                    # 开始下载，带Level3进度回调
                    success = await download_uploader_videos_with_progress(
                        session_id, video_urls, str(user_directory),
                        i, total_uploaders, username, downloaded_count, total_videos
                    )

                    if success:
                        print(f"✅ UP主 {username} 下载完成")
                        completed_uploaders += 1
                    else:
                        print(f"❌ UP主 {username} 下载失败")
                        failed_uploaders += 1
                else:
                    print(f"✅ UP主 {username} 没有新视频需要下载")
                    completed_uploaders += 1

            except Exception as e:
                failed_uploaders += 1
                error_msg = f"❌ 处理UP主 {folder_name} 失败: {e}"
                print(error_msg)
                import traceback
                print(f"详细错误信息: {traceback.format_exc()}")

                # 发送错误信息到前端
                socketio.emit('uploader_batch_progress', {
                    'action': 'update_selected',
                    'level1': {
                        'current': i,
                        'total': total_uploaders,
                        'percentage': int((i / total_uploaders) * 100),
                        'status': f'处理失败: {folder_name} ({i+1}/{total_uploaders})'
                    },
                    'level2': {
                        'current': 0,
                        'total': 0,
                        'percentage': 0,
                        'status': f'错误: {str(e)}',
                        'uploader_name': username
                    },
                    'level3': []
                }, room=session_id)

            # 短暂延迟
            await asyncio.sleep(1)

        print(f"🏁 批量更新循环结束，准备发送最终状态")
        print(f"📊 最终统计: 成功={completed_uploaders}, 失败={failed_uploaders}, 总数={total_uploaders}")

        # 发送最终状态
        socketio.emit('uploader_batch_progress', {
            'action': 'update_selected',
            'level1': {
                'current': total_uploaders,
                'total': total_uploaders,
                'percentage': 100,
                'status': f'批量更新完成！成功: {completed_uploaders}, 失败: {failed_uploaders}'
            },
            'level2': {
                'current': 0,
                'total': 0,
                'percentage': 100,
                'status': '全部完成',
                'uploader_name': ''
            },
            'level3': []
        }, room=session_id)

        # 发送完成信息
        socketio.emit('uploader_success', {
            'action': 'update_selected',
            'message': f'批量更新完成！成功更新 {completed_uploaders} 个UP主' +
                      (f'，失败 {failed_uploaders} 个' if failed_uploaders > 0 else ''),
            'output': f'更新统计：\n- 成功更新: {completed_uploaders}\n- 失败数量: {failed_uploaders}'
        }, room=session_id)

    except Exception as e:
        error_msg = f'批量更新出错: {str(e)}'
        print(f"❌ {error_msg}")
        import traceback
        print(f"详细错误信息: {traceback.format_exc()}")

        socketio.emit('uploader_error', {
            'message': error_msg
        }, room=session_id)


async def download_uploader_videos_with_progress(session_id, video_urls, output_dir,
                                                uploader_index, total_uploaders, username,
                                                downloaded_count, total_videos):
    """下载UP主视频，带三级进度条回调"""
    try:
        import asyncio
        from yutto_plus.core import YuttoPlus

        # 创建下载器实例
        downloader = YuttoPlus(
            max_concurrent=2,  # 固定并发数为2
            default_output_dir=output_dir,
            default_quality=80,
            default_audio_quality=30280,
            default_video_codec='avc',
            default_output_format='mp4',
            overwrite=False,
            enable_resume=True,
            sessdata=""
        )

        # 准备下载任务
        tasks = []
        for url in video_urls:
            task_config = {
                'quality': 80,
                'audio_quality': 30280,
                'video_codec': 'avc',
                'output_format': 'mp4',
                'output_dir': output_dir,
                'overwrite': False,
                'enable_resume': True,
                'episodes_selection': '',
                'create_folder_for_multi_p': True,
                'no_danmaku': False,
                'no_cover': False,
                'danmaku_format': 'ass',
                'audio_format': 'mp3',
                'audio_bitrate': '192k'
            }
            tasks.append((url, task_config))

        # 添加任务到下载器
        task_ids = downloader.add_download_tasks(tasks)

        # 设置进度回调
        def setup_progress_callback():
            original_update = downloader._update_progress_display

            def enhanced_update():
                try:
                    # 调用原始更新
                    original_update()

                    # 获取当前进度
                    overall_progress = downloader.get_overall_progress()
                    tasks_progress = downloader.tasks_progress

                    # 计算Level2进度（当前UP主的视频进度）
                    current_completed = downloaded_count + overall_progress.completed_tasks
                    level2_percentage = int((current_completed / total_videos) * 100) if total_videos > 0 else 100

                    # 构建Level3进度（并行下载任务）
                    level3_tasks = []
                    for task_id, progress in tasks_progress.items():
                        if progress.status.value in ['downloading', 'processing', 'completed']:
                            level3_tasks.append({
                                'task_id': task_id,
                                'title': progress.video_info.get('title', '未知标题') if progress.video_info else '未知标题',
                                'status': progress.status.value,
                                'percentage': progress.progress_percentage,
                                'speed': progress.download_speed / (1024*1024) if progress.download_speed else 0  # MB/s
                            })

                    # 发送三级进度更新
                    socketio.emit('uploader_batch_progress', {
                        'action': 'update_selected',
                        'level1': {
                            'current': uploader_index,
                            'total': total_uploaders,
                            'percentage': int((uploader_index / total_uploaders) * 100),
                            'status': f'正在下载: {username} ({uploader_index+1}/{total_uploaders})'
                        },
                        'level2': {
                            'current': current_completed,
                            'total': total_videos,
                            'percentage': level2_percentage,
                            'status': f'下载进度: {current_completed}/{total_videos} 个视频',
                            'uploader_name': username
                        },
                        'level3': level3_tasks
                    }, room=session_id)

                except Exception as e:
                    print(f"❌ 进度回调出错: {e}")

            downloader._update_progress_display = enhanced_update

        # 设置回调
        setup_progress_callback()

        # 启动下载
        downloader.start_parallel_download(display_mode='silent')

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

        return success_count > 0

    except Exception as e:
        print(f"❌ 下载UP主视频失败: {e}")
        return False


def cleanup_all_processes():
    """清理所有UP主相关进程"""
    print("🧹 清理所有UP主相关进程...")

    for session_id in list(active_uploader_processes.keys()):
        cleanup_uploader_processes(session_id)

    print("✅ 进程清理完成")

def signal_handler(signum, frame):
    """信号处理器"""
    print(f"\n🛑 收到信号 {signum}，正在清理...")
    cleanup_all_processes()
    print("👋 WebUI 已退出")
    sys.exit(0)

def open_browser_delayed(url, delay=2):
    """延迟打开浏览器"""
    time.sleep(delay)
    webbrowser.open(url)

if __name__ == '__main__':
    print("🚀 启动 YuttoPlus Web UI v2.0")

    # 注册信号处理器和退出清理
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    atexit.register(cleanup_all_processes)

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