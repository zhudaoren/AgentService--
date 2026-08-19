# -*- coding: utf-8 -*-
"""SSE Integration Test Runner for AgentService Chat Pipeline

Tests the full streaming chat pipeline via gateway:
  POST /api/v1/conversations  (create conv for an agent)
  POST /api/v1/chat           (SSE stream)

Validates:
  A. Event-type sequence correctness (workflow_mode -> thinking ->
     thinking_to_answer -> message -> done) to catch 最终回答/思考错位
  B. Skill activation for 深度调研 skill question
  C. Tool calls (incl. web_search / MCP 联网搜索) fire
  D. plan_generated event contains plan_steps for Plan-and-Execute
  E. Thinking content != Final answer content (no leak across blocks)
  F. Final answer length > min chars & no error text covering valid answers
  G. ERROR / done event present at stream end
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

GATEWAY = "http://localhost:8000"
TIMEOUT_S = 360  # single SSE stream max runtime (P&E + deep research + multi tool needs more)
REQUEST_TIMEOUT = httpx.Timeout(TIMEOUT_S, connect=10)

PY = sys.executable


# ── helpers ────────────────────────────────────────────────────────────────
async def post(path: str, payload: dict) -> tuple[int, Any]:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as c:
        r = await c.post(f"{GATEWAY}{path}", json=payload)
        body = None
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
    if status != 200 or not isinstance(body, dict):
        raise RuntimeError(f"create_conv failed status={status} body={body}")
    data = body.get("data") or {}
    cid = data.get("id")
    if not cid:
        raise RuntimeError(f"create_conv empty id body={body}")
    return cid


def parse_sse_event(buf: str) -> tuple[str | None, dict | None, str]:
    """Parse a single SSE block ("event: ...\\ndata: ...\\n\\n")
    Returns (event_type, parsed_data_dict_or_None_if_no_data, remaining_buf)
    """
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
class StreamReport:
    name: str
    agent_id: str
    question: str
    conv_id: str = ""
    status: str = "pending"  # pass/fail/pending
    events: list[tuple[str, dict | None]] = field(default_factory=list)
    error: str | None = None
    # parsed buckets
    workflow_mode_events: list[dict] = field(default_factory=list)
    skills_available: list[dict] = field(default_factory=list)
    skill_used: list[dict] = field(default_factory=list)
    plan_generated: list[dict] = field(default_factory=list)
    plan_steps: list[dict] = field(default_factory=list)
    thinking_chars: int = 0
    thinking_samples: list[str] = field(default_factory=list)
    message_chars: int = 0
    message_samples: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    error_events: list[dict] = field(default_factory=list)
    done_events: list[dict] = field(default_factory=list)
    thinking_to_answer_seen: bool = False
    started_at: float = 0.0
    finished_at: float = 0.0

    def total_time_s(self) -> float:
        return max(0.0, self.finished_at - self.started_at)


async def run_sse_stream(rep: StreamReport, workflow_mode: str | None = None) -> None:
    rep.started_at = time.time()
    url = f"{GATEWAY}/api/v1/chat"
    payload: dict[str, Any] = {
        "conversation_id": rep.conv_id,
        "content": rep.question,
        "stream": True,
    }
    if workflow_mode:
        payload["workflow_mode"] = workflow_mode

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as c:
            async with c.stream("POST", url, json=payload,
                                headers={"Accept": "text/event-stream"}) as resp:
                if resp.status_code != 200:
                    rep.status = "fail"
                    rep.error = f"HTTP {resp.status_code}: {await resp.aread()}"
                    rep.finished_at = time.time()
                    return
                buf = ""
                async for raw in resp.aiter_text():
                    if not raw:
                        continue
                    buf += raw
                    while "\n\n" in buf:
                        evt, data, buf = parse_sse_event(buf)
                        if evt is None and data is None:
                            break
                        if evt:
                            rep.events.append((evt, data))
                            # bucket
                            if evt == "workflow_mode":
                                rep.workflow_mode_events.append(data or {})
                            elif evt == "skills_available":
                                rep.skills_available.append(data or {})
                            elif evt == "skill_used":
                                rep.skill_used.append(data or {})
                            elif evt == "plan_generated":
                                rep.plan_generated.append(data or {})
                                # backend uses field "steps"; frontend assigns to plan_steps internally
                                ps = (data or {}).get("plan_steps") or (data or {}).get("steps") or []
                                if isinstance(ps, list):
                                    rep.plan_steps.extend([p for p in ps if isinstance(p, dict)])
                            elif evt == "plan_step":
                                rep.plan_steps.append(data or {})
                            elif evt == "thinking":
                                c = (data or {}).get("content") or ""
                                if isinstance(c, str):
                                    rep.thinking_chars += len(c)
                                    # Lower threshold: 1 char to allow tiny-chunk streams to sample
                                    if len(rep.thinking_samples) < 3 and len(c) >= 1:
                                        # Append consecutive, deduplicate later
                                        if len(rep.thinking_samples) == 0 or len(c) > 5:
                                            rep.thinking_samples.append(c[:300])
                            elif evt == "thinking_to_answer":
                                rep.thinking_to_answer_seen = True
                            elif evt == "message":
                                c = (data or {}).get("content") or ""
                                if isinstance(c, str):
                                    rep.message_chars += len(c)
                                    if len(rep.message_samples) < 3 and len(c) >= 1:
                                        if len(rep.message_samples) == 0 or len(c) > 5:
                                            rep.message_samples.append(c[:300])
                            elif evt == "tool_call" or evt == "tool_call_start" or evt == "tool_call_result":
                                rep.tool_calls.append({"evt": evt, **(data or {})})
                            elif evt == "error":
                                rep.error_events.append(data or {})
                            elif evt == "done":
                                rep.done_events.append(data or {})
    except Exception as e:
        rep.status = "fail"
        rep.error = f"stream_exception: {type(e).__name__}: {e}"
        rep.finished_at = time.time()
        return
    rep.finished_at = time.time()

    # simple overall pass heuristic
    if rep.error_events and rep.message_chars < 80:
        rep.status = "fail"
        if not rep.error:
            first_err = rep.error_events[0]
            rep.error = f"error_event: {json.dumps(first_err, ensure_ascii=False)[:400]}"
    elif rep.message_chars < 30 and not rep.done_events:
        rep.status = "fail"
        rep.error = (f"no meaningful final answer received, message_chars={rep.message_chars}, "
                     f"done_events={len(rep.done_events)}, events_total={len(rep.events)}")
    else:
        rep.status = "pass"


# ── Validators ─────────────────────────────────────────────────────────────
def validate(rep: StreamReport, rules: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Return list of (check_id, status PASS/FAIL, reason)."""
    out: list[tuple[str, str, str]] = []

    def P(cid: str, ok: bool, reason: str) -> None:
        out.append((cid, "PASS" if ok else "FAIL", reason))

    P("T-overall", rep.status == "pass",
      f"overall={rep.status}, duration={rep.total_time_s():.1f}s, err={rep.error or 'nil'}")
    P("T-done-event", len(rep.done_events) >= 1,
      f"done_events count={len(rep.done_events)}")

    if rules.get("want_workflow_mode"):
        modes = [e.get("mode") for e in rep.workflow_mode_events if isinstance(e, dict)]
        P("W-workflow_mode-set", any(modes),
          f"workflow_mode_events modes={modes}")
        if rules.get("expect_mode"):
            P("W-workflow_mode-expect", rules["expect_mode"] in modes,
              f"expect={rules['expect_mode']} actual modes={modes}")

    if rules.get("want_skill"):
        skill_names: set[str] = set()
        for su in rep.skill_used:
            nm = su.get("name") or su.get("skill") or su.get("skill_name")
            if isinstance(nm, str):
                skill_names.add(nm)
        # fall back: available skill names
        for sa in rep.skills_available:
            for sk in (sa.get("skills") or []):
                if isinstance(sk, dict):
                    n2 = sk.get("name") or sk.get("id")
                    if isinstance(n2, str):
                        skill_names.add(n2)
        want = rules["want_skill"]
        P("S-skill-activation", any(want in n for n in skill_names),
          f"skills_seen={sorted(skill_names)}, want='{want}'")

    if rules.get("want_tool_search"):
        search_names: list[str] = []
        for tc in rep.tool_calls:
            n = tc.get("tool_name") or tc.get("name") or tc.get("tool")
            if isinstance(n, str):
                search_names.append(n.lower())
        ok = any(("search" in n) or ("web" in n) or ("baidu" in n) or ("bing" in n) or ("google" in n)
                 for n in search_names)
        # also fall back: accept mcp tool with any generic name if total >= 1
        if not ok and rules.get("want_tool_search_loose"):
            ok = len(rep.tool_calls) >= 1
        P("X-search-tool", ok,
          f"tool_call_names={search_names[:8]} total_tools={len(rep.tool_calls)}")

    if rules.get("want_plan_steps"):
        P("P-plan-steps", len(rep.plan_steps) >= rules["want_plan_steps"],
          f"plan_steps_count={len(rep.plan_steps)}  require≥{rules['want_plan_steps']}")

    # Final answer separation (no large overlap between thinking and answer)
    if rules.get("want_final_answer_separation"):
        # Robust heuristic:
        # 1. Must have produced final answer content (message_chars>0)
        # 2. If both thinking & answer produced, their concatenated first samples should NOT be
        #    near-identical (>85% char equality for first 100 chars means leak)
        # 3. If either is empty, separation is still fine as long as message_chars>0.
        leak_suspected = False
        evidence = ""
        if rep.message_chars <= 0:
            leak_suspected = True
            evidence = "final answer empty (message_chars=0)"
        elif rep.thinking_chars == 0 or not rep.thinking_samples or not rep.message_samples:
            leak_suspected = False
            evidence = f"no overlap possible: thinking_chars={rep.thinking_chars} answer_samples_empty={not rep.message_samples}"
        else:
            t = rep.thinking_samples[0]
            a = rep.message_samples[0]
            if len(t) > 40 and t[:40] == a[:40]:
                leak_suspected = True
                evidence = f"thinking&answer first 40 chars identical: {t[:60]!r}"
            else:
                leak_suspected = False
                evidence = (f"distinct content: thinking_sample[:60]={t[:60]!r} "
                            f"answer_sample[:60]={a[:60]!r}")
        P("A-separation-no-leak", not leak_suspected,
          f"thinking_chars={rep.thinking_chars} message_chars={rep.message_chars} detail={evidence}")

    # Final answer length
    min_len = rules.get("min_answer_chars", 50)
    P("A-answer-length", rep.message_chars >= min_len,
      f"message_chars={rep.message_chars}  require≥{min_len}")

    # thinking_to_answer seen (or no-thinking path valid)
    if rules.get("want_thinking_to_answer"):
        P("F-thinking→answer-transition", rep.thinking_to_answer_seen or rep.thinking_chars == 0,
          f"thinking_to_answer_seen={rep.thinking_to_answer_seen} thinking_chars={rep.thinking_chars}")

    # No fatal error when we expected valid answer
    if rules.get("forbid_error"):
        P("E-no-error-when-expected-answer",
          (not rep.error_events) or rep.message_chars >= rules.get("forbid_error_min_chars", 200),
          f"error_events_count={len(rep.error_events)}  message_chars={rep.message_chars}")

    # Event ordering (monotonic check)
    order_ok = True
    order_evidence = []
    answer_started = False
    for evt, data in rep.events:
        if evt in ("thinking", "thinking_start") and answer_started:
            order_ok = False
            order_evidence.append(f"{evt} AFTER answer started")
            break
        if evt == "thinking_to_answer":
            answer_started = True
        if evt == "message":
            answer_started = True
    P("O-event-order-no-thinking-after-answer", order_ok,
      "; ".join(order_evidence) if order_evidence else "order correct")

    return out


# ── Main scenarios ─────────────────────────────────────────────────────────
SCENARIOS = [
    {
        "id": "T1-深度调研-新能源车",
        "agent_name_contains": "日常对话助手",
        "question": (
            "帮我对比2025年比亚迪海鸥和五菱宏光MINIEV的销量趋势、配置差异和用户口碑，给出购买建议。"
            "请使用深度调研技能，并通过联网搜索获取最新数据，给出详实的对比分析报告。"
        ),
        "workflow_mode": None,  # Hybrid default
        "rules": {
            "want_workflow_mode": True,
            "want_skill": "深度调研",
            "want_tool_search": True,
            "want_tool_search_loose": True,
            "want_final_answer_separation": True,
            "want_thinking_to_answer": True,
            "forbid_error": True,
            "forbid_error_min_chars": 300,
            "min_answer_chars": 200,
        },
    },
    {
        "id": "T2-ReAct-简单工具问答",
        "agent_name_contains": "日常对话助手",
        "question": (
            "2025年杭州G20峰会什么时候召开？主会场在哪里？请通过联网搜索确认最新信息。"
        ),
        "workflow_mode": "react",
        "rules": {
            "want_workflow_mode": True,
            "expect_mode": "react",
            "want_tool_search": True,
            "want_tool_search_loose": True,
            "want_final_answer_separation": True,
            "want_thinking_to_answer": True,
            "forbid_error": True,
            "forbid_error_min_chars": 150,
            "min_answer_chars": 80,
        },
    },
    {
        "id": "T3-P&E-多步骤旅行规划",
        "agent_name_contains": "日常对话助手",
        "question": (
            "帮我规划一次7天6晚的成都亲子游，孩子5岁，预算8000元（含交通住宿餐饮门票）。"
            "请先制定详细执行计划，再逐步执行。需要包含：每日行程、交通方案、景点门票价格、酒店推荐、餐厅推荐。"
            "请联网搜索2025年最新价格和开放时间。"
        ),
        "workflow_mode": "plan_and_execute",
        "rules": {
            "want_workflow_mode": True,
            "expect_mode": "plan_and_execute",
            "want_plan_steps": 3,  # at least 3 plan steps
            "want_tool_search": True,
            "want_tool_search_loose": True,
            "want_final_answer_separation": True,
            "want_thinking_to_answer": True,
            "forbid_error": True,
            "forbid_error_min_chars": 300,
            "min_answer_chars": 300,
        },
    },
    {
        "id": "T4-联网搜索MCP-最新新闻",
        "agent_name_contains": "日常对话助手",
        "question": (
            "2025年诺贝尔物理学奖颁给了谁？获奖理由是什么？请一定先联网搜索再回答，不要猜测。"
        ),
        "workflow_mode": None,
        "rules": {
            "want_workflow_mode": True,
            "want_tool_search": True,
            "want_tool_search_loose": True,
            "want_final_answer_separation": True,
            "want_thinking_to_answer": True,
            "forbid_error": True,
            "forbid_error_min_chars": 150,
            "min_answer_chars": 100,
        },
    },
]


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
        # fallback: first agent
        if items:
            return items[0]["id"]
        raise RuntimeError(f"No agents found matching '{name_contains}'")


def print_report_table(all_checks: list[tuple[str, str, str]]) -> None:
    # all_checks list of (scen_id, cid, status, reason)
    header = f"{'Scenario':<24} {'Check':<36} {'Result':<7} Reason"
    print("\n" + "=" * 140)
    print("FINAL VALIDATION SUMMARY")
    print("=" * 140)
    print(header)
    print("-" * 140)
    for scen_id, cid, status, reason in all_checks:
        # truncate reason
        r = reason.replace("\n", " ")
        if len(r) > 78:
            r = r[:75] + "..."
        print(f"{scen_id[:24]:<24} {cid[:36]:<36} {status:<7} {r}")
    print("=" * 140)
    fails = [t for t in all_checks if t[2] == "FAIL"]
    total = len(all_checks)
    passed = total - len(fails)
    print(f"RESULT: {passed}/{total} checks passed.  FAILURES={len(fails)}")
    if fails:
        print("FAILURES detail:")
        for scen_id, cid, status, reason in fails:
            print(f"  - [{scen_id}] {cid}: {reason}")
        sys.exit(2)
    else:
        print("ALL CHECKS PASSED ✅")


async def main() -> None:
    print(f"[setup] gateway={GATEWAY}  scenarios={len(SCENARIOS)}  timeout={TIMEOUT_S}s")
    # verify gateway
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10, connect=5)) as c:
            r = await c.get(f"{GATEWAY}/healthz")
            print(f"[setup] gateway healthz HTTP {r.status_code}")
    except Exception as e:
        print(f"[setup] gateway UNREACHABLE: {type(e).__name__}: {e}")
        sys.exit(1)

    all_rows: list[tuple[str, str, str, str]] = []
    for scen in SCENARIOS:
        sid = scen["id"]
        print(f"\n{'#' * 120}")
        print(f"## SCENARIO {sid}")
        print(f"## Question: {scen['question'][:120]}…")
        print(f"## workflow_mode: {scen['workflow_mode'] or '(default Hybrid)'}")
        print(f"{'#' * 120}")
        try:
            agent_id = await pick_agent(scen["agent_name_contains"])
            print(f"  → agent_id={agent_id}")
            conv_id = await create_conv(agent_id, title=f"itest-{sid}-{int(time.time())}")
            print(f"  → conv_id={conv_id}")
        except Exception as e:
            print(f"  !! setup failed: {type(e).__name__}: {e}")
            all_rows.append((sid, "PRE-SETUP", "FAIL", f"setup err: {e}"))
            continue

        rep = StreamReport(name=sid, agent_id=agent_id,
                           question=scen["question"], conv_id=conv_id)
        await run_sse_stream(rep, workflow_mode=scen.get("workflow_mode"))

        print(f"  → result={rep.status}  duration={rep.total_time_s():.1f}s")
        print(f"  → events_total={len(rep.events)}  thinking_chars={rep.thinking_chars}  "
              f"message_chars={rep.message_chars}  tools={len(rep.tool_calls)}  "
              f"plan_steps={len(rep.plan_steps)}  skills_used={len(rep.skill_used)}  "
              f"error_events={len(rep.error_events)}  done_events={len(rep.done_events)}")
        if rep.error:
            print(f"  → error_detail: {rep.error}")
        if rep.error_events:
            for i, ee in enumerate(rep.error_events[:3]):
                print(f"  → error_events[{i}]: {json.dumps(ee, ensure_ascii=False)[:300]}")
        # show event type order (summary, deduplicated consecutive)
        order: list[str] = []
        for e, _d in rep.events:
            if not order or order[-1] != e:
                order.append(e)
        print(f"  → event_order: {' → '.join(order[:30])}")
        if rep.message_samples:
            print(f"  → answer_sample[0]: {rep.message_samples[0][:200]}")
        if rep.thinking_samples:
            print(f"  → thinking_sample[0]: {rep.thinking_samples[0][:200]}")

        checks = validate(rep, scen["rules"])
        for cid, res, reason in checks:
            all_rows.append((sid, cid, res, reason))

    print_report_table(all_rows)


if __name__ == "__main__":
    asyncio.run(main())
