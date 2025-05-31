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
from yutto_plus import YuttoPlus, TaskStatus
from config_manager import ConfigManager
import socket
import webbrowser
import threading
import time
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'yutto_plus_secret'
socketio = SocketIO(app, cors_allowed_origins="*")

# 全局实例
downloader = None
config_manager = ConfigManager()
active_downloads = {}  # {session_id: {downloader, tasks}}

def init_downloader(session_id, config=None):
    """为每个会话初始化独立的下载器"""
    if config:
        # 使用配置文件参数
        downloader_instance = YuttoPlus(
            max_concurrent=config.get('concurrent', 3),
            default_output_dir=config.get('output_dir', './Downloads'),
            default_quality=config.get('quality', 80),
            default_audio_quality=config.get('audio_quality', 30280),
            default_video_codec=config.get('video_codec', 'avc'),
            default_output_format=config.get('format', 'mp4'),
            overwrite=config.get('overwrite', False),
            enable_resume=config.get('enable_resume', True),
            sessdata=config.get('sessdata')
        )
    else:
        # 默认配置
        downloader_instance = YuttoPlus(
            max_concurrent=2,
            default_output_dir="./Downloads",
            default_quality=80,
            default_audio_quality=30280,
            overwrite=False
        )
    
    active_downloads[session_id] = {
        'downloader': downloader_instance,
        'tasks': {},
        'config': config or {}
    }
    
    return downloader_instance

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/config/<path:filename>')
def serve_config(filename):
    """提供配置文件下载"""
    config_dir = Path('.')
    return send_from_directory(config_dir, filename)

@app.route('/api/configs')
def get_configs():
    """获取可用的配置文件列表"""
    config_files = []
    
    # 查找YAML配置文件
    for config_file in Path('.').glob('yutto-*.yaml'):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            config_files.append({
                'name': config_file.stem,
                'filename': config_file.name,
                'description': config.get('description', '无描述'),
                'concurrent': config.get('concurrent', 1),
                'quality': config.get('quality', 80),
                'audio_only': config.get('audio_only', False)
            })
        except Exception as e:
            print(f"⚠️ 读取配置文件失败 {config_file}: {e}")
    
    return jsonify(config_files)

@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    session_id = request.sid
    print(f'🌐 [连接] 客户端已连接: {session_id}')
    
    # 为新会话初始化下载器
    init_downloader(session_id)

@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开连接"""
    session_id = request.sid
    print(f'🔌 [断开] 客户端已断开: {session_id}')
    
    # 清理会话数据
    if session_id in active_downloads:
        # 关闭下载器
        try:
            active_downloads[session_id]['downloader'].shutdown()
        except:
            pass
        del active_downloads[session_id]

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
        config_path = Path(config_filename)
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
            'message': f'配置文件已加载: {config.get("description", config_filename)}'
        })
        
        print(f'⚙️ [配置] 会话 {session_id} 加载配置: {config.get("description", config_filename)}')
        
    except Exception as e:
        print(f'❌ [错误] 加载配置文件时出错: {e}')
        emit('error', {'message': f'加载配置文件时出错: {str(e)}'})

@socketio.on('parallel_download_request')
def handle_parallel_download_request(data):
    """处理并行下载请求"""
    try:
        session_id = request.sid
        urls = data.get('urls', [])
        custom_config = data.get('config', {})
        
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
        for url in urls:
            if url.strip():
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
                    "audio_bitrate": merged_config.get('audio_bitrate', '192k')
                }
                tasks.append((url.strip(), task_config))
        
        if not tasks:
            emit('error', {'message': '没有有效的下载链接'})
            return
        
        # 设置进度监控回调
        def setup_progress_callbacks():
            # 重写下载器的进度回调方法
            original_update_progress = downloader_instance._update_progress_display
            
            def enhanced_update_progress():
                # 调用原始方法
                original_update_progress()
                
                # 发送实时进度到前端
                overall_progress = downloader_instance.get_overall_progress()
                tasks_progress = downloader_instance.tasks_progress
                
                # 发送整体进度
                socketio.emit('parallel_progress', {
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
                            'title': progress.video_info.get('title', '未知标题') if progress.video_info else '未知标题',
                            'progress_percentage': progress.progress_percentage,
                            'download_speed': progress.download_speed / (1024*1024) if progress.download_speed else 0
                        }
                        for task_id, progress in tasks_progress.items()
                    }
                }, room=session_id)
            
            # 替换方法
            downloader_instance._update_progress_display = enhanced_update_progress
        
        # 添加任务到下载器
        task_ids = downloader_instance.add_download_tasks(tasks)
        
        # 设置回调
        setup_progress_callbacks()
        
        # 启动并行下载
        downloader_instance.start_parallel_download(display_mode='silent')
        
        # 保存任务到会话
        active_downloads[session_id]['tasks'].update({tid: 'running' for tid in task_ids})
        
        # 发送开始确认
        emit('parallel_download_started', {
            'task_ids': task_ids,
            'total_tasks': len(tasks),
            'concurrent': merged_config.get('concurrent', 2)
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
            'config': {'quality': quality, 'concurrent': 1}
        }
        
        handle_parallel_download_request(parallel_data)
        
    except Exception as e:
        print(f'❌ [错误] 处理单个下载请求时出错: {e}')
        emit('error', {'message': f'处理单个下载请求时出错: {str(e)}'})

@socketio.on('get_session_status')
def handle_get_session_status():
    """获取会话状态"""
    session_id = request.sid
    
    if session_id in active_downloads:
        downloader_instance = active_downloads[session_id]['downloader']
        config = active_downloads[session_id]['config']
        
        queue_status = downloader_instance.task_manager.get_queue_status()
        overall_progress = downloader_instance.get_overall_progress()
        
        emit('session_status', {
            'config_loaded': bool(config),
            'config_description': config.get('description', '默认配置'),
            'queue_status': queue_status,
            'overall_progress': {
                'total_tasks': overall_progress.total_tasks,
                'completed_tasks': overall_progress.completed_tasks,
                'running_tasks': overall_progress.running_tasks,
                'failed_tasks': overall_progress.failed_tasks,
                'overall_progress': overall_progress.overall_progress
            }
        })

def find_available_port(start_port=12001):
    """查找可用端口"""
    for port in range(start_port, start_port + 100):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', port))
                return port
        except OSError:
            continue
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