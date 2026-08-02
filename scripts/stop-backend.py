#!/usr/bin/env python3
"""
AgentService 后端服务停止脚本 (跨平台)
支持 Linux / macOS / Windows

用法:
    python scripts/stop-backend.py [--force]
"""

import argparse
import os
import signal
import sys
import time
from pathlib import Path

SERVICES = ["gateway", "agent-svc", "chat-svc", "tool-svc", "mem-svc"]
SERVICE_PORTS = {
    "gateway": 8000,
    "agent-svc": 8001,
    "chat-svc": 8002,
    "tool-svc": 8003,
    "mem-svc": 8004,
}


def main():
    parser = argparse.ArgumentParser(description="AgentService 后端服务停止器")
    parser.add_argument("--force", action="store_true", help="强制停止（kill -9）")
    args = parser.parse_args()

    script_dir = Path(__file__).parent.resolve()
    project_root = script_dir.parent
    log_dir = project_root / "logs"

    print("=" * 40)
    print("  AgentService 后端服务停止器")
    print("=" * 40)
    print()

    stopped = 0

    for name in SERVICES:
        pid_file = log_dir / f"{name}.pid"
        found = False

        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                if _is_running(pid):
                    _stop_pid(pid, force=args.force)
                    print(f"  ✓ {'强制停止' if args.force else '已停止'} {name} (PID: {pid})")
                    stopped += 1
                    found = True
                else:
                    print(f"    {name} 进程已不存在 (PID: {pid})")
            except ValueError:
                pass
            pid_file.unlink(missing_ok=True)

        if not found:
            # 尝试通过端口查找
            port = SERVICE_PORTS[name]
            pids = _find_pids_by_port(port)
            if pids:
                for pid in pids:
                    _stop_pid(pid, force=args.force)
                print(f"  ✓ {'强制停止' if args.force else '已停止'} {name} (端口 {port}, PID: {', '.join(map(str, pids))})")
                stopped += 1
                found = True

        if not found:
            print(f"    {name} 未运行")

    print()
    if stopped > 0:
        print(f"✓ 共停止 {stopped} 个服务")
    else:
        print("⚠ 没有运行中的服务")
    print("=" * 40)


def _is_running(pid: int) -> bool:
    """检查进程是否运行中"""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _stop_pid(pid: int, force: bool = False):
    """停止进程"""
    try:
        if force:
            os.kill(pid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGTERM)
            # 等待3秒
            for _ in range(30):
                if not _is_running(pid):
                    return
                time.sleep(0.1)
            os.kill(pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass


def _find_pids_by_port(port: int) -> list:
    """通过端口查找进程ID"""
    pids = []
    try:
        import psutil
        for conn in psutil.net_connections():
            if hasattr(conn, 'laddr') and conn.laddr.port == port and conn.pid:
                pids.append(conn.pid)
    except ImportError:
        pass
    return list(set(pids))


if __name__ == "__main__":
    main()
