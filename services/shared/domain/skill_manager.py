"""Skill 管理器 - 渐进式披露 Prompt 构建

不依赖数据库，专注于 Skill Prompt 的分层构建与 Token 估算。

层级设计:
  Level 0 (概要):   300 tokens 预算 - 批量注入所有可用 Skill 名称+一句话描述
  Level 1 (完整):  3000 tokens 预算 - 单个 Skill 的完整使用说明 + 典型场景
  Level 2 (深度): 10000 tokens 预算 - 单个 Skill 的深度内容(案例/代码/详细步骤)
"""
from __future__ import annotations

import re
from typing import Any

from common.logger import get_logger

logger = get_logger(__name__)


class SkillManager:
    """Skill Prompt 构建与 Token 估算管理器"""

    LEVEL_TOKEN_BUDGET: dict[int, int] = {
        0: 300,
        1: 3000,
        2: 10000,
    }

    _CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\U00020000-\U0002a6df"
                         r"\U0002a700-\U0002b73f\U0002b740-\U0002b81f"
                         r"\U0002b820-\U0002ceaf\uf900-\ufaff]")
    _EN_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_']*")

    @classmethod
    def estimate_tokens(cls, text: str) -> int:
        """粗略估算文本 Token 数

        估算规则:
          - 中文字符(含CJK扩展区): 1 token / 字
          - 英文单词: 约 0.5 token / 词 (即 2 词约 1 token)
          - 数字/标点/符号: 忽略或极少，可忽略不计

        Args:
            text: 待估算的文本

        Returns:
            估算出的 token 数量 (>= 0)
        """
        if not text:
            return 0
        cjk_count = len(cls._CJK_RE.findall(text))
        en_words = cls._EN_WORD_RE.findall(text)
        en_word_count = len(en_words)
        en_tokens = max(1, int(en_word_count / 2 + 0.5)) if en_word_count > 0 else 0
        total = cjk_count + en_tokens
        if total <= 0 and len(text.strip()) > 0:
            return max(1, len(text) // 4)
        return total

    @classmethod
    def build_skill_prompt_level0(cls, skills: list) -> str:
        """为多个 Skill 构建 Level 0 概要注入文本

        Level 0 定位：所有可用 Skill 的索引目录，预算 ~300 tokens。
        仅展示「名称 + 一句话描述 + 分类/标签关键字」，供 LLM 决策
        "是否需要深入使用某个 Skill"。

        Args:
            skills: Skill 对象列表，每项为 dict 或对象，应包含:
                    name, description(可选), category(可选), tags(可选), version(可选)

        Returns:
            Level 0 概要 Prompt 文本
        """
        if not skills:
            return "【可用技能目录】\n（当前未绑定任何技能）"

        lines: list[str] = []
        lines.append("【可用技能目录 (Level 0 概要)】")
        lines.append("提示：以下为所有已启用的技能索引。如需调用，请根据技能名称进一步加载对应层级的详细说明。")
        lines.append("")

        for idx, skill in enumerate(skills, start=1):
            name = cls._attr(skill, "name", f"skill_{idx}")
            description = cls._attr(skill, "description", "") or ""
            description = description.strip()
            if len(description) > 80:
                description = description[:77] + "..."
            category = cls._attr(skill, "category", "") or ""
            tags = cls._attr(skill, "tags", None)
            tag_text = ""
            if tags and isinstance(tags, list):
                tag_strs = [str(t) for t in tags if str(t).strip()]
                if tag_strs:
                    tag_text = " [#" + ", #".join(tag_strs[:3]) + "]"
            version = cls._attr(skill, "version", "") or ""
            version_text = f" (v{version})" if version else ""
            cat_text = f"[{category}] " if category else ""
            line = f"  {idx}. {name}{version_text} - {cat_text}{description}{tag_text}"
            lines.append(line.strip())

        lines.append("")
        lines.append("使用建议：")
        lines.append("  1) 先浏览名称+描述判断相关性；")
        lines.append("  2) 确认要使用某技能时，显式请求加载 Level 1 (完整说明) 或 Level 2 (深度细节)。")

        prompt = "\n".join(lines)
        budget = cls.LEVEL_TOKEN_BUDGET.get(0, 300)
        actual = cls.estimate_tokens(prompt)
        if actual > budget:
            logger.info(
                f"Level0 Skill Prompt tokens={actual} 超过预算 {budget}, "
                f"skill_count={len(skills)}"
            )
        return prompt

    @classmethod
    def build_skill_prompt_level1(cls, skill_name: str, levels_data: list) -> str:
        """构建单个 Skill 的 Level 1 完整说明

        Level 1 定位：单个 Skill 的完整使用说明书，预算 ~3000 tokens。
        内容包含：概述 + Level 0 概要 + Level 1 完整内容 + 使用边界/注意事项。

        Args:
            skill_name: 技能名称
            levels_data: SkillLevel 列表，每项含 level(int)、name(str,可选)、
                         content(str)、token_count(int,可选)

        Returns:
            Level 1 Prompt 文本 (至少包含 Level 0 + Level 1 内容)
        """
        level_map = cls._group_levels(levels_data)
        budget = cls.LEVEL_TOKEN_BUDGET.get(1, 3000)

        lines: list[str] = []
        lines.append(f"【技能完整说明 (Level 1) - {skill_name}】")
        lines.append("=" * 50)
        lines.append("")

        level0 = level_map.get(0)
        if level0:
            lines.append(f"■ 层级 0 - {level0.get('name') or '概要索引'}")
            lines.append(cls._indent(level0.get("content") or "", indent="  "))
            lines.append("")

        level1 = level_map.get(1)
        if level1:
            lines.append(f"■ 层级 1 - {level1.get('name') or '完整使用说明'}")
            content = level1.get("content") or ""
            content = cls._truncate_to_token_budget(content, budget)
            lines.append(cls._indent(content, indent="  "))
            lines.append("")
        else:
            lines.append("■ 层级 1 - 完整使用说明")
            lines.append("  （本技能未提供 Level 1 内容，建议结合 Level 0 概要自行推理或请求加载 Level 2）")
            lines.append("")

        lines.append("【使用边界与注意事项】")
        lines.append("  - 本说明为 Level 1 标准粒度；若涉及复杂案例/代码级细节，请请求加载 Level 2。")
        lines.append("  - 执行时请严格遵循技能描述中的参数约定与前置条件。")
        lines.append("  - 如产生不确定结果，先确认输入数据，再考虑切换到 Level 2 深度说明。")

        prompt = "\n".join(lines)
        actual = cls.estimate_tokens(prompt)
        if actual > budget:
            logger.warning(
                f"Level1 Skill Prompt tokens={actual} 超过预算 {budget}, "
                f"skill={skill_name}"
            )
        return prompt

    @classmethod
    def build_skill_prompt_level2(cls, skill_name: str, levels_data: list) -> str:
        """构建单个 Skill 的 Level 2 深度说明

        Level 2 定位：单个 Skill 的深度内容，预算 ~10000 tokens。
        内容包含：Level 0 概要 + Level 1 完整说明 + Level 2 深度细节
        （案例/代码/详细步骤/常见问题等）。

        Args:
            skill_name: 技能名称
            levels_data: SkillLevel 列表，每项含 level(int)、name(str,可选)、
                         content(str)、token_count(int,可选)

        Returns:
            Level 2 Prompt 文本 (包含 Level 0+1+2 全部内容，按预算裁剪)
        """
        level_map = cls._group_levels(levels_data)
        budget = cls.LEVEL_TOKEN_BUDGET.get(2, 10000)

        lines: list[str] = []
        lines.append(f"【技能深度说明 (Level 2) - {skill_name}】")
        lines.append("=" * 60)
        lines.append("")

        used_tokens = cls.estimate_tokens("\n".join(lines))

        for lv in (0, 1, 2):
            level_data = level_map.get(lv)
            if not level_data:
                if lv == 2:
                    lines.append(f"■ 层级 {lv} - 深度细节")
                    lines.append("  （本技能未提供 Level 2 深度内容，请基于 Level 1 说明执行）")
                    lines.append("")
                continue
            title = level_data.get("name") or (
                "概要索引" if lv == 0 else
                "完整使用说明" if lv == 1 else
                "深度细节/案例/代码"
            )
            lines.append(f"■ 层级 {lv} - {title}")
            content = level_data.get("content") or ""
            remaining_budget = max(100, budget - used_tokens - 200)
            content = cls._truncate_to_token_budget(content, remaining_budget)
            lines.append(cls._indent(content, indent="  "))
            lines.append("")
            used_tokens = cls.estimate_tokens("\n".join(lines))

        lines.append("【执行提示】")
        lines.append("  - 已提供本技能全部层级的内容，请按任务复杂度选取所需细节。")
        lines.append("  - 若仍存在信息不足，请结合实际推理并在结果中注明假设。")

        prompt = "\n".join(lines)
        actual = cls.estimate_tokens(prompt)
        if actual > budget:
            logger.warning(
                f"Level2 Skill Prompt tokens={actual} 超过预算 {budget}, "
                f"skill={skill_name}"
            )
        return prompt

    # ── 内部工具 ──────────────────────────────────────────

    @staticmethod
    def _attr(obj: Any, key: str, default: Any = None) -> Any:
        """兼容 dict / 对象 属性读取"""
        if obj is None:
            return default
        if isinstance(obj, dict):
            val = obj.get(key, default)
            return default if val is None else val
        val = getattr(obj, key, default)
        return default if val is None else val

    @classmethod
    def _group_levels(cls, levels_data: list) -> dict[int, dict]:
        """将 SkillLevel 列表按 level 分组为 dict"""
        result: dict[int, dict] = {}
        if not levels_data:
            return result
        for item in levels_data:
            lv = cls._attr(item, "level", None)
            if lv is None:
                continue
            try:
                lv_int = int(lv)
            except (TypeError, ValueError):
                continue
            result[lv_int] = {
                "name": cls._attr(item, "name", "") or "",
                "content": cls._attr(item, "content", "") or "",
                "token_count": cls._attr(item, "token_count", 0) or 0,
            }
        return result

    @classmethod
    def _truncate_to_token_budget(cls, text: str, budget: int) -> str:
        """按 token 预算截断文本（末尾加省略提示）"""
        if budget <= 0 or not text:
            return ""
        current_tokens = cls.estimate_tokens(text)
        if current_tokens <= budget:
            return text
        reserve = max(20, budget // 10)
        target = max(10, budget - reserve)
        left, right = 0, len(text)
        best_pos = 0
        while left <= right:
            mid = (left + right) // 2
            sub = text[:mid]
            t = cls.estimate_tokens(sub)
            if t <= target:
                best_pos = mid
                left = mid + 1
            else:
                right = mid - 1
        if best_pos <= 0:
            return text[:max(1, budget)] + "..."
        truncated = text[:best_pos]
        sep_candidates = ["\n\n", "\n", "。", ".", " ", ""]
        for sep in sep_candidates:
            if sep and sep in truncated:
                cut = truncated.rfind(sep)
                if cut > len(truncated) // 2:
                    truncated = truncated[:cut]
                    break
        return truncated + "\n  ... (内容过长已按预算截断，需要完整内容请分段加载)"

    @staticmethod
    def _indent(text: str, indent: str = "  ") -> str:
        """为多行文本统一添加缩进 (保留空行)"""
        if not text:
            return indent + "（无内容）"
        lines = text.splitlines()
        if not lines:
            return indent + "（无内容）"
        return "\n".join((indent + line) if line.strip() else line for line in lines)
