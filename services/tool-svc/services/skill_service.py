"""Skill 业务服务 - CRUD + 导入 + 渐进式披露"""
from __future__ import annotations

import json
import os
import re
import uuid
import zipfile
import io
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select, func, or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from common.exceptions import (
    NotFoundException,
    ValidationException,
    BadRequestException,
)
from common.logger import get_logger
from common.schemas import (
    SkillCreate,
    SkillUpdate,
    SkillOut,
    SkillLevelOut,
    SkillProgressiveResponse,
)
from domain.models import Skill, SkillLevel
from domain.skill_manager import SkillManager

logger = get_logger(__name__)

UPLOAD_ROOT = "/workspace/agent-service-platform/data/skills_uploads"


class SkillServiceMgr:
    """Skill 业务服务（单例）"""

    async def list(
        self,
        db: AsyncSession,
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
        category: Optional[str] = None,
        source: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> tuple[list[SkillOut], int]:
        conditions = []
        if keyword:
            like = f"%{keyword}%"
            conditions.append(or_(
                Skill.name.like(like),
                Skill.description.like(like),
            ))
        if category:
            conditions.append(Skill.category == category)
        if source:
            conditions.append(Skill.source == source)
        if enabled is not None:
            conditions.append(Skill.enabled == enabled)

        count_stmt = select(func.count(Skill.id))
        for c in conditions:
            count_stmt = count_stmt.where(c)
        total = (await db.execute(count_stmt)).scalar() or 0

        list_stmt = (
            select(Skill)
            .options(selectinload(Skill.levels))
            .order_by(Skill.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        for c in conditions:
            list_stmt = list_stmt.where(c)
        result = await db.execute(list_stmt)
        items = result.scalars().all()
        outs = [self._to_out(s, with_levels=True) for s in items]
        return outs, total

    async def create(
        self, db: AsyncSession, payload: SkillCreate
    ) -> SkillOut:
        skill_id = uuid.uuid4().hex
        skill = Skill(
            id=skill_id,
            name=payload.name,
            description=payload.description or "",
            category=payload.category or "general",
            version=payload.version or "1.0.0",
            source=payload.source or "local",
            source_url=payload.source_url or "",
            storage_path="",
            enabled=payload.enabled if payload.enabled is not None else True,
            usage_count=0,
            success_rate=0.0,
            author=payload.author or "",
            tags=payload.tags or [],
        )
        db.add(skill)

        levels = payload.levels or []
        for lv_data in levels:
            if isinstance(lv_data, dict):
                level = lv_data.get("level")
                name = lv_data.get("name", "") or ""
                content = lv_data.get("content", "") or ""
            else:
                level = getattr(lv_data, "level", None)
                name = getattr(lv_data, "name", "") or ""
                content = getattr(lv_data, "content", "") or ""
            if level is None or not content:
                continue
            level_obj = SkillLevel(
                id=uuid.uuid4().hex,
                skill_id=skill_id,
                level=int(level),
                name=name,
                content=content,
                token_count=SkillManager.estimate_tokens(content),
            )
            db.add(level_obj)

        await db.flush()
        logger.info(f"创建Skill: id={skill_id}, name={payload.name}")
        skill = await self._get_by_id(db, skill_id, with_levels=True)
        return self._to_out(skill, with_levels=True)

    async def get(
        self, db: AsyncSession, skill_id: str, with_levels: bool = True
    ) -> SkillOut:
        skill = await self._get_by_id(db, skill_id, with_levels=with_levels)
        return self._to_out(skill, with_levels=with_levels)

    async def update(
        self, db: AsyncSession, skill_id: str, payload: SkillUpdate
    ) -> SkillOut:
        skill = await self._get_by_id(db, skill_id, with_levels=True)
        data = payload.model_dump(exclude_unset=True)
        for k, v in data.items():
            setattr(skill, k, v)
        await db.flush()
        logger.info(f"更新Skill: id={skill_id}")
        return self._to_out(skill, with_levels=True)

    async def delete(self, db: AsyncSession, skill_id: str) -> None:
        skill = await self._get_by_id(db, skill_id, with_levels=False)
        await db.delete(skill)
        await db.flush()
        logger.info(f"删除Skill: id={skill_id}")

    async def toggle(
        self, db: AsyncSession, skill_id: str, enabled: bool
    ) -> SkillOut:
        skill = await self._get_by_id(db, skill_id, with_levels=True)
        skill.enabled = enabled
        await db.flush()
        logger.info(f"Skill启用状态变更: id={skill_id}, enabled={enabled}")
        return self._to_out(skill, with_levels=True)

    async def increment_usage(
        self, db: AsyncSession, skill_id: str, success: bool
    ) -> SkillOut:
        """原子更新 Skill usage_count / success_count / success_rate。

        使用原生 SQL UPDATE 避免并发下竞态，然后 re-query 返回最新 SkillOut。
        """
        delta = 1 if success else 0
        stmt = text(
            """
            UPDATE skills
            SET usage_count   = usage_count + 1,
                success_count = success_count + :delta,
                success_rate  = IF(usage_count + 1 > 0,
                                    (success_count + :delta) / (usage_count + 1),
                                    0)
            WHERE id = :id
            """
        )
        result = await db.execute(stmt, {"delta": delta, "id": skill_id})
        await db.flush()
        if result.rowcount == 0:
            raise NotFoundException("Skill不存在")
        skill = await self._get_by_id(db, skill_id, with_levels=False)
        logger.info(
            f"Skill使用统计累计: id={skill_id}, success={success}, "
            f"usage_count={skill.usage_count}, success_count={skill.success_count}, "
            f"success_rate={skill.success_rate}"
        )
        return self._to_out(skill, with_levels=False)

    async def list_levels(
        self, db: AsyncSession, skill_id: str
    ) -> list[SkillLevelOut]:
        _ = await self._get_by_id(db, skill_id, with_levels=False)
        stmt = (
            select(SkillLevel)
            .where(SkillLevel.skill_id == skill_id)
            .order_by(SkillLevel.level.asc())
        )
        result = await db.execute(stmt)
        levels = result.scalars().all()
        return [self._level_to_out(lv) for lv in levels]

    async def get_progressive(
        self, db: AsyncSession, skill_id: str, level: int
    ) -> SkillProgressiveResponse:
        skill = await self._get_by_id(db, skill_id, with_levels=True)
        levels_data = []
        for lv in skill.levels or []:
            levels_data.append({
                "level": lv.level,
                "name": lv.name or "",
                "content": lv.content or "",
                "token_count": lv.token_count or 0,
            })
        if level == 0:
            prompt_text = SkillManager.build_skill_prompt_level0([skill])
        elif level == 1:
            prompt_text = SkillManager.build_skill_prompt_level1(skill.name, levels_data)
        else:
            prompt_text = SkillManager.build_skill_prompt_level2(skill.name, levels_data)
        actual_tokens = SkillManager.estimate_tokens(prompt_text)
        budget_tokens = SkillManager.LEVEL_TOKEN_BUDGET.get(level, 300)
        return SkillProgressiveResponse(
            skill_id=skill.id,
            skill_name=skill.name,
            requested_level=level,
            prompt_text=prompt_text,
            actual_tokens=actual_tokens,
            budget_tokens=budget_tokens,
        )

    # ── 内部工具 ──────────────────────────────────────

    async def _get_by_id(
        self, db: AsyncSession, skill_id: str, with_levels: bool = True
    ) -> Skill:
        stmt = select(Skill)
        if with_levels:
            stmt = stmt.options(selectinload(Skill.levels))
        stmt = stmt.where(Skill.id == skill_id)
        result = await db.execute(stmt)
        skill = result.scalar_one_or_none()
        if not skill:
            raise NotFoundException(f"Skill不存在: {skill_id}")
        return skill

    def _to_out(self, skill: Skill, with_levels: bool = True) -> SkillOut:
        levels_out = []
        if with_levels and skill.levels:
            for lv in skill.levels:
                levels_out.append(self._level_to_out(lv))
        return SkillOut(
            id=skill.id,
            name=skill.name,
            description=skill.description or "",
            category=skill.category or "general",
            version=skill.version or "1.0.0",
            source=skill.source or "local",
            source_url=skill.source_url or "",
            storage_path=skill.storage_path or "",
            enabled=bool(skill.enabled),
            usage_count=skill.usage_count or 0,
            success_count=skill.success_count or 0,
            success_rate=skill.success_rate or 0.0,
            author=skill.author or "",
            tags=skill.tags or [],
            levels=levels_out,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
        )

    def _level_to_out(self, level: SkillLevel) -> SkillLevelOut:
        return SkillLevelOut(
            id=level.id,
            skill_id=level.skill_id,
            level=level.level,
            name=level.name or "",
            content=level.content or "",
            token_count=level.token_count or 0,
            created_at=level.created_at,
        )


skill_service = SkillServiceMgr()


class SkillImportService:
    """Skill 导入服务（本地文件 + 在线 URL）"""

    @staticmethod
    def _init_storage() -> None:
        """创建本地 skills_uploads 目录"""
        try:
            if not os.path.exists(UPLOAD_ROOT):
                os.makedirs(UPLOAD_ROOT, exist_ok=True)
                logger.info(f"Skill上传目录已创建: {UPLOAD_ROOT}")
            else:
                logger.info(f"Skill上传目录已存在: {UPLOAD_ROOT}")
        except Exception as e:
            logger.error(f"创建Skill上传目录失败: {e}")

    async def import_from_file(
        self,
        db: AsyncSession,
        filename: str,
        content_bytes: bytes,
        content_type: str,
    ) -> SkillOut:
        """从本地文件导入 Skill（支持 .md/.json/.skill/.txt/.zip）"""
        ext = os.path.splitext(filename)[1].lower()

        if ext == ".zip":
            return await self._import_from_zip(db, filename, content_bytes)

        try:
            text = content_bytes.decode("utf-8", errors="replace")
        except Exception as e:
            raise ValidationException(f"文件解码失败: {e}")

        parsed: dict[str, Any] = {}
        if ext == ".json":
            try:
                parsed = json.loads(text)
            except Exception as e:
                raise ValidationException(f"JSON解析失败: {e}")
        else:
            parsed = self._parse_markdown_skill(text)

        name = parsed.get("name") or os.path.splitext(filename)[0]
        description = parsed.get("description", "") or ""
        category = parsed.get("category", "general") or "general"
        author = parsed.get("author", "") or ""
        tags = parsed.get("tags") or []
        body = parsed.get("body", "") or text

        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        date_dir = os.path.join(UPLOAD_ROOT, date_str)
        os.makedirs(date_dir, exist_ok=True)
        safe_uuid = uuid.uuid4().hex
        storage_filename = f"{safe_uuid}_{filename}"
        storage_path = f"local/{date_str}/{storage_filename}"
        full_path = os.path.join(date_dir, storage_filename)
        try:
            with open(full_path, "wb") as f:
                f.write(content_bytes)
        except Exception as e:
            logger.warning(f"保存Skill文件失败(忽略): {e}")

        skill_payload = SkillCreate(
            name=name,
            description=description,
            category=category,
            version="1.0.0",
            source="local",
            source_url="",
            enabled=True,
            author=author,
            tags=tags,
            levels=[],
        )
        skill_out = await skill_service.create(db, skill_payload)

        levels_bodies = self._build_three_levels(name, description, tags, category, body)
        skill_id = skill_out.id
        for lv_idx, (lv_name, lv_content) in enumerate(levels_bodies):
            level_obj = SkillLevel(
                id=uuid.uuid4().hex,
                skill_id=skill_id,
                level=lv_idx,
                name=lv_name,
                content=lv_content,
                token_count=SkillManager.estimate_tokens(lv_content),
            )
            db.add(level_obj)
        await db.flush()

        from sqlalchemy import update as sql_update
        await db.execute(
            sql_update(Skill).where(Skill.id == skill_id).values(storage_path=storage_path)
        )
        await db.flush()

        logger.info(f"Skill本地文件导入成功: id={skill_id}, filename={filename}")
        return await skill_service.get(db, skill_id, with_levels=True)

    async def _import_from_zip(
        self,
        db: AsyncSession,
        filename: str,
        content_bytes: bytes,
    ) -> SkillOut:
        """从 ZIP 文件导入多文件结构 Skill"""
        self._init_storage()
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        date_dir = os.path.join(UPLOAD_ROOT, date_str)
        safe_uuid = uuid.uuid4().hex
        extract_dir = os.path.join(date_dir, safe_uuid)
        storage_path = f"local/{date_str}/{safe_uuid}"

        # 解压 ZIP
        try:
            os.makedirs(extract_dir, exist_ok=True)
            with zipfile.ZipFile(io.BytesIO(content_bytes), 'r') as zf:
                # 安全检查：防止路径穿越
                for name in zf.namelist():
                    if name.startswith('/') or '..' in name:
                        raise BadRequestException(f"ZIP文件包含不安全路径: {name}")
                zf.extractall(extract_dir)
        except zipfile.BadZipFile:
            raise BadRequestException("无效的ZIP文件")
        except BadRequestException:
            raise
        except Exception as e:
            raise BadRequestException(f"ZIP解压失败: {e}")

        # 查找 SKILL.md（支持多层目录）
        skill_md_path = self._find_skill_md(extract_dir)
        if not skill_md_path:
            raise BadRequestException("ZIP中未找到 SKILL.md 文件")

        # 读取并解析 SKILL.md
        try:
            with open(skill_md_path, 'r', encoding='utf-8') as f:
                skill_md_content = f.read()
        except Exception as e:
            raise ValidationException(f"SKILL.md 读取失败: {e}")

        parsed = self._parse_markdown_skill(skill_md_content)

        name = parsed.get("name") or os.path.splitext(filename)[0]
        description = parsed.get("description", "") or ""
        category = parsed.get("category", "general") or "general"
        author = parsed.get("author", "") or ""
        tags = parsed.get("tags") or []
        body = parsed.get("body", "") or skill_md_content

        # 收集附加文件信息
        skill_dir = os.path.dirname(skill_md_path)
        has_scripts = os.path.exists(os.path.join(skill_dir, "scripts"))
        has_references = os.path.exists(os.path.join(skill_dir, "references"))
        has_assets = os.path.exists(os.path.join(skill_dir, "assets"))

        # 构建扩展描述
        extensions = []
        if has_scripts:
            extensions.append("scripts(可执行脚本)")
        if has_references:
            extensions.append("references(参考文档)")
        if has_assets:
            extensions.append("assets(资源文件)")
        if extensions and description:
            description += f" [包含: {', '.join(extensions)}]"
        elif extensions:
            description = f"包含 {', '.join(extensions)} 的技能包"

        # 创建 Skill 记录
        skill_payload = SkillCreate(
            name=name,
            description=description,
            category=category,
            version="1.0.0",
            source="local",
            source_url="",
            enabled=True,
            author=author,
            tags=tags,
            levels=[],
        )
        skill_out = await skill_service.create(db, skill_payload)

        # 构建 3 级 levels（包含扩展文件信息）
        levels_bodies = self._build_three_levels(
            name, description, tags, category, body,
            skill_dir=skill_dir,
            has_scripts=has_scripts,
            has_references=has_references,
            has_assets=has_assets,
        )
        skill_id = skill_out.id
        for lv_idx, (lv_name, lv_content) in enumerate(levels_bodies):
            level_obj = SkillLevel(
                id=uuid.uuid4().hex,
                skill_id=skill_id,
                level=lv_idx,
                name=lv_name,
                content=lv_content,
                token_count=SkillManager.estimate_tokens(lv_content),
            )
            db.add(level_obj)
        await db.flush()

        from sqlalchemy import update as sql_update
        await db.execute(
            sql_update(Skill).where(Skill.id == skill_id).values(storage_path=storage_path)
        )
        await db.flush()

        logger.info(f"Skill ZIP导入成功: id={skill_id}, name={name}, "
                     f"scripts={has_scripts}, references={has_references}, assets={has_assets}")
        return await skill_service.get(db, skill_id, with_levels=True)

    @staticmethod
    def _find_skill_md(root_dir: str) -> Optional[str]:
        """递归查找 SKILL.md 文件"""
        for root, dirs, files in os.walk(root_dir):
            # 跳过 __MACOSX 等系统目录
            dirs[:] = [d for d in dirs if not d.startswith('_')]
            for file in files:
                if file.upper() == "SKILL.MD":
                    return os.path.join(root, file)
        return None

    async def import_from_url(
        self,
        db: AsyncSession,
        source_url: str,
        import_format: str = "markdown",
    ) -> SkillOut:
        """从在线 URL 导入 Skill"""
        if not source_url:
            raise ValidationException("source_url 不能为空")
        try:
            import httpx
        except ImportError:
            raise BadRequestException("httpx 未安装，无法使用在线导入")

        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(source_url)
                resp.raise_for_status()
                content_bytes = resp.content
        except Exception as e:
            raise BadRequestException(f"拉取在线内容失败: {e}")

        fmt = (import_format or "markdown").lower()

        # ZIP 分支：复用 _import_from_zip，再二次 UPDATE 改成 online 标记
        if fmt == "zip":
            from urllib.parse import urlparse as _urlparse
            try:
                filename = os.path.basename(_urlparse(source_url).path) or "online_skill.zip"
            except Exception:
                filename = "online_skill.zip"
            if not filename.lower().endswith(".zip"):
                filename += ".zip"
            skill_out = await self._import_from_zip(db, filename, content_bytes)
            skill_id = skill_out.id
            date_str = datetime.utcnow().strftime("%Y-%m-%d")
            new_uuid = uuid.uuid4().hex
            online_storage_path = f"online/{date_str}/{new_uuid}"
            from sqlalchemy import update as sql_update
            await db.execute(
                sql_update(Skill)
                .where(Skill.id == skill_id)
                .values(
                    source="online",
                    source_url=source_url,
                    storage_path=online_storage_path,
                )
            )
            await db.flush()
            logger.info(f"Skill在线ZIP导入成功: id={skill_id}, url={source_url}")
            return await skill_service.get(db, skill_id, with_levels=True)

        # 非 ZIP：解码为文本处理 markdown/json
        try:
            content = content_bytes.decode("utf-8", errors="replace")
        except Exception as e:
            raise ValidationException(f"内容解码失败: {e}")

        parsed: dict[str, Any] = {}
        if fmt == "json":
            try:
                parsed = json.loads(content)
            except Exception as e:
                raise ValidationException(f"JSON解析失败: {e}")
        else:
            parsed = self._parse_markdown_skill(content)

        name = parsed.get("name") or self._name_from_url(source_url)
        description = parsed.get("description", "") or ""
        category = parsed.get("category", "general") or "general"
        author = parsed.get("author", "") or ""
        tags = parsed.get("tags") or []
        body = parsed.get("body", "") or content

        skill_payload = SkillCreate(
            name=name,
            description=description,
            category=category,
            version="1.0.0",
            source="online",
            source_url=source_url,
            enabled=True,
            author=author,
            tags=tags,
            levels=[],
        )
        skill_out = await skill_service.create(db, skill_payload)

        levels_bodies = self._build_three_levels(name, description, tags, category, body)
        skill_id = skill_out.id
        for lv_idx, (lv_name, lv_content) in enumerate(levels_bodies):
            level_obj = SkillLevel(
                id=uuid.uuid4().hex,
                skill_id=skill_id,
                level=lv_idx,
                name=lv_name,
                content=lv_content,
                token_count=SkillManager.estimate_tokens(lv_content),
            )
            db.add(level_obj)
        await db.flush()

        logger.info(f"Skill在线导入成功: id={skill_id}, url={source_url}")
        return await skill_service.get(db, skill_id, with_levels=True)

    # ── 内部工具 ──────────────────────────────────────

    @staticmethod
    def _parse_markdown_skill(text: str) -> dict[str, Any]:
        """简单解析 Markdown Skill：
        - 从 frontmatter YAML 或第一段提取 name/description/tags
        - title = 第一个 # 标题
        - body = 正文
        """
        result: dict[str, Any] = {
            "name": "",
            "description": "",
            "tags": [],
            "category": "general",
            "author": "",
            "body": text,
        }
        if not text:
            return result

        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
        if fm_match:
            fm_text = fm_match.group(1)
            try:
                fm = SkillImportService._simple_yaml(fm_text)
                result["name"] = fm.get("name", "") or ""
                result["description"] = fm.get("description", "") or ""
                result["category"] = fm.get("category", "general") or "general"
                result["author"] = fm.get("author", "") or ""
                tags_raw = fm.get("tags") or fm.get("tag") or []
                if isinstance(tags_raw, str):
                    tags_raw = [t.strip() for t in tags_raw.replace(",", " ").split() if t.strip()]
                if isinstance(tags_raw, list):
                    result["tags"] = [str(t) for t in tags_raw if str(t).strip()]
                body_start = fm_match.end()
                result["body"] = text[body_start:].lstrip()
            except Exception:
                pass

        if not result["name"]:
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("# "):
                    result["name"] = s[2:].strip()
                    break
                elif s.startswith("#"):
                    stripped = s.lstrip("#").strip()
                    if stripped:
                        result["name"] = stripped
                        break

        if not result["description"]:
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            for l in lines[:10]:
                if l.startswith("#"):
                    continue
                if l.lower().startswith("tags:") or l.lower().startswith("tag:"):
                    tag_part = l.split(":", 1)[1].strip()
                    tags_raw = [t.strip() for t in tag_part.replace(",", " ").replace("#", " ").split() if t.strip()]
                    if tags_raw and not result["tags"]:
                        result["tags"] = tags_raw
                    continue
                if 5 < len(l) < 300:
                    result["description"] = l[:200]
                    break

        if not result["name"]:
            result["name"] = "未命名 Skill"
        return result

    @staticmethod
    def _simple_yaml(text: str) -> dict[str, Any]:
        """极简 YAML 解析（支持 key: value 和简单 list），用于 frontmatter"""
        result: dict[str, Any] = {}
        current_key: Optional[str] = None
        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            if not line.strip() or line.strip().startswith("#"):
                continue
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            if indent == 0 and ":" in stripped:
                key, _, value = stripped.partition(":")
                key = key.strip()
                value = value.strip()
                if value == "":
                    result[key] = []
                    current_key = key
                elif (value.startswith("[") and value.endswith("]")):
                    try:
                        result[key] = json.loads(value)
                    except Exception:
                        inner = value[1:-1]
                        result[key] = [v.strip().strip("\"'") for v in inner.split(",") if v.strip()]
                elif value.startswith("- "):
                    result[key] = [value[2:].strip().strip("\"'")]
                    current_key = key
                else:
                    v = value.strip("\"'")
                    if v.lower() == "true":
                        result[key] = True
                    elif v.lower() == "false":
                        result[key] = False
                    else:
                        try:
                            result[key] = int(v)
                        except Exception:
                            try:
                                result[key] = float(v)
                            except Exception:
                                result[key] = v
                    current_key = None
            elif indent > 0 and current_key and stripped.startswith("- "):
                item = stripped[2:].strip().strip("\"'")
                if isinstance(result.get(current_key), list):
                    result[current_key].append(item)
        return result

    @staticmethod
    def _build_three_levels(
        name: str,
        description: str,
        tags: list,
        category: str,
        body: str,
        skill_dir: Optional[str] = None,
        has_scripts: bool = False,
        has_references: bool = False,
        has_assets: bool = False,
    ) -> list[tuple[str, str]]:
        """生成 3 级 levels（支持多文件结构 Skill）"""
        tags_str = ""
        if tags:
            tags_str = " #" + " #".join([str(t) for t in tags[:5]])

        # 构建多文件扩展信息
        extensions_info = []
        if has_scripts and skill_dir:
            scripts_dir = os.path.join(skill_dir, "scripts")
            scripts_files = SkillImportService._list_files(scripts_dir)
            extensions_info.append(f"- **scripts/**: 包含 {len(scripts_files)} 个可执行脚本\n"
                                   f"  - {', '.join(scripts_files[:5])}")
        if has_references and skill_dir:
            refs_dir = os.path.join(skill_dir, "references")
            refs_files = SkillImportService._list_files(refs_dir)
            extensions_info.append(f"- **references**: 包含 {len(refs_files)} 个参考文档\n"
                                   f"  - {', '.join(refs_files[:5])}")
        if has_assets and skill_dir:
            assets_dir = os.path.join(skill_dir, "assets")
            assets_files = SkillImportService._list_files(assets_dir)
            extensions_info.append(f"- **assets**: 包含 {len(assets_files)} 个资源文件\n"
                                   f"  - {', '.join(assets_files[:5])}")

        extensions_block = "\n".join(extensions_info) if extensions_info else ""

        lv0_name = "概要索引"
        lv0_content = (
            f"技能名称: {name}\n"
            f"分类: {category}\n"
            f"简短描述: {description or '无'}\n"
            f"标签: {tags_str.strip() or '无'}\n"
        )
        if extensions_block:
            lv0_content += f"\n扩展文件:\n{extensions_block}\n"
        lv0_content += f"使用提示: 这是技能 {name} 的 Level 0 概要。"

        lv1_name = "完整使用说明"
        main_body = body.strip()
        if len(main_body) > 8000:
            main_body = main_body[:8000] + "\n...(内容较长，完整内容请参见 Level 2)"
        lv1_content = (
            f"# {name} - 完整使用说明\n\n"
            f"## 描述\n{description or name}\n\n"
        )
        if extensions_block:
            lv1_content += f"## 扩展文件结构\n{extensions_block}\n\n"
        lv1_content += f"## 详细内容\n{main_body}"

        advanced, tips, boundary = "", "", ""
        for section_name, section_content in SkillImportService._extract_sections(body).items():
            sn = section_name.lower()
            if any(k in sn for k in ("高级", "进阶", "技巧", "tip", "advanced", "案例", "示例", "example")):
                advanced += f"\n### {section_name}\n{section_content}\n"
            if any(k in sn for k in ("边界", "限制", "注意", "注意事项", "limitation", "注意点", "caution")):
                boundary += f"\n### {section_name}\n{section_content}\n"
        if not advanced:
            advanced = f"\n### 高级技巧\n请结合 Level 1 的使用说明，根据实际场景灵活运用技能 {name}。\n"
        if not boundary:
            boundary = f"\n### 边界与注意事项\n- 使用前请确认输入数据格式正确\n- 如遇异常，请检查参数并重新尝试\n"

        # 读取 references 目录中的文件作为深度补充
        refs_content = ""
        if has_references and skill_dir:
            refs_dir = os.path.join(skill_dir, "references")
            refs_content = SkillImportService._read_references(refs_dir)

        tips_body = body.strip() if body.strip() else description
        if len(tips_body) > 15000:
            tips_body = tips_body[:15000]
        lv2_name = "深度细节 / 高级技巧 / 边界"
        lv2_content = (
            f"# {name} - Level 2 深度说明\n\n"
            f"## 正文详情\n{tips_body}\n\n"
        )
        if extensions_block:
            lv2_content += f"## 扩展文件详情\n{extensions_block}\n\n"
        if refs_content:
            lv2_content += f"## 参考文档内容\n{refs_content}\n\n"
        lv2_content += (
            f"## 高级技巧与案例\n{advanced}\n\n"
            f"## 边界与注意事项\n{boundary}\n"
        )
        return [(lv0_name, lv0_content), (lv1_name, lv1_content), (lv2_name, lv2_content)]

    @staticmethod
    def _list_files(directory: str) -> list[str]:
        """列出目录下的文件名（非递归）"""
        files = []
        try:
            for f in os.listdir(directory):
                if os.path.isfile(os.path.join(directory, f)):
                    files.append(f)
        except Exception:
            pass
        return files

    @staticmethod
    def _read_references(refs_dir: str, max_tokens: int = 5000) -> str:
        """读取 references 目录中的 Markdown 文档"""
        content_parts = []
        try:
            for fname in sorted(os.listdir(refs_dir)):
                if fname.endswith(('.md', '.markdown', '.txt')):
                    fpath = os.path.join(refs_dir, fname)
                    try:
                        with open(fpath, 'r', encoding='utf-8') as f:
                            text = f.read()
                        if len(text) > 2000:
                            text = text[:2000] + "\n...(截断)"
                        content_parts.append(f"### {fname}\n{text}")
                    except Exception:
                        pass
        except Exception:
            pass
        result = "\n\n".join(content_parts)
        if len(result) > max_tokens * 4:
            result = result[:max_tokens * 4] + "\n\n...(按预算截断)"
        return result

    @staticmethod
    def _extract_sections(text: str) -> dict[str, str]:
        """提取 Markdown 中 ## / ### 级别的 section"""
        sections: dict[str, str] = {}
        if not text:
            return sections
        current_title: Optional[str] = None
        current_lines: list[str] = []
        heading_re = re.compile(r"^(#{2,6})\s+(.*)$")
        for line in text.splitlines():
            m = heading_re.match(line)
            if m:
                if current_title is not None:
                    sections[current_title] = "\n".join(current_lines).strip()
                current_title = m.group(2).strip()
                current_lines = []
            else:
                if current_title is not None:
                    current_lines.append(line)
        if current_title is not None:
            sections[current_title] = "\n".join(current_lines).strip()
        return sections

    @staticmethod
    def _name_from_url(url: str) -> str:
        """从 URL 提取一个可读名称"""
        try:
            from urllib.parse import urlparse
            path = urlparse(url).path
            name = os.path.basename(path) or "OnlineSkill"
            name = os.path.splitext(name)[0]
            if name:
                return name.replace("-", " ").replace("_", " ").strip() or "Online Skill"
        except Exception:
            pass
        return "Online Skill"


skill_import_service = SkillImportService()
