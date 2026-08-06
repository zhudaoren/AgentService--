#!/bin/bash
# AgentService 中间件一键启动脚本 (Linux/macOS)
# 用法: ./scripts/start-middleware.sh [--pull] [--check-only]
#
# 启动中间件: MySQL / Redis / MinIO / Milvus(etcd+minio+standalone)
# --pull       启动前先拉取镜像
# --check-only 仅检查环境，不启动服务

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.yml"

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# 中间件服务清单
MIDDLEWARE_SERVICES=(
    "mysql:8.0|agent-mysql|3306"
    "redis:7-alpine|agent-redis|6379"
    "minio/minio:RELEASE.2024-01-01T00-00-00Z|agent-minio|9000"
    "quay.io/coreos/etcd:v3.5.5|agent-milvus-etcd|-"
    "minio/minio:RELEASE.2023-03-20T20-16-18Z|agent-milvus-minio|-"
    "milvusdb/milvus:v2.4.0|agent-milvus|19530"
)

# Docker Compose 中间件服务名（与 docker-compose.yml 中一致）
COMPOSE_MIDDLEWARE="mysql redis minio milvus-etcd milvus-minio milvus-standalone"

# 解析参数
PULL_IMAGES=false
CHECK_ONLY=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --pull)
            PULL_IMAGES=true
            shift
            ;;
        --check-only)
            CHECK_ONLY=true
            shift
            ;;
        -h|--help)
            echo "用法: $0 [--pull] [--check-only]"
            echo ""
            echo "选项:"
            echo "  --pull        启动前先拉取所有镜像"
            echo "  --check-only  仅检查环境，不启动服务"
            echo "  -h, --help    显示此帮助"
            exit 0
            ;;
        *)
            echo "未知参数: $1"
            exit 1
            ;;
    esac
done

echo "========================================"
echo "  AgentService 中间件启动器"
echo "========================================"
echo ""

# ── 1. 检查 Docker ──────────────────────────────────────

echo -e "${BLUE}▶ 检查 Docker 环境...${NC}"
if ! command -v docker &>/dev/null; then
    echo -e "${RED}✗ 未安装 Docker，请先安装:${NC}"
    echo "  https://docs.docker.com/engine/install/"
    exit 1
fi
if ! docker info &>/dev/null; then
    echo -e "${RED}✗ Docker 未运行，请先启动 Docker 服务${NC}"
    echo "  sudo systemctl start docker  (Linux)"
    echo "  或打开 Docker Desktop          (macOS)"
    exit 1
fi
echo -e "${GREEN}✓ Docker 已就绪${NC}"
echo ""

# 检查 docker compose (v2) 或 docker-compose (v1)
COMPOSE_CMD=""
if docker compose version &>/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &>/dev/null; then
    COMPOSE_CMD="docker-compose"
else
    echo -e "${RED}✗ 未找到 Docker Compose，请安装:${NC}"
    echo "  https://docs.docker.com/compose/install/"
    exit 1
fi
echo -e "${GREEN}✓ Docker Compose: $COMPOSE_CMD${NC}"
echo ""

# ── 2. 检查 .env ───────────────────────────────────────

if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
    echo -e "${YELLOW}⚠ 未找到 .env 文件，从模板创建...${NC}"
    cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
    echo -e "${GREEN}✓ 已从 .env.example 创建 .env${NC}"
    echo ""
fi

# ── 3. 列出镜像清单 ────────────────────────────────────

echo -e "${CYAN}── 中间件镜像清单 ──${NC}"
echo ""
printf "  %-45s %-15s %s\n" "镜像" "容器名" "端口"
printf "  %-45s %-15s %s\n" "─────────────────────────────────────────────" "──────────────" "──────"
for svc in "${MIDDLEWARE_SERVICES[@]}"; do
    IFS='|' read -r image container port <<< "$svc"
    printf "  %-45s %-15s %s\n" "$image" "$container" "${port:--}"
done
echo ""
echo -e "  总计 ${#MIDDLEWARE_SERVICES[@]} 个镜像"
echo ""

# ── 4. 拉取镜像 ────────────────────────────────────────

if $PULL_IMAGES; then
    echo -e "${BLUE}▶ 拉取镜像（首次需要联网，可能需要数分钟）...${NC}"
    for svc in "${MIDDLEWARE_SERVICES[@]}"; do
        IFS='|' read -r image container port <<< "$svc"
        echo -n "  拉取 $image ... "
        if docker pull "$image" &>/dev/null; then
            echo -e "${GREEN}✓${NC}"
        else
            echo -e "${RED}✗ 失败${NC}"
            echo -e "  ${YELLOW}请检查网络或使用国内镜像源:${NC}"
            echo "    {"
            echo '      "registry-mirrors": ['
            echo '        "https://docker.mirrors.ustc.edu.cn",'
            echo '        "https://hub-mirror.c.163.com"'
            echo '      ]'
            echo "    }"
            echo "  配置文件: /etc/docker/daemon.json"
            exit 1
        fi
    done
    echo -e "${GREEN}✓ 所有镜像拉取完成${NC}"
    echo ""
fi

# 仅检查模式
if $CHECK_ONLY; then
    echo -e "${GREEN}✓ 环境检查完成，退出（--check-only）${NC}"
    exit 0
fi

# ── 5. 检查端口占用 ────────────────────────────────────

check_port() {
    local port=$1
    if command -v lsof &>/dev/null; then
        lsof -iTCP:$port -sTCP:LISTEN &>/dev/null
    elif command -v ss &>/dev/null; then
        ss -tlnp 2>/dev/null | grep -q ":$port "
    elif command -v netstat &>/dev/null; then
        netstat -tlnp 2>/dev/null | grep -q ":$port "
    else
        (echo >/dev/tcp/localhost/$port) 2>/dev/null
    fi
}

echo -e "${BLUE}▶ 检查端口占用...${NC}"
PORTS=("3306:MySQL" "6379:Redis" "9000:MinIO-API" "9001:MinIO-Console" "19530:Milvus" "9091:Milvus-Metrics")
port_conflict=false
for entry in "${PORTS[@]}"; do
    IFS=':' read -r port name <<< "$entry"
    if check_port "$port"; then
        echo -e "  ${YELLOW}⚠ 端口 $port ($name) 已被占用${NC}"
        port_conflict=true
    fi
done
if $port_conflict; then
    echo ""
    echo -e "${YELLOW}⚠ 存在端口冲突，可能是中间件已在运行${NC}"
    echo "  如需重启，请先停止: ./scripts/stop-middleware.sh"
    echo ""
    read -p "  是否继续启动？(y/N) " -r
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "已取消"
        exit 0
    fi
fi
echo -e "${GREEN}✓ 端口检查完成${NC}"
echo ""

# ── 6. 启动中间件 ──────────────────────────────────────

echo -e "${BLUE}▶ 启动中间件服务...${NC}"
echo ""

cd "$PROJECT_ROOT"
$COMPOSE_CMD up -d $COMPOSE_MIDDLEWARE 2>&1 | sed 's/^/  /'

echo ""
echo -e "${BLUE}▶ 等待中间件就绪...${NC}"
echo ""

# 等待 MySQL
echo -n "  MySQL (3306) "
for i in $(seq 1 30); do
    if docker exec agent-mysql mysqladmin ping -h localhost -uroot -proot123 &>/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
        break
    fi
    echo -n "."
    sleep 2
    if [[ $i -eq 30 ]]; then
        echo -e "${RED}✗ 超时${NC}"
    fi
done

# 等待 Redis
echo -n "  Redis (6379) "
for i in $(seq 1 15); do
    if docker exec agent-redis redis-cli ping &>/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
        break
    fi
    echo -n "."
    sleep 1
    if [[ $i -eq 15 ]]; then
        echo -e "${RED}✗ 超时${NC}"
    fi
done

# 等待 MinIO
echo -n "  MinIO (9000) "
for i in $(seq 1 15); do
    if curl -s --max-time 1 http://localhost:9000/minio/health/live &>/dev/null; then
        echo -e "${GREEN}✓${NC}"
        break
    fi
    echo -n "."
    sleep 1
    if [[ $i -eq 15 ]]; then
        echo -e "${RED}✗ 超时${NC}"
    fi
done

# 等待 Milvus
echo -n "  Milvus (19530) "
for i in $(seq 1 60); do
    if curl -s --max-time 1 http://localhost:9091/healthz &>/dev/null; then
        echo -e "${GREEN}✓${NC}"
        break
    fi
    echo -n "."
    sleep 2
    if [[ $i -eq 60 ]]; then
        echo -e "${RED}✗ 超时（Milvus 首次启动较慢，请稍后检查）${NC}"
    fi
done

echo ""

# ── 7. 显示状态 ────────────────────────────────────────

echo "========================================"
echo -e "  ${GREEN}中间件启动状态${NC}"
echo "========================================"
echo ""
$COMPOSE_CMD ps $COMPOSE_MIDDLEWARE 2>/dev/null | sed 's/^/  /'
echo ""
echo "  服务地址:"
echo "    MySQL:          localhost:3306  (root/root123)"
echo "    Redis:          localhost:6379  (无密码)"
echo "    MinIO API:      http://localhost:9000  (minioadmin/minioadmin)"
echo "    MinIO Console:  http://localhost:9001  (minioadmin/minioadmin)"
echo "    Milvus:         localhost:19530"
echo "    Milvus Metrics: http://localhost:9091/metrics"
echo ""
echo "  停止中间件: ./scripts/stop-middleware.sh"
echo "  查看日志:   $COMPOSE_CMD logs -f mysql redis minio milvus-standalone"
echo "========================================"
