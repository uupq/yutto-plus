# YuttoDownloader - yutto B站下载工具高级封装

基于 [yutto](https://yutto.nyakku.moe/) B站视频下载工具的高级 Python 封装，提供更灵活、更易于程序化控制的下载体验。

## 特性

- 🎯 **配置持久化与覆盖**: 通过类实例存储默认配置，单次下载时灵活覆盖
- 🔄 **任务对象化与并发**: 每个下载是独立对象，支持并发下载
- 📊 **实时进度回调**: 提供下载进度、速度等实时信息
- 🎬 **流信息提取**: 自动解析并返回实际下载的视频、音频流信息
- 🔧 **灵活的错误处理**: 完善的异常处理和错误信息反馈
- 🎛️ **完整参数支持**: 支持 yutto 的所有主要命令行参数

## 系统要求

- Python 3.7+
- 已安装 `yutto` 包: `pip install yutto`
- 支持 macOS、Linux、Windows

## 快速开始

### 基本用法

```python
from yutto_downloader import YuttoDownloader

# 创建下载器实例
downloader = YuttoDownloader(
    default_output_dir="~/Downloads/Bilibili",
    default_quality=80,  # 1080P
    default_save_cover=True
)

# 创建下载任务
task = downloader.create_download_task(
    "https://www.bilibili.com/video/BV1LWjXzvEX1/"
)

# 启动下载
task.start()

# 等待完成
while task.get_status().value in ['pending', 'downloading', 'merging']:
    time.sleep(1)

print(f"下载状态: {task.get_status().value}")
```

### 带回调函数的用法

```python
def progress_callback(current_bytes, total_bytes, speed_bps, item_name):
    """进度回调函数"""
    percent = (current_bytes / total_bytes * 100) if total_bytes > 0 else 0
    speed_mb = speed_bps / (1024 * 1024)
    print(f"进度: {percent:.1f}% | 速度: {speed_mb:.2f} MB/s | 项目: {item_name}")

def completion_callback(success, result_info, error_message):
    """完成回调函数"""
    if success:
        print("下载完成!")
        print("视频流:", result_info.get('selected_video_stream_info'))
        print("音频流:", result_info.get('selected_audio_stream_info'))
    else:
        print(f"下载失败: {error_message}")

# 启动带回调的下载
task.start(
    progress_callback=progress_callback,
    completion_callback=completion_callback
)
```

## API 参考

### YuttoDownloader 类

主要的下载器类，用于管理默认配置和创建下载任务。

#### 构造函数

```python
YuttoDownloader(
    sessdata=None,                              # B站登录凭证
    default_output_dir=None,                    # 默认下载目录
    default_quality=80,                         # 默认视频质量
    default_audio_quality=30280,                # 默认音频质量
    default_video_codec="avc:avc",              # 默认视频编码
    default_audio_codec="mp4a:mp4a",            # 默认音频编码
    default_download_vcodec_priority=None,      # 视频编码优先级
    default_output_format="mp4",                # 默认输出格式
    default_output_format_audio_only="m4a",    # 仅音频输出格式
    default_proxy=None,                         # 默认代理设置
    default_num_workers=8,                      # 默认并发数
    default_block_size=0.5,                     # 默认分块大小(MiB)
    default_overwrite=False,                    # 默认是否覆盖
    default_danmaku_format="ass",               # 默认弹幕格式
    default_save_cover=True,                    # 默认是否保存封面
    **kwargs                                    # 其他参数
)
```

#### 方法

##### create_download_task(url, **kwargs)

创建下载任务。

**参数:**
- `url` (str): B站视频链接
- `**kwargs`: 覆盖默认配置的参数

**返回:**
- `DownloadTask`: 下载任务对象

### DownloadTask 类

单个下载任务类，代表一个独立的下载操作。

#### 方法

##### start(progress_callback=None, completion_callback=None)

启动下载任务。

**参数:**
- `progress_callback` (callable, optional): 进度回调函数
  - 签名: `(current_bytes: int, total_bytes: int, speed_bps: float, item_name: str) -> None`
- `completion_callback` (callable, optional): 完成回调函数
  - 签名: `(success: bool, result_info: dict, error_message: str) -> None`

##### get_status()

获取当前任务状态。

**返回:**
- `TaskStatus`: 任务状态枚举值

##### get_selected_streams_info()

获取实际选择的流信息。

**返回:**
- `dict`: 包含选择的视频和音频流信息

### TaskStatus 枚举

任务状态枚举:
- `PENDING`: 等待中
- `DOWNLOADING`: 下载中
- `MERGING`: 合并中
- `COMPLETED`: 已完成
- `FAILED`: 失败

## 支持的视频质量

| 质量代码 | 描述 |
|---------|------|
| 127 | 8K |
| 126 | Dolby Vision |
| 125 | HDR |
| 120 | 4K |
| 116 | 1080P60 |
| 112 | 1080P+ |
| 100 | 智能修复 |
| 80 | 1080P |
| 74 | 720P60 |
| 64 | 720P |
| 32 | 480P |
| 16 | 360P |

## 支持的音频质量

| 质量代码 | 描述 |
|---------|------|
| 30251 | Hi-Res |
| 30255 | Dolby Audio |
| 30250 | Dolby Atmos |
| 30280 | 320kbps |
| 30232 | 128kbps |
| 30216 | 64kbps |

## 高级用法

### 并发下载多个视频

```python
from yutto_downloader import YuttoDownloader, TaskStatus
import time

downloader = YuttoDownloader(
    default_output_dir="~/Downloads/Bilibili",
    default_quality=64  # 720P
)

urls = [
    "https://www.bilibili.com/video/BV1234567890/",
    "https://www.bilibili.com/video/BV0987654321/",
]

tasks = []

# 创建并启动多个任务
for i, url in enumerate(urls):
    task = downloader.create_download_task(
        url,
        output_dir=f"~/Downloads/Bilibili/video_{i+1}"
    )
    
    def make_callback(task_id):
        def callback(success, result_info, error_message):
            if success:
                print(f"任务{task_id} 完成!")
            else:
                print(f"任务{task_id} 失败: {error_message}")
        return callback
    
    task.start(completion_callback=make_callback(i+1))
    tasks.append(task)

# 等待所有任务完成
while any(task.get_status() in [TaskStatus.PENDING, TaskStatus.DOWNLOADING, TaskStatus.MERGING] 
          for task in tasks):
    time.sleep(2)

print("所有下载完成!")
```

### 使用 SESSDATA 下载高清视频

```python
downloader = YuttoDownloader(
    sessdata="your_sessdata_here",  # 从浏览器获取
    default_quality=120,  # 4K
    default_output_dir="~/Downloads/Bilibili"
)

task = downloader.create_download_task(
    "https://www.bilibili.com/video/BV1234567890/"
)

task.start()
```

### 自定义编码和格式

```python
downloader = YuttoDownloader(
    default_video_codec="hevc:hevc",  # 使用 HEVC 编码
    default_audio_codec="mp4a:aac",   # 音频转换为 AAC
    default_output_format="mkv",      # 输出 MKV 格式
    default_download_vcodec_priority=["hevc", "avc", "av1"]
)
```

## 错误处理

```python
def completion_callback(success, result_info, error_message):
    if not success:
        if "进程退出码" in error_message:
            print("yutto 执行失败，检查 URL 或网络连接")
        elif "权限" in error_message:
            print("文件权限错误，检查输出目录权限")
        else:
            print(f"未知错误: {error_message}")

task.start(completion_callback=completion_callback)
```

## 注意事项

1. **网络环境**: 确保网络连接稳定，某些视频可能需要代理
2. **登录状态**: 下载高清视频需要提供有效的 SESSDATA
3. **存储空间**: 确保有足够的磁盘空间，特别是下载 4K/8K 视频时
4. **并发控制**: 避免同时启动过多下载任务，以免影响性能
5. **版权尊重**: 请仅下载您有权访问的内容，遵守相关法律法规

## 故障排除

### 常见问题

**Q: 下载失败，提示网络错误**
A: 检查网络连接，尝试设置代理参数

**Q: 无法下载高清视频**
A: 需要提供有效的 SESSDATA，且账户需要相应权限

**Q: 下载速度慢**
A: 可以调整 `num_workers` 参数增加并发数，或使用代理

**Q: 文件保存失败**
A: 检查输出目录是否存在且有写入权限

## 许可证

本项目基于 MIT 许可证开源。请查看 LICENSE 文件了解详情。

## 贡献

欢迎提交 Issue 和 Pull Request 来改进这个项目！

## 致谢

感谢 [yutto](https://github.com/yutto-dev/yutto) 项目提供的优秀命令行工具。 