#!/usr/bin/env python3
"""
AgentService 中间件一键停止脚本 (跨平台)
支持 Linux / macOS / Windows

用法:
    python scripts/stop-middleware.py [--volumes]

--volumes  同时删除数据卷（慎用：会清除所有持久化数据）
"""

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

COMPOSE_MIDDLEWARE = ["mysql", "redis", "minio", "milvus-etcd", "milvus-minio", "milvus-standalone"]
CONTAINERS = ["agent-mysql", "agent-redis", "agent-minio", "agent-milvus-etcd", "agent-milvus-minio", "agent-milvus"]

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

def ok(msg):   print(f"  {Color.GREEN}✓ {msg}{Color.NC}")
def warn(msg): print(f"  {Color.YELLOW}⚠ {msg}{Color.NC}")
def err(msg):  print(f"  {Color.RED}✗ {msg}{Color.NC}")

def run(cmd: list[str], cwd: str = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)

def find_compose_cmd() -> str | None:
    r = run(["docker", "compose", "version"])
    if r.returncode == 0:
        return "docker compose"
    if shutil.which("docker-compose"):
        return "docker-compose"
    return None

def main():
    parser = argparse.ArgumentParser(description="AgentService 中间件停止器")
    parser.add_argument("--volumes", action="store_true", help="同时删除数据卷（慎用）")
    args = parser.parse_args()

    script_dir = Path(__file__).parent.resolve()
    project_root = script_dir.parent

    print("=" * 40)
    print("  AgentService 中间件停止器")
    print("=" * 40)
    print()

    compose_cmd = find_compose_cmd()

    if compose_cmd:
        compose_parts = compose_cmd.split()

        if args.volumes:
            print(f"{Color.RED}⚠ 警告: 将删除所有中间件数据卷！{Color.NC}")
            print(f"{Color.YELLOW}  这会清除 MySQL/Redis/MinIO/Milvus 的所有持久化数据！{Color.NC}")
            print()
            resp = input("  确认删除？输入 YES 继续: ")
            if resp != "YES":
                print("已取消")
                return
            print()
            r = run(compose_parts + ["down", "-v"] + COMPOSE_MIDDLEWARE, cwd=str(project_root))
            if r.stdout:
                for line in r.stdout.strip().splitlines():
                    print(f"  {line}")
            print()
            ok("中间件已停止，数据卷已删除")
        else:
            r = run(compose_parts + ["stop"] + COMPOSE_MIDDLEWARE, cwd=str(project_root))
            if r.stdout:
                for line in r.stdout.strip().splitlines():
                    print(f"  {line}")
            print()
            ok("中间件已停止（数据卷保留）")
            print()
            print("  重新启动: python scripts/start-middleware.py")
            print("  彻底删除: python scripts/stop-middleware.py --volumes")
    else:
        # 回退：直接 docker stop 容器
        warn("未找到 Docker Compose，尝试直接停止容器...")
        print()
        stopped = 0
        for name in CONTAINERS:
            r = run(["docker", "ps", "--format", "{{.Names}}"])
            if name in r.stdout:
                run(["docker", "stop", name])
                ok(f"已停止 {name}")
                stopped += 1
            else:
                print(f"  {name} 未运行")
        print()
        if stopped > 0:
            ok(f"共停止 {stopped} 个中间件容器")
        else:
            warn("没有运行中的中间件")

    print()
    print("=" * 40)

if __name__ == "__main__":
    main()
