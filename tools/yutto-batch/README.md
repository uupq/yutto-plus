# Yutto-Batch

精简版B站批量下载工具，专注于批量下载功能和断点续传。调用原版yutto进行实际下载，提供完善的批量管理和状态跟踪。

## 核心功能特性

### 📺 全面的URL支持
- **投稿视频全集** - 支持多P视频批量下载
- **番剧/电影全集** - 支持番剧和电影的所有集数
- **课程全集** - 支持B站课程的完整下载
- **用户收藏夹** - 支持单个或全部收藏夹
- **视频列表/合集** - 支持视频列表和合集
- **个人空间视频** - 支持UP主所有投稿视频
- **稍后再看** - 支持稍后再看列表

### 🔄 智能断点续传
- **CSV状态管理** - 自动生成和管理下载状态文件
- **中断恢复** - 支持下载中断后继续未完成的任务
- **增量更新** - 自动检测新增视频并只下载新内容
- **状态跟踪** - 实时更新每个视频的下载状态

### 🗂️ 完善的文件管理
- **智能目录** - 根据任务名称自动创建目录结构
- **文件清理** - 下载前自动清理已存在的不完整文件
- **编码兼容** - CSV文件同时支持Excel和VSCode正确显示中文

### 📊 详细的进度信息
- **实时输出** - 显示yutto的完整下载进度
- **统计信息** - 显示总数、已完成、待下载的统计
- **日期格式** - 视频发布时间显示为可读格式

## 安装和配置

### 前置要求
```bash
# 确保已安装原版yutto
pip install yutto

# 安装依赖
pip install -r requirements.txt
```

### 项目结构
```
yutto-batch/
├── main.py              # 主入口程序
├── batch_downloader.py  # 批量下载器
├── extractors.py        # URL提取器
├── api/
│   └── bilibili.py      # B站API接口
├── utils/
│   ├── csv_manager.py   # CSV状态管理
│   ├── logger.py        # 日志系统
│   ├── types.py         # 类型定义
│   └── fetcher.py       # HTTP请求
└── requirements.txt     # 依赖列表
```

## 使用方法

### 基本语法
```bash
python main.py <URL> [选项]
```

### 命令行参数
- `-c, --cookie COOKIE` - B站登录Cookie (SESSDATA)
- `-o, --output DIR` - 输出目录 (默认: ./downloads)
- `--debug` - 启用调试模式
- 其他yutto参数 - 会直接传递给yutto命令

### 使用示例

#### 1. 下载投稿视频全集
```bash
python main.py "https://www.bilibili.com/video/BV1xx411c7mD" -o "/path/to/downloads"
```

#### 2. 下载番剧全集（需要Cookie）
```bash
python main.py "https://www.bilibili.com/bangumi/play/ss12345" \
  -c "your_sessdata_cookie" \
  -o "/path/to/downloads"
```

#### 3. 下载收藏夹
```bash
python main.py "https://space.bilibili.com/123456/favlist?fid=789012&ftype=create" \
  -c "your_sessdata_cookie" \
  -o "/path/to/downloads"
```

#### 4. 下载个人空间所有视频
```bash
python main.py "https://space.bilibili.com/123456" \
  -c "your_sessdata_cookie" \
  -o "/path/to/downloads"
```

#### 5. 带调试信息下载
```bash
python main.py "https://www.bilibili.com/video/BV1xx411c7mD" \
  -o "/path/to/downloads" \
  --debug
```

## 断点续传机制

### 工作原理
1. **首次下载** - 创建以任务名称命名的文件夹和CSV状态文件
2. **状态跟踪** - 每完成一个视频下载，立即更新CSV文件
3. **中断恢复** - 重新运行相同命令时，自动从CSV加载未完成的任务
4. **增量更新** - 检测到新增视频时，只下载新的内容

### CSV文件格式
CSV文件保存在任务目录下，格式为 `YY-MM-DD-HH-MM.csv`：

```csv
# Original URL: https://space.bilibili.com/123456/favlist?fid=789012
video_url,title,name,download_path,downloaded,avid,cid,pubdate
https://www.bilibili.com/video/BV1xx411c7mD,视频标题,分P名称,路径,True,BV1xx411c7mD,123456,2024-01-01 12:00:00
```

### 字段说明
- `video_url` - 视频链接
- `title` - 视频标题
- `name` - 分P名称
- `download_path` - 下载路径
- `downloaded` - 是否已下载 (True/False)
- `avid` - 视频ID
- `cid` - 分P ID
- `pubdate` - 发布时间 (可读格式)

## 目录结构示例

下载完成后的目录结构：
```
/path/to/downloads/
└── 收藏夹-声音/                    # 任务目录
    ├── 25-01-15-14-30.csv         # 状态文件
    ├── 视频标题1/                  # 视频文件夹
    │   ├── 视频标题1.mp4
    │   ├── 视频标题1.ass
    │   └── 视频标题1_中文.srt
    └── 视频标题2/
        ├── 视频标题2.mp4
        └── ...
```

## 注意事项和最佳实践

### Cookie获取
1. 登录B站后按F12打开开发者工具
2. 切换到Network标签
3. 刷新页面，找到任意请求
4. 在Request Headers中找到Cookie字段
5. 复制SESSDATA对应的值

### 使用建议
- **大批量下载**：建议分批下载，避免单次任务过大
- **存储空间**：确保有足够的磁盘空间
- **网络稳定**：下载过程中保持网络连接稳定
- **定期清理**：完成下载后可删除CSV文件节省空间

### 常见问题
- **权限问题**：某些视频需要登录Cookie才能下载
- **地区限制**：部分内容可能有地区访问限制
- **网络超时**：网络不稳定时可重新运行继续下载
- **文件占用**：Windows下可能遇到文件被占用，重启后重试

## 开发说明

本工具基于原版yutto开发，采用分工合作的架构：
- **yutto-batch** - 负责批量URL解析和下载管理
- **原版yutto** - 负责实际的视频下载和转换

这种设计确保了：
- 下载质量和稳定性（使用成熟的yutto）
- 批量管理的便利性（专门的批量工具）
- 功能的可扩展性（独立的模块设计） 