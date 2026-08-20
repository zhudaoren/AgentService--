"""Initialize AgentService platform with LLM config / MCP service / Skill data"""
import asyncio, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "services" / "shared"))
try:
    import httpx
    from dotenv import load_dotenv
except ImportError as e:
    print("Missing dep:", e); sys.exit(1)

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

GATEWAY = "http://127.0.0.1:8000"
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
QWEN_KEY = os.getenv("QWEN_API_KEY", "")

print("DeepSeek key loaded:", "YES" if DEEPSEEK_KEY else "NO")
print("Qwen key loaded:", "YES" if QWEN_KEY else "NO")

async def post(path: str, payload: dict, label: str):
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{GATEWAY}{path}", json=payload)
        print(f"{label}: status={r.status_code}")
        print("  body:", r.text[:500])
        return r.status_code, r.json() if r.headers.get("content-type","").startswith("application/json") else r.text

async def get(path: str, label: str):
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{GATEWAY}{path}")
        print(f"{label}: status={r.status_code}")
        print("  body:", r.text[:400])
        return r.status_code, r.json() if r.headers.get("content-type","").startswith("application/json") else r.text

async def main():
    # 1. DeepSeek LLM
    status, body = await post("/api/v1/llm-configs", {
        "name": "DeepSeek-V3 默认",
        "provider": "deepseek",
        "model_name": "deepseek-chat",
        "api_key": DEEPSEEK_KEY,
        "api_base_url": "https://api.deepseek.com",
        "default_params": {"temperature": 0.7, "max_tokens": 4096, "top_p": 0.9},
        "is_default": True,
    }, "1. Create DeepSeek LLM config")

    # 2. 联网搜索 MCP
    await post("/api/v1/mcp-services", {
        "name": "联网搜索MCP",
        "description": "通过联网实时搜索，获取最新资讯、数据、事实等信息",
        "mode": "sse",
        "sse_url": "http://localhost:8005/mcp-sse",
        "status": "disconnected",
    }, "2. Create MCP (websearch)")

    # 3. 深度调研 Skill
    await post("/api/v1/skills", {
        "name": "深度调研",
        "description": "针对复杂话题进行多轮次、多维度、多来源的深度信息检索与综合分析，输出结构化的深度研究报告。适用于行业研究、竞品分析、技术选型、市场调研、趋势预测等复杂问题。",
        "category": "research",
        "version": "1.0.0",
        "source": "local",
        "enabled": True,
        "tags": ["调研", "研究", "分析", "报告", "research"],
        "levels": [
            {
                "level": 0,
                "description": "技能核心触发词与目标概述",
                "content": "当用户提出需要进行深度调研、行业研究、市场分析、竞品分析、技术调研、综合报告、多维度对比分析、趋势预测等复杂研究型任务时，激活本技能。\n目标：通过系统的信息检索与综合分析，输出高质量结构化调研报告。",
            },
            {
                "level": 1,
                "description": "技能核心流程与工作方法",
                "content": "核心流程：\n1. 需求分析与拆解\n2. 信息源规划与关键词设计\n3. 多轮检索与多源信息获取\n4. 交叉比对与事实核查\n5. 结构化综合与大纲构建\n6. 报告撰写与质量审查",
            },
            {
                "level": 2,
                "description": "详细执行策略与质量标准",
                "content": "质量标准：数据来源可追溯、分析逻辑清晰、报告结构完整、数据时效性优先近3个月。\n策略：标注数据获取时间；采信权威来源；限制调研范围与诚实地说明边界。",
            },
        ],
    }, "3. Create Skill (深度调研)")

    # 4. Lists
    print("\n=== Lists ===")
    await get("/api/v1/llm-configs", "LLM list")
    await get("/api/v1/mcp-services", "MCP list")
    await get("/api/v1/skills", "Skill list")

asyncio.run(main())
