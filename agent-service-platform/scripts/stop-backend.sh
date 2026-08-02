#!/bin/bash
# AgentService 后端服务停止脚本 (Linux/macOS)
# 用法: ./stop-backend.sh [--force]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_ROOT/logs"
FORCE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --force)
            FORCE=true
            shift
            ;;
        -h|--help)
            echo "用法: $0 [--force]"
            echo ""
            echo "选项:"
            echo "  --force    强制停止（kill -9）"
            echo "  -h, --help 显示此帮助"
            exit 0
            ;;
        *)
            echo "未知参数: $1"
            exit 1
            ;;
    esac
done

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

SERVICES=("gateway" "agent-svc" "chat-svc" "mem-svc")

echo "========================================"
echo "  AgentService 后端服务停止器"
echo "========================================"
echo ""

stopped=0
for name in "${SERVICES[@]}"; do
    pid_file="$LOG_DIR/${name}.pid"
    if [[ -f "$pid_file" ]]; then
        pid=$(cat "$pid_file" 2>/dev/null || true)
        if [[ -n "$pid" ]]; then
            if kill -0 "$pid" 2>/dev/null; then
                if $FORCE; then
                    kill -9 "$pid" 2>/dev/null || true
                    echo -e "  ${RED}✓ 强制停止 $name (PID: $pid)${NC}"
                else
                    kill "$pid" 2>/dev/null || true
                    echo -e "  ${GREEN}✓ 已停止 $name (PID: $pid)${NC}"
                fi
                ((stopped++))
            else
                echo -e "  ${YELLOW}  $name 进程已不存在 (PID: $pid)${NC}"
            fi
        fi
        rm -f "$pid_file"
    else
        # 尝试通过端口查找进程
        case $name in
            gateway) port=8000 ;;
            agent-svc) port=8001 ;;
            chat-svc) port=8002 ;;
            mem-svc) port=8004 ;;
        esac
        pids=$(lsof -t -iTCP:$port 2>/dev/null || true)
        if [[ -n "$pids" ]]; then
            if $FORCE; then
                kill -9 $pids 2>/dev/null || true
                echo -e "  ${RED}✓ 强制停止 $name (端口 $port, PID: $pids)${NC}"
            else
                kill $pids 2>/dev/null || true
                echo -e "  ${GREEN}✓ 已停止 $name (端口 $port, PID: $pids)${NC}"
            fi
            ((stopped++))
        else
            echo -e "  ${YELLOW}  $name 未运行${NC}"
        fi
    fi
done

echo ""
if [[ $stopped -gt 0 ]]; then
    echo -e "${GREEN}✓ 共停止 $stopped 个服务${NC}"
else
    echo -e "${YELLOW}⚠ 没有运行中的服务${NC}"
fi
echo "========================================"
