"""Seed initial rows directly via MySQL"""
import sys
try:
    import pymysql
except ImportError:
    try:
        # try aiomysql via pymysql compatibility path
        import aiomysql as pymysql_mod
        print("using aiomysql")
    except ImportError as e:
        print("No mysql driver:", e); sys.exit(1)

from dotenv import load_dotenv
from pathlib import Path
import os, uuid, json, datetime

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

cfg = dict(
    host=os.getenv("MYSQL_HOST", "localhost"),
    port=int(os.getenv("MYSQL_PORT", "3306")),
    user=os.getenv("MYSQL_USER", "root"),
    password=os.getenv("MYSQL_ROOT_PASSWORD", "root"),
    database=os.getenv("MYSQL_DATABASE", "agent_service"),
    charset="utf8mb4",
    autocommit=False,
)

DS_KEY = os.getenv("DEEPSEEK_API_KEY", "")

print("Connecting to MySQL:", cfg["host"], cfg["port"], cfg["database"])

import pymysql

def enc_key(s: str) -> str:
    """简单加解密占位：后端加密存储，这里使用明文存即可，LLM service会在读取时兼容或重新加密"""
    return s or ""

conn = pymysql.connect(**cfg)
try:
    with conn.cursor() as cur:
        now = datetime.datetime.now()
        def insert_one(table, data):
            cols = ",".join(f"`{k}`" for k in data.keys())
            ph = ",".join(["%s"] * len(data))
            sql = f"INSERT INTO `{table}` ({cols}) VALUES ({ph})"
            vals = list(data.values())
            cur.execute(sql, vals)
            new_id = cur.lastrowid
            # get UUID if it was generated
            if "id" not in data:
                cur.execute(f"SELECT LAST_INSERT_ID(), id FROM `{table}` ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
                return row[1] if row else None
            return data.get("id")

        # 1. LLM config
        llm_id = str(uuid.uuid4())
        try:
            insert_one("llm_configs", dict(
                id=llm_id,
                name="DeepSeek-V3 默认",
                provider="deepseek",
                model_name="deepseek-chat",
                api_key=enc_key(DS_KEY),
                api_base_url="https://api.deepseek.com",
                default_params=json.dumps(dict(temperature=0.7, max_tokens=4096, top_p=0.9), ensure_ascii=False),
                is_default=1,
                is_builtin=1,
                created_at=now, updated_at=now,
            ))
            print(f"✓ LLM config inserted: id={llm_id}")
        except Exception as e:
            print("LLM insert (likely duplicate?):", e)
            cur.execute("ROLLBACK")

        # 2. MCP service (web search stub disconnected)
        mcp_id = str(uuid.uuid4())
        try:
            insert_one("mcp_services", dict(
                id=mcp_id,
                name="联网搜索MCP",
                description="通过联网实时搜索，获取最新资讯、数据、事实等信息",
                mode="sse",
                sse_url="http://localhost:8005/mcp-sse",
                status="disconnected",
                auth_type="none",
                oauth_status="not_configured",
                is_builtin=1,
                created_at=now, updated_at=now,
            ))
            print(f"✓ MCP service inserted: id={mcp_id}")
        except Exception as e:
            print("MCP insert (likely duplicate?):", e)
            cur.execute("ROLLBACK")

        # 3. Skill (深度调研)
        skill_id = str(uuid.uuid4())
        try:
            insert_one("skills", dict(
                id=skill_id,
                name="深度调研",
                description="针对复杂话题进行多轮次、多维度、多来源的深度信息检索与综合分析，输出结构化的深度研究报告。适用于行业研究、竞品分析、技术选型、市场调研、趋势预测等复杂问题。",
                category="research",
                version="1.0.0",
                source="local",
                enabled=1,
                usage_count=0,
                success_rate=0.0,
                tags=json.dumps(["调研", "研究", "分析", "报告", "research"], ensure_ascii=False),
                created_at=now, updated_at=now,
            ))
            # skill_levels
            for (lv, desc, cont) in [
                (0, "技能核心触发词与目标概述", "当用户提出需要进行深度调研、行业研究、市场分析、竞品分析、技术调研、综合报告、多维度对比分析、趋势预测等复杂研究型任务时，激活本技能。目标：通过系统的信息检索与综合分析，输出高质量结构化调研报告。"),
                (1, "技能核心流程与工作方法", "核心流程：1.需求分析与拆解 2.信息源规划与关键词设计 3.多轮检索与多源信息获取 4.交叉比对与事实核查 5.结构化综合与大纲构建 6.报告撰写与质量审查"),
                (2, "执行策略与质量标准", "质量标准：数据来源可追溯、分析逻辑清晰、报告结构完整、数据时效性优先近3个月。策略：标注数据获取时间；采信权威来源；诚实地说明调研范围与边界。"),
            ]:
                insert_one("skill_levels", dict(
                    id=str(uuid.uuid4()),
                    skill_id=skill_id,
                    level=lv,
                    description=desc,
                    content=cont,
                    created_at=now, updated_at=now,
                ))
            print(f"✓ Skill inserted: id={skill_id}")
        except Exception as e:
            print("Skill insert (likely duplicate?):", e)
            cur.execute("ROLLBACK")

        # 4. Agent "日常对话助手" + bindings
        agent_id = str(uuid.uuid4())
        try:
            insert_one("agents", dict(
                id=agent_id,
                name="日常对话助手",
                description="支持日常对话、深度调研、联网搜索的通用助手。支持ReAct和Plan-and-Execute两种工作模式。",
                system_prompt="你是一名专业的日常对话助手，拥有以下能力：\n1.日常对话：回答用户各类问题\n2.深度调研：针对复杂话题进行多维度深度检索与综合分析，输出结构化研究报告\n3.联网搜索：通过MCP联网搜索服务获取实时权威信息\n4.使用工具：熟练调用各类MCP工具和技能\n工作模式：Hybrid自适应选择，根据问题复杂度在ReAct和Plan-and-Execute之间切换。\n请根据用户的问题自动选择最合适的工作模式和技能进行回答。",
                llm_config_id=llm_id,
                status="deployed",
                is_official=0,
                temperature=0.7,
                max_tokens=4096,
                top_p=0.9,
                memory_strategy="standard",
                config=json.dumps(dict(workflow_mode="hybrid"), ensure_ascii=False),
                created_at=now, updated_at=now,
            ))
            # Agent MCP binding
            insert_one("agent_mcp_bindings", dict(
                id=str(uuid.uuid4()),
                agent_id=agent_id,
                mcp_service_id=mcp_id,
                config=json.dumps({}, ensure_ascii=False),
                enabled=1,
                created_at=now,
            ))
            # Agent Skill binding
            insert_one("agent_skill_bindings", dict(
                id=str(uuid.uuid4()),
                agent_id=agent_id,
                skill_id=skill_id,
                priority=10,
                enabled=1,
                created_at=now, updated_at=now,
            ))
            # Long-term memory for agent
            insert_one("long_term_memories", dict(
                id=str(uuid.uuid4()),
                agent_id=agent_id,
                user_profile=json.dumps({}, ensure_ascii=False),
                environment_facts=json.dumps({}, ensure_ascii=False),
                experience=json.dumps({}, ensure_ascii=False),
                shared_items=json.dumps([], ensure_ascii=False),
                version=1,
                updated_at=now, created_at=now,
            ))
            print(f"✓ Agent inserted: id={agent_id}")
        except Exception as e:
            print("Agent insert (likely duplicate?):", e)
            cur.execute("ROLLBACK")

        conn.commit()

        # Final check
        for t in ["llm_configs", "agents", "mcp_services", "skills", "agent_mcp_bindings", "agent_skill_bindings"]:
            cur.execute(f"SELECT COUNT(*) FROM `{t}`")
            print(f"  {t}: {cur.fetchone()[0]} rows")
finally:
    conn.close()
print("DONE")
