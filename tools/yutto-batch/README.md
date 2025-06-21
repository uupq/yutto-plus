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
- **智能合并** - 重复下载同一URL时自动合并到现有任务

### 🔄 批量更新系统
- **全局扫描** - 一键更新输出目录下所有下载任务
- **URL识别** - 自动从CSV文件中提取原始下载链接
- **增量同步** - 只下载新增的视频内容，保持已完成状态
- **并行处理** - 支持同时更新多个任务

### 🗂️ 完善的文件管理
- **智能目录** - 根据任务名称自动创建目录结构
- **文件清理** - 下载前自动清理已存在的不完整文件
- **编码兼容** - CSV文件同时支持Excel和VSCode正确显示中文
- **安全操作** - 使用临时文件确保CSV数据完整性

### 📊 详细的进度信息
- **实时输出** - 显示yutto的完整下载进度
- **统计信息** - 显示总数、已完成、待下载的统计
- **日期格式** - 视频发布时间显示为可读格式
- **VIP支持** - 支持严格VIP模式和高质量下载

## 安装和配置

### 前置要求
```bash
# 确保已安装原版yutto
pip install yutto

# 安装依赖
pip install -r requirements.txt
```

### 配置文件系统

支持YAML格式的配置文件，位于`config/`目录：

- `default.yaml` - 默认配置（不可删除，仅可修改）
- `vip.yaml` - VIP会员配置示例
- 可创建自定义配置文件

#### 配置文件格式
```yaml
name: "配置名称"
description: "配置描述"
output_dir: "~/Downloads"
sessdata: "your_sessdata_here"
vip_strict: true
debug: false
extra_args:
  - "--quality"
  - "8K"
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
- `-o, --output DIR` - 输出目录 (默认: ~/Downloads)
- `--config NAME` - 使用指定的配置文件 (不含.yaml扩展名)
- `--update` - 更新模式：扫描输出目录下所有任务并检查更新
- `--vip-strict` - 启用严格VIP模式（传递给yutto）
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

#### 6. 批量更新所有任务
```bash
python main.py --update -c "your_sessdata_cookie" -o "/path/to/downloads"
```

#### 7. 使用VIP严格模式
```bash
python main.py "https://www.bilibili.com/video/BV1xx411c7mD" \
  -c "your_sessdata_cookie" \
  --vip-strict
```

#### 8. 使用配置文件
```bash
# 使用默认配置
python main.py "https://www.bilibili.com/video/BV1xx411c7mD" --config default

# 使用VIP配置
python main.py "https://www.bilibili.com/video/BV1xx411c7mD" --config vip

# 使用自定义配置
python main.py "https://www.bilibili.com/video/BV1xx411c7mD" --config my_config
```

## 断点续传机制

### 工作原理
1. **首次下载** - 创建以任务名称命名的文件夹和CSV状态文件
2. **状态跟踪** - 每完成一个视频下载，立即更新CSV文件
3. **中断恢复** - 重新运行相同命令时，自动从CSV加载未完成的任务
4. **增量更新** - 检测到新增视频时，只下载新的内容

## 批量更新功能

### 工作原理
使用`--update`参数可以一次性更新所有下载任务：

1. **自动扫描** - 扫描输出目录下的所有一级子目录
2. **识别任务** - 通过CSV文件识别已存在的下载任务  
3. **提取URL** - 从CSV文件第一行读取原始下载URL
4. **批量更新** - 对每个任务执行完整的更新检查流程
5. **增量下载** - 只下载新增的视频内容

### 使用场景
- **定期更新** - 定期检查收藏夹、个人空间等是否有新增视频
- **批量维护** - 一次性更新所有下载任务，无需逐个检查
- **自动化** - 可以配合定时任务实现自动更新

### 注意事项
- 确保CSV文件完整且包含原始URL信息
- 更新过程中保持网络连接稳定
- 大量任务更新时建议在网络空闲时进行

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
- **定期更新**：使用`--update`功能定期检查新增内容
- **VIP内容**：付费内容使用`--vip-strict`确保最佳体验
- **数据备份**：CSV文件包含重要状态信息，建议定期备份

### 常见问题
- **权限问题**：某些视频需要登录Cookie才能下载
- **地区限制**：部分内容可能有地区访问限制
- **网络超时**：网络不稳定时可重新运行继续下载
- **文件占用**：Windows下可能遇到文件被占用，重启后重试

## 版本更新记录

### 最新功能
- ✅ **批量更新系统** - 一键更新所有下载任务
- ✅ **VIP严格模式** - 支持高质量VIP内容下载  
- ✅ **智能CSV管理** - 安全的状态文件操作和合并
- ✅ **增量同步** - 自动检测并下载新增视频
- ✅ **Excel兼容** - CSV文件支持Excel正确显示中文

## 开发说明

本工具基于原版yutto开发，采用分工合作的架构：
- **yutto-batch** - 负责批量URL解析、任务管理和状态跟踪
- **原版yutto** - 负责实际的视频下载、转换和合并

### 架构优势
- **下载质量** - 使用成熟稳定的yutto引擎
- **批量管理** - 专门的批量处理和状态管理
- **扩展性** - 模块化设计便于功能扩展
- **兼容性** - 支持所有yutto原生参数
- **可靠性** - 完善的错误处理和数据保护 