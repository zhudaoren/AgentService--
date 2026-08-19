#!/usr/bin/env python3
"""
AgentService 中间件一键启动脚本 (跨平台)
支持 Linux / macOS / Windows

用法:
    python scripts/start-middleware.py [--pull] [--check-only]

启动中间件: MySQL / Redis / MinIO / Milvus(etcd+minio+standalone)
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

# ── 镜像清单 ──────────────────────────────────────────

IMAGES = [
    {"image": "mysql:8.0",                                  "container": "agent-mysql",          "port": 3306},
    {"image": "redis:7-alpine",                             "container": "agent-redis",          "port": 6379},
    {"image": "minio/minio:RELEASE.2024-10-13T13-34-11Z",   "container": "agent-minio",          "port": 9000},
    {"image": "quay.io/coreos/etcd:v3.5.5",                 "container": "agent-milvus-etcd",    "port": None},
    {"image": "minio/minio:RELEASE.2023-03-20T20-16-18Z",    "container": "agent-milvus-minio",   "port": None},
    {"image": "milvusdb/milvus:v2.4.0",                     "container": "agent-milvus",         "port": 19530},
]

COMPOSE_MIDDLEWARE = ["mysql", "redis", "minio", "milvus-etcd", "milvus-minio", "milvus-standalone"]

# ── 颜色 ──────────────────────────────────────────────

class Color:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    NC = "\033[0m"

    @classmethod
    def disabled(cls):
        cls.GREEN = cls.YELLOW = cls.RED = cls.BLUE = cls.CYAN = cls.NC = ""

if platform.system() == "Windows":
    Color.disabled()

def info(msg):   print(f"{Color.BLUE}▶ {msg}{Color.NC}")
def ok(msg):     print(f"  {Color.GREEN}✓ {msg}{Color.NC}")
def warn(msg):   print(f"  {Color.YELLOW}⚠ {msg}{Color.NC}")
def err(msg):    print(f"  {Color.RED}✗ {msg}{Color.NC}")

# ── 工具函数 ───────────────────────────────────────────

def run(cmd: list[str], cwd: str = None, capture: bool = False) -> subprocess.CompletedProcess:
    """执行命令"""
    return subprocess.run(cmd, cwd=cwd, capture_output=capture, text=True)

def docker_available() -> bool:
    """检查 Docker 是否可用"""
    r = run(["docker", "info"])
    return r.returncode == 0

def find_compose_cmd() -> str | None:
    """查找 docker compose 命令"""
    # v2: docker compose
    r = run(["docker", "compose", "version"])
    if r.returncode == 0:
        return "docker compose"
    # v1: docker-compose
    if shutil.which("docker-compose"):
        return "docker-compose"
    return None

def is_port_in_use(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0

def wait_for_service(name: str, check_fn, timeout: int = 60, interval: int = 2) -> bool:
    """等待服务就绪"""
    print(f"  {name} ", end="", flush=True)
    for i in range(timeout // interval):
        try:
            if check_fn():
                ok("")
                return True
        except Exception:
            pass
        print(".", end="", flush=True)
        time.sleep(interval)
    err("超时")
    return False

# ── .env 解析 ──────────────────────────────────────

def load_env_file(path: Path) -> dict:
    """解析 .env 文件，返回 dict"""
    env = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                env[key] = val
    return env


# 运行时加载 .env 配置
_ENV = load_env_file(Path(__file__).parent.parent / ".env")

MYSQL_ROOT_PASSWORD = _ENV.get("MYSQL_ROOT_PASSWORD", "root123")
REDIS_PASSWORD = _ENV.get("REDIS_PASSWORD", "")


def check_mysql() -> bool:
    cmd = ["docker", "exec", "agent-mysql", "mysqladmin", "ping", "-h", "localhost", "-uroot"]
    pwd = MYSQL_ROOT_PASSWORD
    if pwd:
        cmd.append(f"-p{pwd}")
    r = run(cmd)
    return r.returncode == 0


def check_redis() -> bool:
    cmd = ["docker", "exec", "agent-redis", "redis-cli"]
    if REDIS_PASSWORD:
        cmd += ["-a", REDIS_PASSWORD]
    cmd += ["ping"]
    r = run(cmd)
    return r.returncode == 0

def check_minio() -> bool:
    try:
        with urlopen("http://localhost:9000/minio/health/live", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False

def check_milvus() -> bool:
    try:
        with urlopen("http://localhost:9091/healthz", timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False

# ── 主逻辑 ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="AgentService 中间件启动器")
    parser.add_argument("--pull", action="store_true", help="启动前先拉取所有镜像")
    parser.add_argument("--check-only", action="store_true", help="仅检查环境，不启动服务")
    args = parser.parse_args()

    script_dir = Path(__file__).parent.resolve()
    project_root = script_dir.parent
    compose_file = project_root / "docker-compose.yml"

    print("=" * 40)
    print("  AgentService 中间件启动器")
    print("=" * 40)
    print()

    # 1. 检查 Docker
    info("检查 Docker 环境...")
    if not docker_available():
        err("Docker 未运行或未安装")
        print("  请安装并启动 Docker:")
        print("    https://docs.docker.com/engine/install/")
        sys.exit(1)
    ok("Docker 已就绪")

    compose_cmd = find_compose_cmd()
    if not compose_cmd:
        err("未找到 Docker Compose")
        print("  请安装: https://docs.docker.com/compose/install/")
        sys.exit(1)
    ok(f"Docker Compose: {compose_cmd}")
    print()

    # 2. 检查 .env
    env_file = project_root / ".env"
    if not env_file.exists():
        warn("未找到 .env 文件，从模板创建...")
        shutil.copy(project_root / ".env.example", env_file)
        ok("已从 .env.example 创建 .env")
        print()

    # 3. 列出镜像清单
    print(f"{Color.CYAN}── 中间件镜像清单 ──{Color.NC}")
    print()
    print(f"  {'镜像':<45} {'容器名':<22} {'端口'}")
    print(f"  {'-'*45} {'-'*22} {'-'*6}")
    for img in IMAGES:
        port_str = str(img["port"]) if img["port"] else "-"
        print(f"  {img['image']:<45} {img['container']:<22} {port_str}")
    print()
    print(f"  总计 {len(IMAGES)} 个镜像")
    print()

    # 4. 拉取镜像
    if args.pull:
        info("拉取镜像（首次需要联网，可能需要数分钟）...")
        for img in IMAGES:
            print(f"  拉取 {img['image']} ... ", end="", flush=True)
            r = run(["docker", "pull", img["image"]])
            if r.returncode == 0:
                ok("")
            else:
                err("失败")
                warn("请检查网络或使用国内镜像源:")
                print('    {"registry-mirrors": [')
                print('      "https://docker.mirrors.ustc.edu.cn",')
                print('      "https://hub-mirror.c.163.com"')
                print('    ]}')
                print("  配置文件: /etc/docker/daemon.json")
                sys.exit(1)
        ok("所有镜像拉取完成")
        print()

    # 仅检查模式
    if args.check_only:
        ok("环境检查完成，退出（--check-only）")
        return

    # 5. 检查端口占用
    info("检查端口占用...")
    ports = {3306: "MySQL", 6379: "Redis", 9000: "MinIO-API", 9001: "MinIO-Console", 19530: "Milvus", 9091: "Milvus-Metrics"}
    conflict = False
    for port, name in ports.items():
        if is_port_in_use(port):
            warn(f"端口 {port} ({name}) 已被占用")
            conflict = True
    if conflict:
        warn("存在端口冲突，可能是中间件已在运行")
        print("  如需重启，请先停止: python scripts/stop-middleware.py")
        resp = input("  是否继续启动？(y/N): ")
        if resp.lower() != "y":
            print("已取消")
            return
    else:
        ok("端口检查完成")
    print()

    # 6. 启动中间件
    info("启动中间件服务...")
    compose_parts = compose_cmd.split()
    cmd = compose_parts + ["up", "-d"] + COMPOSE_MIDDLEWARE
    r = run(cmd, cwd=str(project_root))
    if r.returncode != 0:
        err("启动失败")
        print(r.stderr)
        sys.exit(1)
    if r.stdout:
        for line in r.stdout.strip().splitlines():
            print(f"  {line}")
    print()

    # 7. 等待就绪
    info("等待中间件就绪...")
    print()

    wait_for_service("MySQL (3306)",    check_mysql,  timeout=60, interval=2)
    wait_for_service("Redis (6379)",    check_redis,  timeout=15, interval=1)
    wait_for_service("MinIO (9000)",    check_minio,  timeout=15, interval=1)
    wait_for_service("Milvus (19530)",  check_milvus, timeout=120, interval=2)

    print()

    # 8. 显示状态
    print("=" * 40)
    ok("中间件启动状态")
    print("=" * 40)
    print()
    r = run(compose_parts + ["ps"] + COMPOSE_MIDDLEWARE, cwd=str(project_root))
    if r.stdout:
        for line in r.stdout.strip().splitlines():
            print(f"  {line}")
    print()
    print("  服务地址:")
    print("    MySQL:          localhost:3306  (root/root123)")
    print("    Redis:          localhost:6379  (无密码)")
    print("    MinIO API:      http://localhost:9000  (minioadmin/minioadmin)")
    print("    MinIO Console:  http://localhost:9001  (minioadmin/minioadmin)")
    print("    Milvus:         localhost:19530")
    print("    Milvus Metrics: http://localhost:9091/metrics")
    print()
    print("  停止中间件: python scripts/stop-middleware.py")
    print(f"  查看日志:   {compose_cmd} logs -f mysql redis minio milvus-standalone")
    print("=" * 40)

if __name__ == "__main__":
    main()
