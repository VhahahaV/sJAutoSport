#!/usr/bin/env python3
"""
使用 order 模块进行定时预订的包装脚本
"""

import subprocess
import sys
from datetime import datetime, timedelta

def schedule_order(preset, hour, minute, start_hour, date_offset=1):
    """使用 order 模块进行预订"""
    
    # 计算目标日期
    target_date = datetime.now() + timedelta(days=date_offset)
    date_str = target_date.strftime("%Y-%m-%d")
    
    # 构建命令
    cmd = [
        "python", "main.py", "order",
        "--preset", str(preset),
        "--date", date_str,
        "--start-time", str(start_hour)
    ]
    
    print(f"执行预订命令: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print("预订成功:")
        print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print("预订失败:")
        print(e.stderr)
        return False

if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("用法: python schedule_order.py <preset> <hour> <minute> <start_hour> [date_offset]")
        print("示例: python schedule_order.py 13 21 47 17 1")
        sys.exit(1)
    
    preset = int(sys.argv[1])
    hour = int(sys.argv[2])
    minute = int(sys.argv[3])
    start_hour = int(sys.argv[4])
    date_offset = int(sys.argv[5]) if len(sys.argv) > 5 else 1
    
    print(f"预设: {preset}, 执行时间: {hour}:{minute:02d}, 预订时间: {start_hour}:00, 日期偏移: {date_offset}")
    
    # 立即执行预订
    success = schedule_order(preset, hour, minute, start_hour, date_offset)
    sys.exit(0 if success else 1)
