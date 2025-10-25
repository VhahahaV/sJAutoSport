#!/usr/bin/env python3
"""
集成启动脚本
同时启动后端API和bot机器人，处理端口冲突问题
"""

import asyncio
import subprocess
import sys
import time
import signal
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import config as CFG
from bot.nb_config import load_env

load_env()

BOT_HTTP_SERVER_ENABLED = os.getenv("BOT_HTTP_SERVER_ENABLED", "true").lower() != "false"
BOT_HTTP_SERVER_PORT: Optional[int] = (
    int(os.getenv("BOT_HTTP_SERVER_PORT", "6700")) if BOT_HTTP_SERVER_ENABLED else None
)
BOT_HTTP_SERVER_HOST = os.getenv("BOT_HTTP_SERVER_HOST", "127.0.0.1")
FRONTEND_ENABLED = os.getenv("INTEGRATED_FRONTEND_ENABLED", "true").lower() != "false"
FRONTEND_PORT = int(os.getenv("FRONTEND_PORT", "5173"))


class IntegratedServiceManager:
    """集成服务管理器"""
    
    def __init__(self):
        self.processes: List[subprocess.Popen] = []
        self.running = True
        self._log_threads: Dict[int, threading.Thread] = {}
    
    def _attach_logger(self, process: subprocess.Popen, name: str) -> None:
        if not process.stdout:
            return

        def _reader() -> None:
            try:
                for line in process.stdout:
                    if not line:
                        break
                    print(f"[{name}] {line.rstrip()}", flush=True)
            except Exception as exc:  # pylint: disable=broad-except
                print(f"⚠️ 日志读取失败({name}): {exc}")

        thread = threading.Thread(target=_reader, daemon=True)
        thread.start()
        self._log_threads[process.pid or len(self._log_threads)] = thread
        
    def start_backend_api(self) -> subprocess.Popen:
        """启动后端API服务"""
        print("🚀 启动后端API服务...")
        cmd = [sys.executable, "-m", "web_api.main"]
        process = subprocess.Popen(
            cmd,
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        self._attach_logger(process, "API")
        return process
    
    def start_bot(self) -> subprocess.Popen:
        """启动bot机器人"""
        print("🤖 启动bot机器人...")
        cmd = [sys.executable, "-m", "bot.bot"]
        process = subprocess.Popen(
            cmd,
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        self._attach_logger(process, "Bot")
        return process
    
    def start_frontend(self) -> subprocess.Popen:
        """启动前端开发服务器"""
        print("🌐 启动前端开发服务器...")
        frontend_dir = project_root / "frontend"
        cmd = ["npm", "run", "dev", "--", "--port", str(FRONTEND_PORT)]
        process = subprocess.Popen(
            cmd,
            cwd=frontend_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        self._attach_logger(process, "Frontend")
        return process
    
    def check_port_available(self, port: int) -> bool:
        """检查端口是否可用"""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return True
            except OSError:
                return False
    
    def kill_process_on_port(self, port: int):
        """杀死占用指定端口的进程"""
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True
            )
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    if pid.strip():
                        print(f"🔪 杀死占用端口 {port} 的进程 {pid}")
                        subprocess.run(["kill", "-9", pid.strip()])
                        time.sleep(1)
        except Exception as e:
            print(f"⚠️ 无法杀死端口 {port} 上的进程: {e}")
    
    def start_services(self, include_frontend: bool = True):
        """启动所有服务"""
        print("🎯 启动集成服务...")
        
        # 检查并清理端口
        ports_to_check = [8000]
        if BOT_HTTP_SERVER_ENABLED and BOT_HTTP_SERVER_PORT is not None:
            ports_to_check.append(BOT_HTTP_SERVER_PORT)
        if include_frontend:
            ports_to_check.append(FRONTEND_PORT)
        
        for port in ports_to_check:
            if not self.check_port_available(port):
                print(f"⚠️ 端口 {port} 被占用，尝试清理...")
                self.kill_process_on_port(port)
                time.sleep(2)
        
        # 启动后端API
        try:
            api_process = self.start_backend_api()
            self.processes.append(api_process)
            print("✅ 后端API服务已启动 (端口 8000)")
        except Exception as e:
            print(f"❌ 启动后端API失败: {e}")
            return
        
        # 等待API启动
        print("⏳ 等待API服务启动...")
        time.sleep(3)
        
        # 启动bot
        try:
            bot_process = self.start_bot()
            self.processes.append(bot_process)
            if BOT_HTTP_SERVER_ENABLED and BOT_HTTP_SERVER_PORT is not None:
                print(f"✅ Bot机器人已启动 (端口 {BOT_HTTP_SERVER_PORT})")
            else:
                print("✅ Bot机器人已启动 (HTTP 服务已禁用)")
        except Exception as e:
            print(f"❌ 启动bot失败: {e}")
            return
        
        # 启动前端（可选）
        if include_frontend:
            try:
                frontend_process = self.start_frontend()
                self.processes.append(frontend_process)
                print(f"✅ 前端开发服务器已启动 (端口 {FRONTEND_PORT})")
            except Exception as e:
                print(f"⚠️ 启动前端失败: {e}")
        
        print("\n🎉 所有服务已启动！")
        print("📋 服务地址:")
        print("  - 后端API: http://localhost:8000")
        print("  - API文档: http://localhost:8000/api/docs")
        if BOT_HTTP_SERVER_ENABLED and BOT_HTTP_SERVER_PORT is not None:
            display_host = (
                "localhost"
                if BOT_HTTP_SERVER_HOST in {"0.0.0.0", "127.0.0.1", "localhost"}
                else BOT_HTTP_SERVER_HOST
            )
            print(f"  - Bot HTTP: http://{display_host}:{BOT_HTTP_SERVER_PORT}")
        else:
            print("  - Bot HTTP: （HTTP 服务已禁用）")
        if include_frontend:
            print(f"  - 前端界面: http://localhost:{FRONTEND_PORT}")
        print("\n💡 使用 Ctrl+C 停止所有服务")
    
    def stop_services(self):
        """停止所有服务"""
        print("\n🛑 正在停止所有服务...")
        self.running = False
        
        for process in self.processes:
            try:
                process.terminate()
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            except Exception as e:
                print(f"⚠️ 停止进程失败: {e}")
        
        print("✅ 所有服务已停止")
    
    def monitor_services(self):
        """监控服务状态"""
        try:
            while self.running:
                # 检查进程状态
                for i, process in enumerate(self.processes):
                    if process.poll() is not None:
                        print(f"⚠️ 服务 {i+1} 已停止")
                        self.running = False
                        break
                
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 收到停止信号...")
            self.stop_services()


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="启动集成服务")
    parser.add_argument("--no-frontend", action="store_true", help="不启动前端服务")
    parser.add_argument("--api-only", action="store_true", help="只启动API服务")
    parser.add_argument("--bot-only", action="store_true", help="只启动bot服务")
    
    args = parser.parse_args()
    
    manager = IntegratedServiceManager()
    
    # 设置信号处理
    def signal_handler(signum, frame):
        manager.stop_services()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        if args.api_only:
            # 只启动API
            api_process = manager.start_backend_api()
            manager.processes.append(api_process)
            print("✅ 后端API服务已启动")
        elif args.bot_only:
            # 只启动bot
            bot_process = manager.start_bot()
            manager.processes.append(bot_process)
            print("✅ Bot机器人已启动")
        else:
            # 启动所有服务
            include_frontend = FRONTEND_ENABLED and not args.no_frontend
            manager.start_services(include_frontend)
        
        # 监控服务
        manager.monitor_services()
        
    except Exception as e:
        print(f"❌ 启动失败: {e}")
        manager.stop_services()
        sys.exit(1)


if __name__ == "__main__":
    main()
