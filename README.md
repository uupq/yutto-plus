# YuttoPlus v2.0

🚀 现代化B站视频下载器，支持并行下载和Web界面

## ✨ 特性

- 🔥 **并行下载**: 支持多任务并发下载，大幅提升下载效率
- 🌐 **Web界面**: 现代化的Web UI，支持实时进度监控
- ⚙️ **配置文件**: 支持YAML配置文件，预设多种下载场景
- 📊 **智能对齐**: 完美支持中英文混合的CLI表格显示
- 🔄 **断点续传**: 支持下载中断后从断点继续
- 🎯 **多格式支持**: 支持多种视频、音频格式和质量选择

## 📁 项目结构

```
bili-upper/
├── src/yutto_plus/          # 核心包
│   ├── __init__.py          # 包初始化
│   ├── core.py              # 核心下载逻辑
│   ├── config.py            # 配置管理
│   └── cli.py               # CLI模块
├── webui/                   # Web界面
│   ├── app.py               # Flask应用
│   └── templates/           # HTML模板
├── configs/                 # 配置文件
│   ├── yutto-default.yaml   # 默认配置
│   ├── yutto-high-quality.yaml  # 高清配置
│   └── ...                  # 其他预设配置
├── docs/                    # 文档
├── yutto-plus-cli.py        # CLI入口脚本
├── setup.py                 # 安装配置
└── requirements.txt         # 依赖列表
```

## 🚀 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### CLI使用

```bash
# 单个视频下载
python yutto-plus-cli.py "https://www.bilibili.com/video/BV1234567890/"

# 并行下载多个视频
python yutto-plus-cli.py -c 3 "url1" "url2" "url3"

# 使用配置文件
python yutto-plus-cli.py --config configs/yutto-high-quality.yaml "url1"
```

### Web界面

```bash
# 启动Web界面
python webui/app.py

# 浏览器访问 http://localhost:12001
```

## 📖 详细文档

- [功能文档](docs/FEATURE_DOCUMENTATION.md)
- [配置指南](docs/CONFIG_GUIDE.md)
- [并行下载设计](docs/PARALLEL_DOWNLOAD_DESIGN.md)

## 🛠️ 开发

### 包安装

```bash
# 开发模式安装
pip install -e .

# 安装Web界面依赖
pip install -e .[webui]
```

### 使用包

```python
from yutto_plus import YuttoPlus

# 创建下载器
downloader = YuttoPlus(max_concurrent=3)

# 添加任务
task_ids = downloader.add_download_tasks([
    ("https://www.bilibili.com/video/BV1234567890/", {}),
    ("https://www.bilibili.com/video/BV0987654321/", {})
])

# 开始下载
downloader.start_parallel_download()
downloader.wait_for_completion()
```

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交Issue和Pull Request！ 