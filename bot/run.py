#!/usr/bin/env python3
"""
机器人启动脚本
"""

import asyncio
import sys
from pathlib import Path

# 添加父目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.bot import main

if __name__ == "__main__":
    asyncio.run(main())
