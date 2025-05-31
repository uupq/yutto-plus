# YuttoPlus 配置文件使用指南

## 📋 概述

YuttoPlus 支持使用配置文件来预设下载参数，让您可以为不同的使用场景创建专门的配置，无需每次都输入大量命令行参数。

## 🚀 快速开始

### 1. 查看可用的配置模板
```bash
python yutto-plus.py --list-configs
```

### 2. 创建配置文件
```bash
# 创建默认配置
python yutto-plus.py --create-config default

# 创建高清视频配置
python yutto-plus.py --create-config high_quality

# 创建仅音频配置
python yutto-plus.py --create-config audio_only

# 创建批量下载配置
python yutto-plus.py --create-config batch_download
```

### 3. 使用配置文件下载
```bash
# 使用配置文件
python yutto-plus.py --config yutto-plus-high_quality.json "https://www.bilibili.com/video/BV1234567890"

# 配置文件 + 命令行参数（命令行参数优先）
python yutto-plus.py --config yutto-plus-audio_only.json -c 4 -o "./MyDownloads" "url1" "url2"
```

## 📝 配置模板详解

### 🎯 default - 默认配置
```json
{
  "description": "默认下载配置",
  "quality": 80,
  "audio_quality": 30280,
  "format": "mp4",
  "concurrent": 1,
  "parallel_display": "table",
  "danmaku_format": "ass",
  "output_dir": "./Downloads"
}
```
**适用场景**: 日常下载，平衡质量和速度

### 🎬 high_quality - 高清视频配置
```json
{
  "description": "高清视频下载配置",
  "quality": 127,
  "audio_quality": 30251,
  "format": "mkv",
  "video_codec": "hevc",
  "concurrent": 2,
  "no_danmaku": true,
  "no_cover": true,
  "output_dir": "./HighQuality_Downloads"
}
```
**适用场景**: 下载8K/4K高清视频，收藏精品内容

### 🎵 audio_only - 仅音频配置
```json
{
  "description": "仅音频下载配置（播客/音乐）",
  "audio_only": true,
  "audio_format": "mp3",
  "audio_bitrate": "320k",
  "audio_quality": 30280,
  "no_video": true,
  "no_danmaku": true,
  "no_cover": false,
  "concurrent": 3,
  "output_dir": "./Audio_Downloads"
}
```
**适用场景**: 下载播客、音乐、有声读物等音频内容

### ⚡ batch_download - 批量下载配置
```json
{
  "description": "批量下载配置（速度优先）",
  "quality": 64,
  "audio_quality": 30232,
  "concurrent": 4,
  "parallel_display": "simple",
  "no_danmaku": true,
  "no_cover": true,
  "overwrite": false,
  "enable_resume": true,
  "output_dir": "./Batch_Downloads"
}
```
**适用场景**: 批量下载大量视频，优先速度而非质量

## ⚙️ 配置参数详解

### 基础设置
- `quality`: 视频质量 (16, 32, 64, 80, 112, 116, 120, 127)
- `audio_quality`: 音频质量 (30216, 30232, 30280, 30251)
- `output_dir`: 输出目录
- `format`: 输出格式 (mp4, mkv, mov)
- `overwrite`: 是否覆盖现有文件
- `enable_resume`: 是否启用断点续传

### 并行设置
- `concurrent`: 并发下载数量 (1-10)
- `parallel_display`: 并行显示模式 (table, simple, silent)

### 资源选择
- `audio_only`: 仅下载音频
- `no_video`: 不下载视频
- `no_danmaku`: 不下载弹幕
- `no_cover`: 不下载封面

### 格式设置
- `danmaku_format`: 弹幕格式 (xml, ass, protobuf)
- `audio_format`: 音频格式 (mp3, wav, flac, m4a, aac)
- `audio_bitrate`: 音频比特率 (320k, 256k, 192k, 128k, 96k)
- `video_codec`: 视频编码偏好 (avc, hevc, av1)

### 输出控制
- `quiet`: 安静模式
- `verbose`: 详细模式
- `sessdata`: B站登录凭证

## 🔧 自定义配置

### 创建自定义配置文件

您可以基于现有模板创建自定义配置：

```bash
# 1. 创建基础模板
python yutto-plus.py --create-config default

# 2. 编辑配置文件
vim yutto-plus-default.json

# 3. 自定义配置示例
{
  "description": "我的自定义配置 - 中等质量批量下载",
  "quality": 80,
  "audio_quality": 30280,
  "format": "mp4",
  "concurrent": 3,
  "parallel_display": "table",
  "no_danmaku": true,
  "no_cover": true,
  "output_dir": "./MyVideos",
  "sessdata": "your_sessdata_here"
}
```

### 支持的文件格式

- **JSON格式** (推荐): `my_config.json`
- **YAML格式**: `my_config.yaml` 或 `my_config.yml`

YAML格式示例：
```yaml
description: "YAML格式配置示例"
quality: 80
audio_quality: 30280
format: mp4
concurrent: 2
output_dir: "./Downloads"
no_danmaku: true
```

## 🛠️ 验证配置文件

验证配置文件是否正确：
```bash
python config_manager.py validate my_config.json
```

## 💡 使用技巧

### 1. 配置文件优先级
- 命令行参数 > 配置文件参数 > 默认值
- 可以用配置文件设置基础参数，命令行微调

### 2. 多配置文件管理
```bash
# 为不同用途创建不同配置
python yutto-plus.py --create-config high_quality
mv yutto-plus-high_quality.json configs/movies.json

python yutto-plus.py --create-config audio_only  
mv yutto-plus-audio_only.json configs/podcasts.json

python yutto-plus.py --create-config batch_download
mv yutto-plus-batch_download.json configs/anime.json

# 使用时指定具体配置
python yutto-plus.py --config configs/movies.json "movie_url"
python yutto-plus.py --config configs/podcasts.json "podcast_url"
```

### 3. 环境变量配置
可以在配置文件中设置SESSDATA：
```json
{
  "sessdata": "your_sessdata_here",
  "description": "已登录用户配置"
}
```

## 🔍 故障排除

### 常见问题

1. **配置文件不生效**
   - 检查文件路径是否正确
   - 验证JSON/YAML格式是否正确
   - 使用验证命令检查配置

2. **参数冲突**
   - 命令行参数会覆盖配置文件参数
   - 检查是否有冲突的设置

3. **权限问题**
   - 确保输出目录有写入权限
   - 检查配置文件有读取权限

### 调试方法
```bash
# 使用详细模式查看详细信息
python yutto-plus.py --config my_config.json --verbose "test_url"

# 验证配置文件
python config_manager.py validate my_config.json
```

## 📚 示例场景

### 场景1: 追剧下载
```json
{
  "description": "追剧专用配置",
  "quality": 80,
  "concurrent": 3,
  "format": "mp4",
  "no_danmaku": false,
  "no_cover": true,
  "output_dir": "./Anime",
  "parallel_display": "table"
}
```

### 场景2: 播客收听
```json
{
  "description": "播客下载配置",
  "audio_only": true,
  "audio_format": "mp3",
  "audio_bitrate": "192k",
  "concurrent": 4,
  "no_danmaku": true,
  "no_cover": false,
  "output_dir": "./Podcasts"
}
```

### 场景3: 高质量收藏
```json
{
  "description": "收藏级高质量配置",
  "quality": 127,
  "audio_quality": 30251,
  "format": "mkv",
  "video_codec": "hevc",
  "concurrent": 1,
  "no_danmaku": false,
  "no_cover": false,
  "output_dir": "./Collection"
}
```

---

🎉 现在您已经掌握了YuttoPlus配置文件系统的完整使用方法！根据不同的下载需求创建相应的配置文件，让下载更加高效便捷。 