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
    """为每个会话初始化独立的下载器"""
    if config is None:
        # 默认加载WebUI配置文件
        webui_config_path = ensure_webui_config()
        with open(webui_config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    
    # 使用配置文件参数
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