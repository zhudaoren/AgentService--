"""Skill 管理路由 - CRUD + 导入 + 渐进式披露"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, UploadFile, File, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from common.schemas import (
    ApiResponse,
    PageData,
    SkillCreate,
    SkillUpdate,
    SkillOut,
    SkillLevelOut,
    SkillOnlineImport,
    SkillProgressiveResponse,
)
from infrastructure.db import get_db
from services.skill_service import skill_service, skill_import_service

skill_router = APIRouter()


class ToggleSkillRequest(BaseModel):
    enabled: bool


@skill_router.get("/skills", response_model=ApiResponse)
async def list_skills(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = None,
    category: Optional[str] = None,
    source: Optional[str] = None,
    enabled: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
):
    """Skill 列表查询（支持 keyword/category/source/enabled 过滤）"""
    items, total = await skill_service.list(
        db,
        page=page,
        page_size=page_size,
        keyword=keyword,
        category=category,
        source=source,
        enabled=enabled,
    )
    page_data = PageData(
        items=[i.model_dump() for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(data=page_data.model_dump())


@skill_router.post("/skills", response_model=ApiResponse)
async def create_skill(
    payload: SkillCreate,
    db: AsyncSession = Depends(get_db),
):
    """手动创建 Skill（含 levels 数组一并写入）"""
    skill = await skill_service.create(db, payload)
    return ApiResponse(data=skill.model_dump())


@skill_router.get("/skills/{skill_id}", response_model=ApiResponse)
async def get_skill(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取 Skill 详情（含 levels 嵌套）"""
    skill = await skill_service.get(db, skill_id, with_levels=True)
    return ApiResponse(data=skill.model_dump())


@skill_router.put("/skills/{skill_id}", response_model=ApiResponse)
async def update_skill(
    skill_id: str,
    payload: SkillUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新 Skill"""
    skill = await skill_service.update(db, skill_id, payload)
    return ApiResponse(data=skill.model_dump())


@skill_router.delete("/skills/{skill_id}", response_model=ApiResponse)
async def delete_skill(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除 Skill"""
    await skill_service.delete(db, skill_id)
    return ApiResponse(message="删除成功")


@skill_router.post("/skills/{skill_id}/toggle", response_model=ApiResponse)
async def toggle_skill(
    skill_id: str,
    payload: ToggleSkillRequest,
    db: AsyncSession = Depends(get_db),
):
    """启用/禁用 Skill"""
    skill = await skill_service.toggle(db, skill_id, payload.enabled)
    return ApiResponse(data=skill.model_dump())


@skill_router.get("/skills/{skill_id}/levels", response_model=ApiResponse)
async def list_skill_levels(
    skill_id: str,
    db: AsyncSession = Depends(get_db),
):
    """列出 Skill 的 levels 列表"""
    levels = await skill_service.list_levels(db, skill_id)
    return ApiResponse(data=[l.model_dump() for l in levels])


@skill_router.post("/skills/import/local", response_model=ApiResponse)
async def import_skill_local(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """本地文件导入：支持 .md/.json/.skill/.txt/.zip（多文件结构）"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="缺少文件名")
    allowed_exts = (".md", ".json", ".skill", ".txt", ".zip")
    if not file.filename.lower().endswith(allowed_exts):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型，仅支持: {', '.join(allowed_exts)}。.zip 用于导入多文件结构 Skill",
        )
    content_bytes = await file.read()
    content_type = file.content_type or ""
    skill = await skill_import_service.import_from_file(
        db,
        filename=file.filename,
        content_bytes=content_bytes,
        content_type=content_type,
    )
    return ApiResponse(data=skill.model_dump())


@skill_router.post("/skills/import/online", response_model=ApiResponse)
async def import_skill_online(
    payload: SkillOnlineImport,
    import_format: str = Query("markdown", description="markdown/json/skill"),
    db: AsyncSession = Depends(get_db),
):
    """在线导入：通过 URL 拉取 markdown/json/skill 内容"""
    fmt = (import_format or "markdown").lower()
    if fmt not in ("markdown", "json", "skill"):
        fmt = "markdown"
    skill = await skill_import_service.import_from_url(
        db,
        source_url=payload.source_url,
        import_format=fmt,
    )
    return ApiResponse(data=skill.model_dump())


@skill_router.get("/skills/{skill_id}/progressive", response_model=ApiResponse)
async def get_skill_progressive(
    skill_id: str,
    level: int = Query(0, ge=0, le=2, description="0=概要, 1=完整, 2=深度"),
    db: AsyncSession = Depends(get_db),
):
    """渐进式披露：按 level 返回 Skill Prompt"""
    result = await skill_service.get_progressive(db, skill_id, level)
    return ApiResponse(data=result.model_dump())
