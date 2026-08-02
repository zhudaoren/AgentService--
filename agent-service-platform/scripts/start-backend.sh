#!/bin/bash
# AgentService 后端服务一键启动脚本 (Linux/macOS)
# 用法: ./start-backend.sh [--daemon] [--log-dir <目录>]
#
# 默认前台运行，Ctrl+C 同时停止所有服务
# 加 --daemon 参数可后台运行，配合 ./stop-backend.sh 停止

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_ROOT/logs"
DAEMON_MODE=false

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --daemon)
            DAEMON_MODE=true
            shift
            ;;
        --log-dir)
            LOG_DIR="$2"
            shift 2
            ;;
        -h|--help)
            echo "用法: $0 [--daemon] [--log-dir <目录>]"
            echo ""
            echo "选项:"
            echo "  --daemon         后台运行（配合 stop-backend.sh 停止）"
            echo "  --log-dir <目录>  指定日志目录（默认: ./logs）"
            echo "  -h, --help       显示此帮助"
            exit 0
            ;;
        *)
            echo "未知参数: $1"
            echo "用法: $0 [--daemon] [--log-dir <目录>]"
            exit 1
            ;;
    esac
done

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 服务配置：名称 端口 目录 启动命令后缀
SERVICES=(
    "gateway:8000:gateway"
    "agent-svc:8001:agent-svc"
    "chat-svc:8002:chat-svc"
    "mem-svc:8004:mem-svc"
)

# 检查端口是否被占用
check_port() {
    local port=$1
    if command -v lsof &>/dev/null; then
        lsof -iTCP:$port -sTCP:LISTEN &>/dev/null
    elif command -v ss &>/dev/null; then
        ss -tlnp 2>/dev/null | grep -q ":$port "
    elif command -v netstat &>/dev/null; then
        netstat -tlnp 2>/dev/null | grep -q ":$port "
    else
        # 尝试用 bash 内置方式检查
        (echo >/dev/tcp/localhost/$port) 2>/dev/null
    fi
}

# 检查 Python 依赖
check_python_deps() {
    echo -e "${BLUE}▶ 检查 Python 依赖...${NC}"
    local missing=()
    for pkg in fastapi uvicorn sqlalchemy aiomysql pydantic pydantic_settings redis cryptography httpx; do
        if ! python3 -c "import $pkg" 2>/dev/null; then
            missing+=("$pkg")
        fi
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        echo -e "${RED}✗ 缺少以下 Python 依赖:${NC}"
        printf '  - %s\n' "${missing[@]}"
        echo ""
        echo "请安装依赖:"
        echo "  pip install fastapi uvicorn 'sqlalchemy[asyncio]' aiomysql pydantic pydantic-settings redis cryptography httpx"
        exit 1
    fi
    echo -e "${GREEN}✓ Python 依赖检查通过${NC}"
}

# 检查 .env
check_env() {
    if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
        echo -e "${YELLOW}⚠ 未找到 .env 文件，将使用默认配置${NC}"
        echo "  如需自定义，请复制: cp .env.example .env"
    fi
}

# 创建日志目录
mkdir -p "$LOG_DIR"

# 停止已有进程
stop_existing() {
    local name=$1 port=$2
    if check_port $port; then
        echo -e "${YELLOW}⚠ 端口 $port 被占用，尝试停止已有 $name...${NC}"
        # 尝试查找并停止
        local pids
        pids=$(lsof -t -iTCP:$port 2>/dev/null || true)
        if [[ -n "$pids" ]]; then
            kill $pids 2>/dev/null || true
            sleep 1
        fi
        if check_port $port; then
            echo -e "${RED}✗ 端口 $port 仍被占用，请手动释放${NC}"
            return 1
        fi
    fi
}

# 启动单个服务
start_service() {
    local name=$1 port=$2 svc_dir=$3
    local log_file="$LOG_DIR/${name}.log"
    local pid_file="$LOG_DIR/${name}.pid"

    echo -e "${BLUE}▶ 启动 $name (端口 $port)...${NC}"

    cd "$PROJECT_ROOT/services/$svc_dir"

    export PYTHONPATH="$PROJECT_ROOT/services/shared:."

    if $DAEMON_MODE; then
        nohup python3 -m uvicorn main:app \
            --host 0.0.0.0 \
            --port $port \
            > "$log_file" 2>&1 &
        echo $! > "$pid_file"
        echo "  日志: $log_file | PID: $(cat "$pid_file")"
    else
        # 前台运行，输出重定向到日志同时 tee 到控制台
        python3 -m uvicorn main:app \
            --host 0.0.0.0 \
            --port $port \
            2>&1 | tee "$log_file" &
        echo $! > "$pid_file"
    fi
}

# 等待服务健康检查
wait_for_health() {
    local name=$1 port=$2
    local max_wait=30
    local waited=0

    echo -n "  等待 $name 就绪 "
    while [[ $waited -lt $max_wait ]]; do
        if curl -s --max-time 1 "http://localhost:$port/healthz" &>/dev/null; then
            echo -e "\n  ${GREEN}✓ $name 已就绪${NC}"
            return 0
        fi
        echo -n "."
        sleep 1
        ((waited++))
    done
    echo -e "\n  ${YELLOW}⚠ $name 启动超时（可能正在初始化数据库）${NC}"
    return 1
}

# 清理函数
cleanup() {
    echo ""
    echo -e "${YELLOW}▶ 收到中断信号，正在停止所有服务...${NC}"
    for svc in "${SERVICES[@]}"; do
        IFS=':' read -r name port dir <<< "$svc"
        local pid_file="$LOG_DIR/${name}.pid"
        if [[ -f "$pid_file" ]]; then
            local pid
            pid=$(cat "$pid_file" 2>/dev/null || true)
            if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
                kill "$pid" 2>/dev/null || true
                echo "  已停止 $name (PID: $pid)"
            fi
            rm -f "$pid_file"
        fi
    done
    echo -e "${GREEN}✓ 所有服务已停止${NC}"
    exit 0
}

# 主流程
echo "========================================"
echo "  AgentService 后端服务启动器"
echo "========================================"
echo ""

check_python_deps
check_env

# 注册清理钩子（仅前台模式）
if ! $DAEMON_MODE; then
    trap cleanup INT TERM
fi

echo ""
echo -e "${BLUE}▶ 启动服务列表:${NC}"
for svc in "${SERVICES[@]}"; do
    IFS=':' read -r name port dir <<< "$svc"
    echo "  • $name → http://localhost:$port"
done
echo ""

# 停止已有进程
echo -e "${BLUE}▶ 检查端口占用...${NC}"
for svc in "${SERVICES[@]}"; do
    IFS=':' read -r name port dir <<< "$svc"
    stop_existing "$name" "$port"
done
echo -e "${GREEN}✓ 端口检查完成${NC}"
echo ""

# 启动服务
for svc in "${SERVICES[@]}"; do
    IFS=':' read -r name port dir <<< "$svc"
    start_service "$name" "$port" "$dir"
    sleep 1
done

echo ""
echo -e "${BLUE}▶ 等待服务就绪...${NC}"
for svc in "${SERVICES[@]}"; do
    IFS=':' read -r name port dir <<< "$svc"
    wait_for_health "$name" "$port"
done

echo ""
echo "========================================"
if $DAEMON_MODE; then
    echo -e "  ${GREEN}✓ 所有服务已后台启动${NC}"
    echo ""
    echo "  日志目录: $LOG_DIR"
    echo "  查看日志: tail -f $LOG_DIR/*.log"
    echo "  停止服务: ./scripts/stop-backend.sh"
    echo ""
    echo "  服务地址:"
    echo "    Gateway:   http://localhost:8000"
    echo "    Agent-SVC: http://localhost:8001"
    echo "    Chat-SVC:  http://localhost:8002"
    echo "    Mem-SVC:   http://localhost:8004"
else
    echo -e "  ${GREEN}✓ 所有服务已启动（前台运行）${NC}"
    echo ""
    echo "  按 Ctrl+C 停止所有服务"
    echo ""
    echo "  服务地址:"
    echo "    Gateway:   http://localhost:8000"
    echo "    Agent-SVC: http://localhost:8001"
    echo "    Chat-SVC:  http://localhost:8002"
    echo "    Mem-SVC:   http://localhost:8004"
    echo ""
    echo "  日志目录: $LOG_DIR"
fi
echo "========================================"

# 前台模式下等待所有子进程
if ! $DAEMON_MODE; then
    wait
fi
