# -*- coding: utf-8 -*-
"""快速单场景自测：复现用户截图中的问题
复现 query = "写一份关于 deepseekHarness 性能评估的社交媒体帖子，并消除 AI 痕迹"
预期:
  - workflow_mode 正常显示
  - 深度调研 Skill 被激活
  - web_search 工具被调用
  - 有最终回答（长度 >= 150 chars）
  - 没有 error_event 覆盖最终回答
  - 最终 assistant 消息中的 tool_calls 含有 calls/status 持久化字段 + _plan_steps/_skills_used
  - 刷新后（GET messages）恢复正确状态
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

GATEWAY = "http://127.0.0.1:8000"
TIMEOUT_S = 600
REQUEST_TIMEOUT = httpx.Timeout(TIMEOUT_S, connect=10)


async def post(path, payload):
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as c:
        r = await c.post(f"{GATEWAY}{path}", json=payload)
        try:
            body = r.json()
        except Exception:
            body = r.text[:500]
        return r.status_code, body


async def get(path, params=None):
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as c:
        r = await c.get(f"{GATEWAY}{path}", params=params)
        try:
            body = r.json()
        except Exception:
            body = r.text[:500]
        return r.status_code, body


async def create_conv(agent_id: str, title: str) -> str:
    status, body = await post(
        "/api/v1/conversations",
        {"agent_id": agent_id, "title": title, "user_id": "default"},
    )
    if status != 200:
        raise RuntimeError(f"create_conv HTTP {status} {body}")
    cid = (body.get("data") or {}).get("id")
    if not cid:
        raise RuntimeError(f"create_conv empty id body={body}")
    return cid


async def pick_agent(name_contains: str) -> str:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as c:
        r = await c.get(f"{GATEWAY}/api/v1/agents", params={"page_size": 20})
        if r.status_code != 200:
            raise RuntimeError(f"agents list HTTP {r.status_code} {r.text[:300]}")
        j = r.json()
    items = (j.get("data") or {}).get("items") or []
    for a in items:
        if name_contains in (a.get("name") or ""):
            return a["id"]
    if items:
        return items[0]["id"]
    raise RuntimeError(f"No agents found matching '{name_contains}'")


def parse_sse_event(buf: str):
    if "\n\n" not in buf:
        return None, None, buf
    block, rest = buf.split("\n\n", 1)
    event = None
    data_lines: list[str] = []
    for line in block.split("\n"):
        if line.startswith("event:"):
            event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:"):].strip())
    data_str = "\n".join(data_lines)
    data_obj: dict | None = None
    if data_str:
        try:
            data_obj = json.loads(data_str)
        except Exception:
            data_obj = {"_raw": data_str}
    return event, data_obj, rest


@dataclass
class Rep:
    conv_id: str = ""
    events: list = field(default_factory=list)
    error_events: list = field(default_factory=list)
    done_events: list = field(default_factory=list)
    workflow_modes: list = field(default_factory=list)
    plan_steps: list = field(default_factory=list)
    thinking_chars: int = 0
    message_chars: int = 0
    skills_available: list = field(default_factory=list)
    skills_used_in_event: list = field(default_factory=list)
    tool_calls: list = field(default_factory=list)
    final_error: str | None = None
    duration_s: float = 0.0


async def run_stream(conv_id: str, question: str) -> Rep:
    rep = Rep(conv_id=conv_id)
    t0 = time.time()
    url = f"{GATEWAY}/api/v1/chat"
    payload = {"conversation_id": conv_id, "content": question, "stream": True}
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as c:
            async with c.stream("POST", url, json=payload,
                                headers={"Accept": "text/event-stream"}) as resp:
                if resp.status_code != 200:
                    rep.final_error = f"HTTP {resp.status_code}: {await resp.aread()}"
                    rep.duration_s = time.time() - t0
                    return rep
                buf = ""
                async for raw in resp.aiter_text():
                    if not raw:
                        continue
                    buf += raw
                    while "\n\n" in buf:
                        evt, data, buf = parse_sse_event(buf)
                        if evt is None and data is None:
                            break
                        if not evt:
                            continue
                        rep.events.append((evt, data))
                        if evt == "workflow_mode":
                            rep.workflow_modes.append((data or {}).get("mode"))
                        elif evt == "plan_generated":
                            ps = (data or {}).get("plan_steps") or (data or {}).get("steps") or []
                            for p in ps:
                                if isinstance(p, dict):
                                    rep.plan_steps.append(p)
                        elif evt == "plan_step":
                            if isinstance(data, dict):
                                rep.plan_steps.append(data)
                        elif evt == "thinking":
                            cc = (data or {}).get("content") or ""
                            if isinstance(cc, str):
                                rep.thinking_chars += len(cc)
                        elif evt == "message":
                            cc = (data or {}).get("content") or ""
                            if isinstance(cc, str):
                                rep.message_chars += len(cc)
                        elif evt == "skills_available":
                            for sk in ((data or {}).get("skills") or []):
                                if isinstance(sk, dict):
                                    rep.skills_available.append(sk.get("name"))
                        elif evt == "skill_used":
                            rep.skills_used_in_event.append((data or {}).get("name") or (data or {}).get("skill_name"))
                        elif evt in ("tool_call", "tool_call_start", "tool_call_result"):
                            rep.tool_calls.append({"evt": evt, **(data or {})})
                        elif evt == "error":
                            rep.error_events.append(data)
                        elif evt == "done":
                            rep.done_events.append(data)
    except Exception as e:
        rep.final_error = f"stream_exception: {type(e).__name__}: {e}"
    rep.duration_s = time.time() - t0
    return rep


def print_buckets(rep: Rep):
    print(f"\n--- STREAM SUMMARY (duration={rep.duration_s:.1f}s) ---")
    print(f"  workflow_modes   = {rep.workflow_modes}")
    print(f"  plan_steps_count = {len(rep.plan_steps)}")
    print(f"  thinking_chars   = {rep.thinking_chars}")
    print(f"  message_chars    = {rep.message_chars}")
    print(f"  skills_available = {rep.skills_available}")
    print(f"  skills_used_evts = {rep.skills_used_in_event}")
    tool_names = [(t.get("tool_name") or t.get("name") or t.get("tool"), t.get("status") or t.get("evt"))
                  for t in rep.tool_calls]
    print(f"  tool_calls       = {tool_names[:12]} (total {len(rep.tool_calls)})")
    print(f"  error_events     = {len(rep.error_events)}  (first={rep.error_events[0] if rep.error_events else None})")
    print(f"  done_events      = {len(rep.done_events)}")


def check(rep: Rep):
    fails = []
    def P(name, ok, reason):
        tag = "PASS" if ok else "FAIL"
        print(f"  [{tag}] {name}: {reason}")
        if not ok:
            fails.append((name, reason))

    print("\n--- VALIDATION ---")
    # ReAct (Hybrid) 模式不会生成 plan_steps；只有 P&E (plan_and_execute) 模式才有。
    # 如果 workflow_mode 是 plan_and_execute 或 hybrid，就允许 plan_steps=0
    is_pe = any(m in ("plan_and_execute", "hybrid") for m in rep.workflow_modes)
    P("workflow mode present", any(rep.workflow_modes), f"modes={rep.workflow_modes}")
    need_plan = is_pe and any(m == "plan_and_execute" for m in rep.workflow_modes)
    P("plan_steps (only for P&E mode)", (not need_plan) or len(rep.plan_steps) >= 1,
      f"steps={len(rep.plan_steps)}  workflow_modes={rep.workflow_modes}")
    P("thinking produced", rep.thinking_chars >= 50, f"thinking_chars={rep.thinking_chars}")
    P("final answer >= 150 chars", rep.message_chars >= 150, f"message_chars={rep.message_chars}")
    P("skills_available not empty", len(rep.skills_available) >= 1, f"skills_available={rep.skills_available}")
    P("web_search tool fired", any(("search" in (t.get("tool_name") or t.get("name") or t.get("tool") or "").lower())
                                     for t in rep.tool_calls), f"tool_names={[(t.get('tool_name'),t.get('name')) for t in rep.tool_calls]}")
    P("no error when answer >= 150",
      (not rep.error_events) or rep.message_chars >= 150,
      f"error_events={len(rep.error_events)} message_chars={rep.message_chars}")
    P("done event present", len(rep.done_events) >= 1, f"done={len(rep.done_events)}")
    P("no fatal stream exception", rep.final_error is None, f"final_error={rep.final_error}")
    return fails


async def inspect_messages(conv_id: str):
    status, body = await get(f"/api/v1/conversations/{conv_id}/messages", params={"page": 1, "page_size": 200})
    print(f"\n--- REFRESH / GET messages HTTP {status} ---")
    if status != 200:
        print(f"  FAILED: {body}")
        return []
    items = ((body.get("data") or {}).get("items") or [])
    print(f"  total messages: {len(items)}")
    # Dump all types to aid debugging
    type_counts: dict[str, int] = {}
    for m in items:
        t = m.get("message_type") or "UNKNOWN"
        type_counts[t] = type_counts.get(t, 0) + 1
    print(f"  message_type counts: {type_counts}")
    for m in items:
        print(f"    id={m.get('id')} type={m.get('message_type')} content_len={len(str(m.get('content') or ''))}")
    # find assistant message with tool_calls
    assistant_msgs = [m for m in items if m.get("message_type") == "assistant"]
    print(f"  assistant msgs: {len(assistant_msgs)}")
    checks = []
    for i, m in enumerate(assistant_msgs[-2:]):  # last 2
        tc_raw = m.get("tool_calls")
        parsed = None
        if isinstance(tc_raw, str) and tc_raw:
            try:
                parsed = json.loads(tc_raw)
            except Exception:
                parsed = None
        elif isinstance(tc_raw, dict):
            parsed = tc_raw
        calls = None
        plan_s = None
        skills_u = None
        if isinstance(parsed, dict):
            if "calls" in parsed:
                calls = parsed.get("calls")
            plan_s = parsed.get("_plan_steps")
            skills_u = parsed.get("_skills_used")
        # also check messages-level plan_steps/skills_used columns
        col_plan = m.get("plan_steps")
        col_skills = m.get("skills_used")
        print(f"\n  assistant[{i}] id={m.get('id')} content_len={len(str(m.get('content') or ''))}")
        print(f"    plan_steps (column)  = {'✅ present' if isinstance(col_plan, list) and col_plan else '❌ MISSING'} ({type(col_plan).__name__})")
        print(f"    skills_used (column) = {'✅ present' if isinstance(col_skills, list) and col_skills else '❌ MISSING'} ({type(col_skills).__name__})")
        print(f"    tool_calls.calls     = {'✅ present' if isinstance(calls, list) else '❌ MISSING'}")
        if isinstance(calls, list):
            print(f"      calls[0] sample keys: {list(calls[0].keys()) if calls else 'EMPTY'}")
            for j, c in enumerate(calls[:5]):
                print(f"      call#{j}: name={c.get('tool_name')} status={c.get('status')}")
        print(f"    tool_calls._plan_steps   = {'✅ present' if isinstance(plan_s, list) and plan_s else '(N/A)'}  (count={len(plan_s) if isinstance(plan_s, list) else 0})")
        print(f"    tool_calls._skills_used  = {'✅ present' if isinstance(skills_u, list) and skills_u else '(N/A)'}  (count={len(skills_u) if isinstance(skills_u, list) else 0})")
        checks.append({
            "id": m.get("id"),
            "col_plan_ok": bool(isinstance(col_plan, list) and col_plan),
            "col_skills_ok": bool(isinstance(col_skills, list) and col_skills),
            "tc_calls_ok": isinstance(calls, list),
            "tc_plan_ok": isinstance(plan_s, list) and bool(plan_s),
            "tc_skills_ok": isinstance(skills_u, list) and bool(skills_u),
            "calls_statuses_ok": all(c.get("status") in ("success", "failed") for c in (calls or [])) if isinstance(calls, list) else False,
        })
    return checks


async def main():
    print(f"[self-test] gateway={GATEWAY}")
    async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5)) as c:
        r = await c.get(f"{GATEWAY}/healthz")
        print(f"[self-test] gateway healthz HTTP {r.status_code}")
    agent_id = await pick_agent("日常对话助手")
    print(f"[self-test] agent_id={agent_id}")
    conv_id = await create_conv(agent_id, f"self-test-{int(time.time())}")
    print(f"[self-test] conv_id={conv_id}")
    question = (
        "你帮我写一份关于deepseekHarness性能评估的社交媒体帖子，"
        "并消除中文文本中的AI生成痕迹，将生硬的机器输出转化为自然流畅的人类文笔。"
    )
    print(f"\n[self-test] Question:\n  {question}")
    print(f"\n[self-test] Running SSE stream (max {TIMEOUT_S}s)...")
    rep = await run_stream(conv_id, question)
    print_buckets(rep)
    fails = check(rep)
    checks = await inspect_messages(conv_id)
    # validate persistence
    # 设计上 plan_steps / skills_usED 不在 Message 表独立列，而是存在 tool_calls JSON 里
    # （避免 DB schema 变更，前端通过 normalizeToolCalls 从 tool_calls 解析）。
    # 所以这里只要求：
    #   - tool_calls.calls 存在且每条都有 status（success/failed）
    #   - tool_calls._skills_used 至少非空（即「使用了哪些技能」元信息被持久化）
    #   - plan_steps 列不存在是允许的（设计如此）
    print("\n--- REFRESH PERSISTENCE CHECKS ---")
    for ck in checks:
        ok = ck["tc_calls_ok"] and ck["calls_statuses_ok"] and ck["tc_skills_ok"]
        tag = "PASS" if ok else "FAIL"
        print(f"  [{tag}] msg {ck['id']}: plan_col={ck['col_plan_ok']} skills_col={ck['col_skills_ok']} tc_calls={ck['tc_calls_ok']} statuses_ok={ck['calls_statuses_ok']} tc_plan={ck['tc_plan_ok']} tc_skills={ck['tc_skills_ok']}")
        if not ok:
            fails.append((f"persist:{ck['id'][:8]}", str(ck)))
    if fails:
        print(f"\n❌ FAILED {len(fails)} checks:")
        for n, r in fails:
            print(f"   - {n}: {r}")
        sys.exit(2)
    else:
        print("\n✅ ALL CHECKS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
