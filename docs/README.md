# YuttoPlus - 现代化B站视频下载器

基于纯 HTTP API 实现的现代化 B站视频下载器，提供多种使用方式。

## ✨ 特性

- 🚀 **纯API实现** - 不依赖外部CLI工具
- 🎯 **多质量支持** - 支持8K/4K/1080P/720P等多种画质
- 🎵 **音频模式** - 支持仅下载音频并转换为MP3/FLAC等格式
- 📝 **弹幕支持** - 支持XML和Protobuf格式弹幕下载
- 🖼️ **封面下载** - 自动下载视频封面
- 🔄 **断点续传** - 支持下载中断后继续
- 👤 **登录支持** - 支持SESSDATA登录下载高清视频
- 🌐 **多接口** - 提供命令行、Web界面、API三种使用方式

## 📂 项目结构

```
bili-upper/
├── yutto_plus.py      # 核心库代码
├── yutto-plus.py      # 命令行接口
├── web_ui.py          # Web界面
├── test_simple.py     # 测试脚本
├── requirements.txt   # 依赖列表
└── README.md         # 说明文档
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 使用方式

#### 方式一：命令行 (推荐)

```bash
# 基础下载
python yutto-plus.py "https://www.bilibili.com/video/BV1Zx411w7Ug"

# 指定质量和输出目录
python yutto-plus.py -q 127 -o "./Downloads" "https://www.bilibili.com/video/BV1Zx411w7Ug"

# 仅下载音频
python yutto-plus.py --audio-only -af mp3 -ab 192k "https://www.bilibili.com/video/BV1Zx411w7Ug"

# 完整参数
python yutto-plus.py -q 80 -o "./Downloads" --sessdata "你的SESSDATA" "https://www.bilibili.com/video/BV1Zx411w7Ug"
```

#### 方式二：Web界面

```bash
python web_ui.py
# 然后访问 http://localhost:8501
```

#### 方式三：Python API

```python
from yutto_plus import YuttoPlus

# 创建下载器
downloader = YuttoPlus(
    sessdata="你的SESSDATA",  # 可选
    default_output_dir="./downloads"
)

# 创建下载任务
task = downloader.create_download_task(
    "https://www.bilibili.com/video/BV1Zx411w7Ug",
    quality=80,
    audio_only=False,
    require_danmaku=True,
    require_cover=True
)

# 开始下载
task.start(
    progress_callback=lambda c, t, s, n: print(f"进度: {c/t*100:.1f}%"),
    completion_callback=lambda success, info, err: print("完成!" if success else f"失败: {err}")
)
```

## 📋 命令行参数

### 基础参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-q, --quality` | 视频质量 (16/32/64/80/112/116/120/127) | 80 |
| `-aq, --audio-quality` | 音频质量 (30216/30232/30280/30251) | 30280 |
| `-o, --output` | 输出目录 | ./Downloads |
| `-f, --format` | 输出格式 (mp4/mkv/mov) | mp4 |
| `--sessdata` | B站登录凭证 | - |

### 资源选择

| 参数 | 说明 |
|------|------|
| `--audio-only` | 仅下载音频 |
| `--no-video` | 不下载视频 |
| `--no-danmaku` | 不下载弹幕 |
| `--no-cover` | 不下载封面 |
| `-af, --audio-format` | 音频格式 (mp3/wav/flac/m4a/aac) |
| `-ab, --audio-bitrate` | 音频比特率 (320k/256k/192k/128k/96k) |

### 下载控制

| 参数 | 说明 |
|------|------|
| `-w, --overwrite` | 覆盖已存在文件 |
| `--no-resume` | 禁用断点续传 |
| `--quiet` | 安静模式 |
| `--verbose` | 详细模式 |

## 🎯 画质说明

| 代码 | 画质 | 说明 |
|------|------|------|
| 127 | 8K 超高清 | 需要大会员 |
| 120 | 4K 超清 | 需要大会员 |
| 116 | 1080P60 | 需要大会员 |
| 112 | 1080P+ | 需要大会员 |
| 80 | 1080P 高清 | 推荐 |
| 64 | 720P 高清 | - |
| 32 | 480P 清晰 | - |
| 16 | 360P 流畅 | - |

## 🔧 配置说明

### SESSDATA 获取方法

1. 浏览器登录B站
2. 按F12打开开发者工具
3. 切换到Application/Storage标签
4. 找到Cookies -> https://www.bilibili.com
5. 复制SESSDATA的值

### 断点续传

- 默认启用断点续传功能
- 下载中断后重新运行可从断点继续
- 使用 `--no-resume` 禁用断点续传
- 使用 `-w/--overwrite` 覆盖现有文件

## 🧪 测试

```bash
# 运行测试脚本
python test_simple.py
```

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！