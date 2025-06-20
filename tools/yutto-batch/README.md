# Yutto-Batch

精简版B站批量下载工具，专注于批量下载功能。

## 功能特性

- 支持所有yutto-b支持的URL类型：
  - 投稿视频全集
  - 番剧全集  
  - 课程全集
  - 用户收藏夹
  - 视频列表/合集
  - 个人空间视频
  - 稍后再看

## 使用方法

```bash
python main.py <url>
```

## 示例

```bash
# 下载投稿视频所有分P
python main.py "https://www.bilibili.com/video/BV1xx411c7mD"

# 下载番剧全集
python main.py "https://www.bilibili.com/bangumi/play/ss12345"

# 下载收藏夹
python main.py "https://space.bilibili.com/123456/favlist?fid=789012"

# 下载个人空间所有视频
python main.py "https://space.bilibili.com/123456"
``` 