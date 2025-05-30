# yutto-plus - 现代化 B站视频下载器

一个基于纯 HTTP API 的 B站视频下载器，提供 Web UI、CLI 和 Python API 三种使用方式。完全重写了下载逻辑，不依赖 yutto CLI 输出解析，专注于**核心下载功能**和**用户体验**。

> **功能完整度**: 60% (核心下载功能 100% 完成，辅助功能待实现)

## ✨ 主要特性

### 🚀 核心优势
- **🌐 现代化 Web UI**: 自动端口选择，自动打开浏览器，实时进度显示
- **📊 统一进度管理**: 多流进度合并计算，避免进度条横跳
- **🔄 实时回调机制**: 编程友好的进度、状态、完成回调
- **🎯 智能流选择**: 根据质量偏好自动选择最佳视频和音频流
- **⚡ 并发下载**: 视频流和音频流并行下载，提高效率
- **🔧 纯 API 实现**: 直接调用 B站 HTTP API，不依赖 CLI 解析

### 📹 视频功能
- **多清晰度**: 8K/4K/1080P60/1080P/720P/480P/360P
- **多编码**: AVC(H.264)/HEVC(H.265)/AV1 自动选择
- **音频质量**: Hi-Res/320kbps/128kbps/64kbps
- **输出格式**: MP4/MKV/MOV，FFmpeg 自动合并

### 🎛️ 用户体验
- **Web 界面**: 响应式设计，实时状态更新
- **命令行工具**: 简洁易用的 CLI 接口
- **API 接口**: 面向对象设计，灵活配置
- **状态管理**: 准备中 → 下载中 → 合并中 → 完成
- **错误处理**: 友好的错误信息和重试机制

## 🚀 快速开始

### 方式一：CLI 命令行 (推荐)

```bash
# 基本用法
python3 yutto-plus.py "https://www.bilibili.com/video/BV1LWjXzvEX1/"

# 指定质量和输出目录
python3 yutto-plus.py -q 80 -o "./Downloads" "https://www.bilibili.com/video/BV1LWjXzvEX1/"

# 显示帮助
python3 yutto-plus.py --help
```

### 方式二：Web UI

```bash
# 启动 Web UI
python3 web_ui.py
# 自动打开浏览器，开始使用！
```

### 方式三：Python API

```python
from yutto_plus import YuttoPlus
import time

# 创建下载器
downloader = YuttoPlus(
    default_output_dir="./Downloads",
    default_quality=80,  # 1080P
    default_audio_quality=30280,  # 320kbps
    overwrite=True
)

# 创建下载任务
task = downloader.create_download_task(
    "https://www.bilibili.com/video/BV1LWjXzvEX1/",
    quality=64  # 可覆盖默认设置
)

# 定义回调函数
def on_progress(current, total, speed, item):
    percent = (current / total * 100) if total > 0 else 0
    print(f"进度: {percent:.1f}% | 速度: {speed/(1024**2):.2f} MB/s")

def on_completion(success, result, error):
    if success:
        print(f"✅ 下载完成: {result['output_filepath']}")
        print(f"📺 视频流: {result['selected_video_stream_info']}")
        print(f"🔊 音频流: {result['selected_audio_stream_info']}")
    else:
        print(f"❌ 下载失败: {error}")

# 启动下载
task.start(
    progress_callback=on_progress,
    completion_callback=on_completion
)

# 等待完成
while task.get_status().value not in ['completed', 'failed']:
    time.sleep(1)
```

## 📖 CLI 使用指南

### 基本命令

```bash
# 下载视频（默认1080P）
python3 yutto-plus.py "URL"

# 指定视频质量
python3 yutto-plus.py -q 127 "URL"  # 8K
python3 yutto-plus.py -q 120 "URL"  # 4K  
python3 yutto-plus.py -q 80 "URL"   # 1080P
python3 yutto-plus.py -q 64 "URL"   # 720P

# 指定音频质量
python3 yutto-plus.py -aq 30280 "URL"  # 320kbps
python3 yutto-plus.py -aq 30232 "URL"  # 128kbps

# 指定输出目录
python3 yutto-plus.py -o "./Downloads" "URL"

# 覆盖已存在文件
python3 yutto-plus.py -w "URL"

# 指定输出格式
python3 yutto-plus.py -f mkv "URL"
```

### 完整参数列表

```
用法: yutto-plus.py [-h] [-q QUALITY] [-aq AUDIO_QUALITY] [-o OUTPUT_DIR] 
                   [-f FORMAT] [-w] [--video-codec CODEC] [--sessdata SESSDATA] 
                   [--quiet] [--verbose] url

位置参数:
  url                   B站视频链接

可选参数:
  -h, --help           显示帮助信息
  -q, --quality        视频质量 (16-127, 默认: 80)
  -aq, --audio-quality 音频质量 (30216-30251, 默认: 30280)  
  -o, --output         输出目录 (默认: ./Downloads)
  -f, --format         输出格式 (mp4/mkv/mov, 默认: mp4)
  -w, --overwrite      覆盖已存在文件
  --video-codec        视频编码偏好 (avc/hevc/av1, 默认: avc)
  --sessdata           B站登录凭证，会自动验证登录状态和会员身份
  --quiet              安静模式，减少输出
  --verbose            详细模式，显示调试信息
```

### SESSDATA 登录验证

```bash
# 使用 SESSDATA 登录，自动验证状态
python3 yutto-plus.py --sessdata "你的SESSDATA值" "URL"

# 系统会显示登录状态：
# 🎖️ [登录状态] ✅ 成功以大会员身份登录～
# 或
# 👤 [登录状态] ✅ 登录成功，以非大会员身份登录
# 或  
# ❌ [登录状态] SESSDATA 无效或已过期，请检查后重试
```

## 📖 API 文档

### YuttoPlus 类

```python
downloader = YuttoPlus(
    # 必需依赖
    sessdata=None,                    # B站登录凭证 (可选)
    
    # 核心配置
    default_output_dir="./downloads", # 下载目录
    default_quality=80,               # 视频质量 (16-127)
    default_audio_quality=30280,      # 音频质量
    default_video_codec="avc",        # 视频编码偏好
    default_output_format="mp4",      # 输出格式
    overwrite=False                   # 是否覆盖已存在文件
)
```

#### 视频质量对应表
| 代码 | 清晰度 | 代码 | 清晰度 |
|------|--------|------|--------|
| 127 | 8K 超高清 | 80 | 1080P 高清 |
| 120 | 4K 超清 | 64 | 720P 高清 |
| 116 | 1080P60 | 32 | 480P 清晰 |
| 112 | 1080P+ | 16 | 360P 流畅 |

#### 音频质量对应表
| 代码 | 质量 |
|------|------|
| 30251 | Hi-Res 无损 |
| 30280 | 320kbps |
| 30232 | 128kbps |
| 30216 | 64kbps |

### DownloadTask 类

```python
# 创建任务
task = downloader.create_download_task(
    url="https://www.bilibili.com/video/BV...",
    quality=80,           # 覆盖默认质量
    output_dir="./custom" # 覆盖默认目录
)

# 启动下载
task.start(
    progress_callback=callback_func,    # 进度回调
    stream_info_callback=info_func,     # 流信息回调  
    completion_callback=done_func       # 完成回调
)

# 状态查询
status = task.get_status()              # pending/extracting/downloading/merging/completed/failed
streams = task.get_selected_streams_info()  # 获取流信息
```

## 🆚 与 yutto 对比

### ✅ 已实现功能
| 功能 | yutto | yutto-plus | 状态 |
|------|-------|------------|------|
| 视频/音频下载 | ✅ | ✅ | **完全支持** |
| 清晰度选择 | ✅ | ✅ | **完全支持** |
| 编码选择 | ✅ | ✅ | **完全支持** |
| 并发下载 | ✅ | ✅ | **重新实现，更好** |
| 进度显示 | ✅ | ✅ | **更好的体验** |
| 格式转换 | ✅ | ✅ | **FFmpeg 集成** |
| 登录验证 | ✅ | ✅ | **自动验证状态** |
| 会员状态显示 | ✅ | ✅ | **清晰显示会员身份** |

### ❌ 待实现功能
| 功能 | yutto | yutto-plus | 计划 |
|------|-------|------------|------|
| 弹幕下载 | ✅ | ❌ | 🔥 高优先级 |
| 字幕下载 | ✅ | ❌ | 🔥 高优先级 |
| 封面下载 | ✅ | ❌ | 🔥 高优先级 |
| 批量下载 | ✅ | ❌ | 🟡 中优先级 |
| 代理支持 | ✅ | ❌ | 🟡 中优先级 |

### 🚀 yutto-plus 的独有优势
| 功能 | yutto | yutto-plus |
|------|-------|------------|
| **Web UI** | ❌ | ✅ |
| **实时回调** | ❌ | ✅ |
| **任务对象** | ❌ | ✅ |
| **状态管理** | ❌ | ✅ |
| **统一进度** | ❌ | ✅ |
| **纯 API** | ❌ | ✅ |

## 💡 使用场景

### 🎯 适合场景
- ✅ **单视频下载**: 核心功能完善，体验优秀
- ✅ **程序化集成**: API 接口友好，回调机制完整
- ✅ **Web 应用**: 现代化 UI，实时进度显示
- ✅ **命令行使用**: 简洁的 CLI 接口
- ✅ **高质量需求**: 支持 8K/4K/Hi-Res 等最高质量

### ⚠️ 当前限制
- ❌ **弹幕/字幕需求**: 尚未实现，建议等待更新或使用 yutto
- ❌ **批量下载**: 暂不支持，需要循环调用
- ❌ **登录限制视频**: 无法访问需要登录的高清画质

## 🔧 开发状态

### 当前版本：v0.65.0 (65% 功能完成)

**✅ 已完成**:
- 核心下载引擎 (100%)
- Web UI 界面 (100%)
- CLI 命令行工具 (100%)
- API 架构设计 (100%)
- 多流进度管理 (100%)
- 登录验证和会员状态显示 (100%)

**🔄 开发中**:
- 封面下载 (计划 v0.7.0)
- 弹幕下载 (计划 v0.8.0)

## 📁 项目结构

```