#!/usr/bin/env python3
"""
配置文件管理器 - 支持JSON和YAML配置文件
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional


class ConfigManager:
    """配置文件管理器"""
    
    def __init__(self):
        self.default_config = {
            # 基础设置
            "quality": 80,
            "audio_quality": 30280,
            "output_dir": "./Downloads",
            "format": "mp4",
            "overwrite": False,
            "enable_resume": True,
            
            # 并行设置
            "concurrent": 1,
            "parallel_display": "table",
            
            # 资源选择
            "audio_only": False,
            "no_video": False,
            "no_danmaku": False,
            "no_cover": False,
            
            # 格式设置
            "danmaku_format": "ass",
            "audio_format": "mp3",
            "audio_bitrate": "192k",
            "video_codec": "avc",
            
            # 输出控制
            "quiet": False,
            "verbose": False,
            
            # 登录凭证
            "sessdata": None,

            # 严格验证设置
            "vip_strict": False,
            "login_strict": False
        }
    
    def load_config(self, config_path: str) -> Dict[str, Any]:
        """加载配置文件"""
        config_file = Path(config_path)
        
        if not config_file.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        
        # 根据文件扩展名选择解析方式
        if config_file.suffix.lower() == '.json':
            return self._load_json_config(config_file)
        elif config_file.suffix.lower() in ['.yaml', '.yml']:
            return self._load_yaml_config(config_file)
        else:
            # 尝试JSON格式
            return self._load_json_config(config_file)
    
    def _load_json_config(self, config_file: Path) -> Dict[str, Any]:
        """加载JSON配置文件"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
            return self._merge_config(config)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON配置文件格式错误: {e}")
        except Exception as e:
            raise ValueError(f"读取配置文件失败: {e}")
    
    def _load_yaml_config(self, config_file: Path) -> Dict[str, Any]:
        """加载YAML配置文件"""
        try:
            import yaml
            with open(config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            return self._merge_config(config)
        except ImportError:
            raise ValueError("需要安装PyYAML库来支持YAML配置文件: pip install PyYAML")
        except Exception as e:
            raise ValueError(f"读取YAML配置文件失败: {e}")
    
    def _merge_config(self, user_config: Dict[str, Any]) -> Dict[str, Any]:
        """合并用户配置和默认配置"""
        merged = self.default_config.copy()
        
        # 递归合并配置
        for key, value in user_config.items():
            if key in merged:
                merged[key] = value
            else:
                print(f"⚠️  未知配置项: {key}")
        
        return merged
    
    def create_sample_config(self, config_path: str, style: str = "default"):
        """创建示例配置文件"""
        config_file = Path(config_path)
        
        if style == "high_quality":
            sample_config = {
                "description": "高清视频下载配置",
                "quality": 127,
                "audio_quality": 30251,
                "format": "mkv",
                "video_codec": "hevc",
                "concurrent": 2,
                "no_danmaku": True,
                "no_cover": True,
                "output_dir": "./HighQuality_Downloads"
            }
        elif style == "audio_only":
            sample_config = {
                "description": "仅音频下载配置（播客/音乐）",
                "audio_only": True,
                "audio_format": "mp3",
                "audio_bitrate": "320k",
                "audio_quality": 30280,
                "no_video": True,
                "no_danmaku": True,
                "no_cover": False,
                "concurrent": 3,
                "output_dir": "./Audio_Downloads"
            }
        elif style == "batch_download":
            sample_config = {
                "description": "批量下载配置（速度优先）",
                "quality": 64,
                "audio_quality": 30232,
                "concurrent": 4,
                "parallel_display": "simple",
                "no_danmaku": True,
                "no_cover": True,
                "overwrite": False,
                "enable_resume": True,
                "output_dir": "./Batch_Downloads"
            }
        else:  # default
            sample_config = {
                "description": "默认下载配置",
                "quality": 80,
                "audio_quality": 30280,
                "format": "mp4",
                "concurrent": 1,
                "parallel_display": "table",
                "danmaku_format": "ass",
                "output_dir": "./Downloads"
            }
        
        # 写入文件
        if config_file.suffix.lower() == '.json':
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(sample_config, f, indent=2, ensure_ascii=False)
        else:
            # 默认使用JSON格式
            with open(config_file.with_suffix('.json'), 'w', encoding='utf-8') as f:
                json.dump(sample_config, f, indent=2, ensure_ascii=False)
        
        print(f"✅ 示例配置文件已创建: {config_file}")
    
    def validate_config(self, config: Dict[str, Any]) -> bool:
        """验证配置的有效性"""
        try:
            # 验证质量参数
            if config.get("quality") not in [16, 32, 64, 74, 80, 100, 112, 116, 120, 125, 126, 127]:
                print(f"⚠️  无效的视频质量: {config.get('quality')}")
                return False
            
            # 验证音频质量
            if config.get("audio_quality") not in [30216, 30232, 30280, 30251]:
                print(f"⚠️  无效的音频质量: {config.get('audio_quality')}")
                return False
            
            # 验证并发数
            if config.get("concurrent", 1) < 1 or config.get("concurrent", 1) > 10:
                print(f"⚠️  并发数应该在1-10之间: {config.get('concurrent')}")
                return False
            
            # 验证输出目录
            output_dir = config.get("output_dir", "./Downloads")
            try:
                Path(output_dir).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                print(f"⚠️  无效的输出目录: {output_dir} - {e}")
                return False
            
            return True
        except Exception as e:
            print(f"⚠️  配置验证失败: {e}")
            return False
    
    def list_builtin_configs(self) -> Dict[str, str]:
        """列出内置配置模板"""
        return {
            "default": "默认下载配置",
            "high_quality": "高清视频下载配置（8K/4K优先）",
            "audio_only": "仅音频下载配置（播客/音乐）", 
            "batch_download": "批量下载配置（速度优先）"
        }


def create_config_command():
    """配置文件创建命令行工具"""
    import argparse
    
    parser = argparse.ArgumentParser(description="yutto-plus 配置文件管理工具")
    subparsers = parser.add_subparsers(dest='action', help='操作类型')
    
    # 创建配置文件
    create_parser = subparsers.add_parser('create', help='创建示例配置文件')
    create_parser.add_argument('--style', choices=['default', 'high_quality', 'audio_only', 'batch_download'], 
                              default='default', help='配置文件风格')
    create_parser.add_argument('--output', default='yutto-plus.json', help='配置文件路径')
    
    # 列出模板
    list_parser = subparsers.add_parser('list', help='列出可用的配置模板')
    
    # 验证配置文件
    validate_parser = subparsers.add_parser('validate', help='验证配置文件')
    validate_parser.add_argument('config_file', help='配置文件路径')
    
    args = parser.parse_args()
    manager = ConfigManager()
    
    if args.action == 'create':
        manager.create_sample_config(args.output, args.style)
    elif args.action == 'list':
        print("📋 可用的配置模板:")
        for style, desc in manager.list_builtin_configs().items():
            print(f"  {style}: {desc}")
    elif args.action == 'validate':
        try:
            config = manager.load_config(args.config_file)
            if manager.validate_config(config):
                print(f"✅ 配置文件有效: {args.config_file}")
            else:
                print(f"❌ 配置文件无效: {args.config_file}")
        except Exception as e:
            print(f"❌ 配置文件错误: {e}")
    else:
        parser.print_help()


if __name__ == "__main__":
    create_config_command() 