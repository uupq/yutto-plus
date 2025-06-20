"""
简化版日志模块
"""

import sys
from datetime import datetime
from typing import Literal

LogLevel = Literal["INFO", "WARNING", "ERROR", "DEBUG"]


class Logger:
    """简化版日志器"""
    
    @staticmethod
    def _format_message(level: LogLevel, message: str) -> str:
        """格式化日志消息"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        colors = {
            "INFO": "\033[92m",     # 绿色
            "WARNING": "\033[93m",  # 黄色
            "ERROR": "\033[91m",    # 红色
            "DEBUG": "\033[94m",    # 蓝色
        }
        reset = "\033[0m"
        
        color = colors.get(level, "")
        return f"[{timestamp}] {color}{level}{reset}: {message}"
    
    @staticmethod
    def info(message: str):
        """输出信息日志"""
        print(Logger._format_message("INFO", message))
    
    @staticmethod
    def warning(message: str):
        """输出警告日志"""
        print(Logger._format_message("WARNING", message))
    
    @staticmethod
    def error(message: str):
        """输出错误日志"""
        print(Logger._format_message("ERROR", message), file=sys.stderr)
    
    @staticmethod
    def debug(message: str):
        """输出调试日志"""
        print(Logger._format_message("DEBUG", message))
    
    @staticmethod
    def custom(title: str, badge: str):
        """输出自定义格式的日志"""
        print(f"[{badge}] {title}") 