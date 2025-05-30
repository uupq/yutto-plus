#!/usr/bin/env python3
"""
yutto-plus Web UI
基于新的纯 API 实现的 Web 界面
"""

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import json
from pathlib import Path
from yutto_plus import YuttoPlus, TaskStatus
import socket
import webbrowser
import threading
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'yutto_plus_secret'
socketio = SocketIO(app, cors_allowed_origins="*")

# 全局下载器实例
downloader = None
active_tasks = {}

def init_downloader():
    """初始化下载器"""
    global downloader
    downloader = YuttoPlus(
        default_output_dir="/Users/sauterne/Downloads/Bilibili",
        default_quality=80,  # 1080P
        default_audio_quality=30280,  # 320kbps
        default_video_codec="avc",
        default_output_format="mp4",
        overwrite=True
    )

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    print(f'🌐 [连接] 客户端已连接: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开连接"""
    print(f'🔌 [断开] 客户端已断开: {request.sid}')

@socketio.on('download_request')
def handle_download_request(data):
    """处理下载请求"""
    try:
        url = data.get('url', '').strip()
        quality = int(data.get('quality', 80))
        
        if not url:
            emit('error', {'message': '请输入有效的 B站视频链接'})
            return
        
        print(f'📥 [下载请求] URL: {url}, 质量: {quality}')
        
        # 保存当前会话ID，避免在线程中访问 request 上下文
        session_id = request.sid
        
        # 生成任务 ID
        task_id = f"task_{session_id}_{len(active_tasks)}"
        
        # 创建下载任务
        task = downloader.create_download_task(
            url,
            quality=quality,
            output_dir="/Users/sauterne/Downloads/Bilibili"
        )
        
        # 定义回调函数
        def on_progress(current_bytes, total_bytes, speed_bps, item_name):
            """进度回调"""
            percentage = (current_bytes / total_bytes * 100) if total_bytes > 0 else 0
            speed_mb = speed_bps / (1024 * 1024)
            
            # 使用保存的 session_id，而不是 request.sid
            socketio.emit('progress', {
                'task_id': task_id,
                'current_bytes': current_bytes,
                'total_bytes': total_bytes,
                'percentage': percentage,
                'speed_mbps': speed_mb,
                'item_name': item_name
            }, room=session_id)
        
        def on_stream_info(stream_info):
            """流信息回调 - 在流选择完成后立即调用，也用于状态更新"""
            # 检查是否是状态更新消息
            if 'status' in stream_info:
                socketio.emit('status_update', {
                    'task_id': task_id,
                    'status': stream_info['status'],
                    'message': stream_info.get('message', '')
                }, room=session_id)
                print(f'📡 [状态更新] 任务 {task_id} 状态: {stream_info["status"]}')
            else:
                # 正常的流信息
                socketio.emit('stream_info', {
                    'task_id': task_id,
                    'streams': stream_info
                }, room=session_id)
                
                # 同时更新状态为正在下载
                socketio.emit('status_update', {
                    'task_id': task_id,
                    'status': 'downloading',
                    'message': '正在下载...'
                }, room=session_id)
                print(f'📡 [流信息] 任务 {task_id} 流信息已发送')
        
        def on_completion(success, result_info, error_message):
            """完成回调"""
            if success:
                # 使用保存的 session_id
                socketio.emit('download_complete', {
                    'task_id': task_id,
                    'success': True,
                    'result': result_info
                }, room=session_id)
                print(f'✅ [完成] 任务 {task_id} 下载成功')
            else:
                # 使用保存的 session_id
                socketio.emit('download_complete', {
                    'task_id': task_id,
                    'success': False,
                    'error': error_message
                }, room=session_id)
                print(f'❌ [失败] 任务 {task_id} 下载失败: {error_message}')
            
            # 清理任务
            if task_id in active_tasks:
                del active_tasks[task_id]
        
        # 保存任务
        active_tasks[task_id] = task
        
        # 发送视频信息（如果可用）
        if task.video_info:
            emit('video_info', {
                'task_id': task_id,
                'title': task.video_info['title'],
                'uploader': task.video_info['uploader'],
                'bvid': task.video_info['bvid'],
                'duration': task.video_info['duration']
            })
        
        # 启动下载
        task.start(
            progress_callback=on_progress,
            stream_info_callback=on_stream_info,
            completion_callback=on_completion
        )
        
        # 发送任务启动确认
        emit('download_started', {
            'task_id': task_id,
            'url': url,
            'quality': quality
        })
        
    except Exception as e:
        print(f'❌ [错误] 处理下载请求时出错: {e}')
        emit('error', {'message': f'处理请求时出错: {str(e)}'})

@socketio.on('get_video_info')
def handle_get_video_info(data):
    """获取视频信息（预览）"""
    try:
        url = data.get('url', '').strip()
        
        if not url:
            emit('error', {'message': '请输入有效的 B站视频链接'})
            return
        
        print(f'🔍 [信息预览] 获取视频信息: {url}')
        
        # 保存当前会话ID
        session_id = request.sid
        
        # 创建临时任务来获取信息
        import asyncio
        from yutto_plus import BilibiliAPIClient
        
        async def get_info():
            async with BilibiliAPIClient() as client:
                return await client.get_video_info(url)
        
        # 在新的事件循环中运行
        import threading
        
        def info_thread():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                video_info = loop.run_until_complete(get_info())
                
                # 使用保存的 session_id
                socketio.emit('video_info_preview', {
                    'title': video_info['title'],
                    'uploader': video_info['uploader'],
                    'bvid': video_info['bvid'],
                    'duration': video_info['duration'],
                    'description': video_info.get('description', '')[:200] + '...' if len(video_info.get('description', '')) > 200 else video_info.get('description', '')
                }, room=session_id)
                
            except Exception as e:
                # 使用保存的 session_id
                socketio.emit('error', {'message': f'获取视频信息失败: {str(e)}'}, room=session_id)
            finally:
                loop.close()
        
        thread = threading.Thread(target=info_thread, daemon=True)
        thread.start()
        
    except Exception as e:
        print(f'❌ [错误] 获取视频信息时出错: {e}')
        emit('error', {'message': f'获取视频信息失败: {str(e)}'})

@socketio.on('get_task_status')
def handle_get_task_status(data):
    """获取任务状态"""
    task_id = data.get('task_id')
    
    if task_id in active_tasks:
        task = active_tasks[task_id]
        status = task.get_status()
        
        emit('task_status', {
            'task_id': task_id,
            'status': status.value
        })
        
        # 如果有流信息，也发送
        stream_info = task.get_selected_streams_info()
        if stream_info:
            emit('stream_info', {
                'task_id': task_id,
                'streams': stream_info
            })
    else:
        emit('error', {'message': f'任务 {task_id} 不存在'})

def find_available_port(start_port=12001):
    """查找可用端口，从 start_port 开始"""
    port = start_port
    while port < 65535:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', port))
                return port
        except OSError:
            port += 1
    raise RuntimeError("无法找到可用端口")

def open_browser_delayed(url, delay=2):
    """延迟打开浏览器"""
    time.sleep(delay)
    print(f"🌐 [浏览器] 正在打开 {url}")
    webbrowser.open(url)

if __name__ == "__main__":
    print("🚀 [启动] yutto-plus Web UI 正在启动...")
    
    # 查找可用端口
    port = find_available_port(12001)
    print(f"🔌 [端口] 找到可用端口: {port}")
    
    print("📁 [输出] 默认下载目录: /Users/sauterne/Downloads/Bilibili")
    
    # 初始化下载器
    init_downloader()
    
    # 构建访问 URL
    url = f"http://localhost:{port}"
    print(f"🌐 [服务] 访问 {url} 来使用界面")
    
    # 延迟打开浏览器，给服务器时间启动
    browser_thread = threading.Thread(target=open_browser_delayed, args=(url, 3), daemon=True)
    browser_thread.start()
    
    socketio.run(app, host='0.0.0.0', port=port, debug=False)  # 关闭 debug 模式避免重启 