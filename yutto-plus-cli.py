#!/usr/bin/env python3
"""
YuttoPlus CLI 入口脚本
"""

import sys
from pathlib import Path

# 添加src目录到Python路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from yutto_plus.cli import main

if __name__ == "__main__":
    main() 