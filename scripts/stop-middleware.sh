#!/bin/bash
# AgentService 中间件一键停止脚本 (Linux/macOS)
# 用法: ./scripts/stop-middleware.sh [--volumes]
#
# --volumes  同时删除数据卷（慎用：会清除所有持久化数据）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

COMPOSE_MIDDLEWARE="mysql redis minio milvus-etcd milvus-minio milvus-standalone"
REMOVE_VOLUMES=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --volumes)
            REMOVE_VOLUMES=true
            shift
            ;;
        -h|--help)
            echo "用法: $0 [--volumes]"
            echo ""
            echo "选项:"
            echo "  --volumes  同时删除数据卷（慎用：会清除所有持久化数据）"
            echo "  -h, --help 显示此帮助"
            exit 0
            ;;
        *)
            echo "未知参数: $1"
            exit 1
            ;;
    esac
done

# 检查 docker compose 命令
COMPOSE_CMD=""
if docker compose version &>/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &>/dev/null; then
    COMPOSE_CMD="docker-compose"
else
    # 回退：直接 docker stop 容器
    echo -e "${YELLOW}⚠ 未找到 Docker Compose，尝试直接停止容器...${NC}"
    CONTAINERS=("agent-mysql" "agent-redis" "agent-minio" "agent-milvus-etcd" "agent-milvus-minio" "agent-milvus")
    stopped=0
    for name in "${CONTAINERS[@]}"; do
        if docker ps --format '{{.Names}}' | grep -q "^${name}$"; then
            docker stop "$name" &>/dev/null
            echo -e "  ${GREEN}✓ 已停止 $name${NC}"
            ((stopped++))
        else
            echo -e "  ${YELLOW}  $name 未运行${NC}"
        fi
    done
    echo ""
    if [[ $stopped -gt 0 ]]; then
        echo -e "${GREEN}✓ 共停止 $stopped 个中间件容器${NC}"
    else
        echo -e "${YELLOW}⚠ 没有运行中的中间件${NC}"
    fi
    exit 0
fi

echo "========================================"
echo "  AgentService 中间件停止器"
echo "========================================"
echo ""

cd "$PROJECT_ROOT"

if $REMOVE_VOLUMES; then
    echo -e "${RED}⚠ 警告: 将删除所有中间件数据卷！${NC}"
    echo -e "${YELLOW}  这会清除 MySQL/Redis/MinIO/Milvus 的所有持久化数据！${NC}"
    echo ""
    read -p "  确认删除？输入 YES 继续: " -r
    if [[ "$REPLY" != "YES" ]]; then
        echo "已取消"
        exit 0
    fi
    echo ""
    $COMPOSE_CMD down -v $COMPOSE_MIDDLEWARE 2>&1 | sed 's/^/  /'
    echo ""
    echo -e "${GREEN}✓ 中间件已停止，数据卷已删除${NC}"
else
    $COMPOSE_CMD stop $COMPOSE_MIDDLEWARE 2>&1 | sed 's/^/  /'
    echo ""
    echo -e "${GREEN}✓ 中间件已停止（数据卷保留）${NC}"
    echo ""
    echo "  重新启动: ./scripts/start-middleware.sh"
    echo "  彻底删除: ./scripts/stop-middleware.sh --volumes"
fi

echo "========================================"
