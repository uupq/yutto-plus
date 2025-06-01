# 多P视频下载功能指南

## 🎯 功能概述

yutto-plus 现在支持自动检测和下载B站多P视频！程序会自动识别视频是否为多P，并提供灵活的分P选择和文件组织选项。

## 🔍 自动检测

程序会自动检测视频类型：
- **单P视频**：直接下载到指定目录
- **多P视频**：自动创建以视频标题命名的文件夹，每个分P保存在其中

## 📋 分P选择语法

使用 `-p/--episodes` 参数选择要下载的分P：

### 基本语法
- `1,3,5` - 下载第1、3、5个分P
- `1~3` - 下载第1到第3个分P（范围）
- `~3` - 下载前3个分P（从第1个开始）
- `-2~` - 下载后2个分P（倒数第2个到最后）
- `$` - 下载最后一个分P
- 空值或不指定 - 下载全部分P

### 复合语法
- `1,3,5~8,10` - 下载第1、3、5到8、10个分P
- `~3,10,-2~` - 下载前3个、第10个、后2个分P

## 💡 使用示例

### 基本下载
```bash
# 下载多P视频的全部分P（自动创建文件夹）
python yutto-plus-cli.py "https://www.bilibili.com/video/BV1unjgzqEms"

# 下载多P视频的前3个分P
python yutto-plus-cli.py -p "~3" "https://www.bilibili.com/video/BV1unjgzqEms"

# 下载指定的分P
python yutto-plus-cli.py -p "1,3,5~8" "https://www.bilibili.com/video/BV1unjgzqEms"

# 下载后2个分P
python yutto-plus-cli.py -p "-2~" "https://www.bilibili.com/video/BV1unjgzqEms"
```

### 文件夹控制
```bash
# 不创建文件夹，直接保存到输出目录
python yutto-plus-cli.py --no-folder "https://www.bilibili.com/video/BV1unjgzqEms"

# 指定输出目录并下载选定分P
python yutto-plus-cli.py -o "./Downloads" -p "1~5" "https://www.bilibili.com/video/BV1unjgzqEms"
```

### 结合其他选项
```bash
# 只下载音频，选择前3个分P
python yutto-plus-cli.py --audio-only -af mp3 -p "~3" "https://www.bilibili.com/video/BV1unjgzqEms"

# 高质量下载，选择特定分P
python yutto-plus-cli.py -q 127 -p "1,5,10" "https://www.bilibili.com/video/BV1unjgzqEms"
```

## 📁 文件组织结构

### 多P视频（默认）
```
Downloads/
└── 视频标题/
    ├── P01_第一集标题.mp4
    ├── P02_第二集标题.mp4
    ├── P03_第三集标题.mp4
    ├── P01_第一集标题.xml  # 弹幕文件
    ├── P02_第二集标题.xml
    └── 视频标题_cover.jpg   # 封面（仅第一个分P时下载）
```

### 多P视频（使用 --no-folder）
```
Downloads/
├── P01_第一集标题.mp4
├── P02_第二集标题.mp4
├── P03_第三集标题.mp4
└── ...
```

### 单P视频
```
Downloads/
├── 视频标题.mp4
├── 视频标题.xml
└── 视频标题_cover.jpg
```

## 🎮 测试多P视频URL

以下是一些可用于测试的多P视频URL：

### 多P视频示例
- `https://www.bilibili.com/video/BV1unjgzqEms`
- `https://www.bilibili.com/video/BV1ZB75zeEa5`
- `https://www.bilibili.com/video/BV1RcjSzXE6E`

### 单P视频示例
- `https://www.bilibili.com/video/BV16A7nzXE2b`
- `https://www.bilibili.com/video/BV1Pr7nzoEH6`

## ⚙️ 配置文件支持

可以在配置文件中设置默认的多P视频选项：

```json
{
  "episodes_selection": "~5",
  "create_folder_for_multi_p": true
}
```

## 🔧 高级功能

### 并行下载多P视频
```bash
# 并行下载多个多P视频
python yutto-plus-cli.py -c 2 -p "~3" "url1" "url2" "url3"
```

### 音频模式下载多P
```bash
# 下载多P视频的音频版本
python yutto-plus-cli.py --audio-only -af mp3 -p "1~10" "https://www.bilibili.com/video/BV1unjgzqEms"
```

## 📊 下载结果显示

程序会显示详细的下载统计信息：
- 总分P数量
- 成功下载的分P列表
- 失败的分P列表（如果有）
- 输出目录位置

## 🚨 注意事项

1. **网络稳定性**：多P视频下载时间较长，建议在网络稳定的环境下进行
2. **存储空间**：确保有足够的存储空间，多P视频通常较大
3. **分P编号**：分P编号从1开始，与B站显示的编号一致
4. **错误处理**：如果某个分P下载失败，程序会继续下载其他分P
5. **文件命名**：分P文件名格式为 `P{编号:02d}_{分P标题}.{格式}`

## 🔄 从旧版本升级

如果你之前使用的是不支持多P的版本：
1. 新版本完全向后兼容
2. 单P视频的下载行为保持不变
3. 多P视频会自动使用新的文件夹结构
4. 可以使用 `--no-folder` 参数保持旧的行为

## 🐛 故障排除

如果遇到问题：
1. 检查视频URL是否正确
2. 确认分P选择语法是否正确
3. 检查网络连接和存储空间
4. 查看详细错误信息（使用 `-v` 参数）
