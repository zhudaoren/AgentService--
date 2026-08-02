#!/usr/bin/env python3
"""
AgentService 后端服务一键启动脚本 (跨平台)
支持 Linux / macOS / Windows

用法:
    python scripts/start-backend.py [--daemon] [--log-dir <目录>]

默认前台运行，Ctrl+C 同时停止所有服务
加 --daemon 参数可后台运行，配合 stop-backend.py 停止
"""

import argparse
import os
import platform
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

# ── 配置 ──────────────────────────────────────────────

SERVICES = [
    {"name": "gateway",   "port": 8000, "dir": "gateway"},
    {"name": "agent-svc", "port": 8001, "dir": "agent-svc"},
    {"name": "chat-svc",  "port": 8002, "dir": "chat-svc"},
    {"name": "mem-svc",   "port": 8004, "dir": "mem-svc"},
]

PYTHON_DEPS = [
    "fastapi", "uvicorn", "sqlalchemy", "aiomysql",
    "pydantic", "pydantic_settings", "redis", "cryptography", "httpx",
]

# ── 颜色 ──────────────────────────────────────────────

class Color:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    NC = "\033[0m"

    @classmethod
    def disabled(cls):
        cls.GREEN = cls.YELLOW = cls.RED = cls.BLUE = cls.NC = ""

if platform.system() == "Windows":
    Color.disabled()

# ── 工具函数 ────────────────────────────────────────────

def info(msg):   print(f"{Color.BLUE}▶ {msg}{Color.NC}")
def ok(msg):     print(f"  {Color.GREEN}✓ {msg}{Color.NC}")
def warn(msg):   print(f"  {Color.YELLOW}⚠ {msg}{Color.NC}")
def err(msg):    print(f"  {Color.RED}✗ {msg}{Color.NC}")

def check_python_deps():
    """检查 Python 依赖"""
    info("检查 Python 依赖...")
    missing = []
    for pkg in PYTHON_DEPS:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        err(f"缺少以下 Python 依赖: {', '.join(missing)}")
        print("\n请安装依赖:")
        print("  pip install fastapi uvicorn 'sqlalchemy[asyncio]' aiomysql")
        print("    pydantic pydantic-settings redis cryptography httpx")
        sys.exit(1)
    ok("Python 依赖检查通过")

def check_env(project_root: Path):
    """检查 .env 文件"""
    env_file = project_root / ".env"
    if not env_file.exists():
        warn("未找到 .env 文件，将使用默认配置")
        print("  如需自定义，请复制: cp .env.example .env")

def is_port_in_use(port: int) -> bool:
    """检查端口是否被占用"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0

def wait_for_health(port: int, timeout: int = 30) -> bool:
    """等待服务健康检查通过"""
    for _ in range(timeout):
        try:
            with urlopen(f"http://localhost:{port}/healthz", timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    return False

def stop_process(pid: int, force: bool = False):
    """停止进程"""
    import psutil
    try:
        p = psutil.Process(pid)
        if force:
            p.kill()
        else:
            p.terminate()
            try:
                p.wait(timeout=3)
            except psutil.TimeoutExpired:
                p.kill()
    except psutil.NoSuchProcess:
        pass

def cleanup_processes(log_dir: Path):
    """清理所有已记录 PID 的进程"""
    for svc in SERVICES:
        pid_file = log_dir / f"{svc['name']}.pid"
        if pid_file.exists():
            try:
                pid = int(pid_file.read_text().strip())
                stop_process(pid)
            except (ValueError, psutil.NoSuchProcess):
                pass
            pid_file.unlink(missing_ok=True)

# ── 主逻辑 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="AgentService 后端服务启动器")
    parser.add_argument("--daemon", action="store_true", help="后台运行")
    parser.add_argument("--log-dir", default=None, help="日志目录（默认: ./logs）")
    args = parser.parse_args()

    script_dir = Path(__file__).parent.resolve()
    project_root = script_dir.parent
    log_dir = Path(args.log_dir) if args.log_dir else project_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 40)
    print("  AgentService 后端服务启动器")
    print("=" * 40)
    print()

    check_python_deps()
    check_env(project_root)

    # 注册 Ctrl+C 处理（仅前台模式）
    processes = []
    if not args.daemon:
        def signal_handler(signum, frame):
            print()
            info("收到中断信号，正在停止所有服务...")
            for p in processes:
                if p.poll() is None:
                    p.terminate()
                    try:
                        p.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        p.kill()
            cleanup_processes(log_dir)
            ok("所有服务已停止")
            sys.exit(0)
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    print()
    info("启动服务列表:")
    for svc in SERVICES:
        print(f"  • {svc['name']} → http://localhost:{svc['port']}")
    print()

    # 检查端口占用
    info("检查端口占用...")
    for svc in SERVICES:
        port = svc["port"]
        if is_port_in_use(port):
            warn(f"端口 {port} 被占用，尝试释放...")
            # 尝试通过 psutil 查找并停止
            try:
                import psutil
                for conn in psutil.net_connections():
                    if conn.laddr.port == port and conn.pid:
                        stop_process(conn.pid)
                        time.sleep(1)
                        break
            except ImportError:
                pass
            if is_port_in_use(port):
                err(f"端口 {port} 仍被占用，请手动释放")
                sys.exit(1)
    ok("端口检查完成")
    print()

    # 启动服务
    shared_path = str(project_root / "services" / "shared")

    for svc in SERVICES:
        name = svc["name"]
        port = svc["port"]
        svc_dir = project_root / "services" / svc["dir"]
        log_file = log_dir / f"{name}.log"
        pid_file = log_dir / f"{name}.pid"

        info(f"启动 {name} (端口 {port})...")

        env = os.environ.copy()
        env["PYTHONPATH"] = f"{shared_path}{os.pathsep}."

        if args.daemon:
            # 后台模式：完全脱离终端
            if platform.system() == "Windows":
                # Windows 使用 CREATE_NEW_PROCESS_GROUP
                p = subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", "main:app",
                     "--host", "0.0.0.0", "--port", str(port)],
                    cwd=str(svc_dir),
                    env=env,
                    stdout=open(log_file, "w"),
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            else:
                p = subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", "main:app",
                     "--host", "0.0.0.0", "--port", str(port)],
                    cwd=str(svc_dir),
                    env=env,
                    stdout=open(log_file, "w"),
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            pid_file.write_text(str(p.pid))
            print(f"  日志: {log_file} | PID: {p.pid}")
        else:
            # 前台模式
            p = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "main:app",
                 "--host", "0.0.0.0", "--port", str(port)],
                cwd=str(svc_dir),
                env=env,
                stdout=open(log_file, "w"),
                stderr=subprocess.STDOUT,
            )
            pid_file.write_text(str(p.pid))
            processes.append(p)

        time.sleep(1)

    print()
    info("等待服务就绪...")
    for svc in SERVICES:
        if wait_for_health(svc["port"]):
            ok(f"{svc['name']} 已就绪")
        else:
            warn(f"{svc['name']} 启动超时（可能正在初始化数据库）")

    print()
    print("=" * 40)
    if args.daemon:
        ok("所有服务已后台启动")
        print()
        print(f"  日志目录: {log_dir}")
        print(f"  查看日志: tail -f {log_dir}/*.log")
        print(f"  停止服务: python {script_dir}/stop-backend.py")
        print()
        print("  服务地址:")
        print("    Gateway:   http://localhost:8000")
        print("    Agent-SVC: http://localhost:8001")
        print("    Chat-SVC:  http://localhost:8002")
        print("    Mem-SVC:   http://localhost:8004")
    else:
        ok("所有服务已启动（前台运行）")
        print()
        print("  按 Ctrl+C 停止所有服务")
        print()
        print("  服务地址:")
        print("    Gateway:   http://localhost:8000")
        print("    Agent-SVC: http://localhost:8001")
        print("    Chat-SVC:  http://localhost:8002")
        print("    Mem-SVC:   http://localhost:8004")
        print()
        print(f"  日志目录: {log_dir}")
    print("=" * 40)

    # 前台模式下等待所有子进程
    if not args.daemon:
        for p in processes:
            p.wait()

if __name__ == "__main__":
    try:
        import psutil
    except ImportError:
        pass  # psutil 是可选的
    main()
