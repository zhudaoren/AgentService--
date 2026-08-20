"""OAuth 2.1 路由 - MCP OAuth 授权流程

端点:
  POST /mcp-services/{id}/oauth/discover   - 发现授权服务器元数据
  POST /mcp-services/{id}/oauth/authorize  - 发起 OAuth 授权 (返回授权 URL)
  GET  /oauth/callback                     - OAuth 回调处理
  POST /mcp-services/{id}/oauth/refresh    - 刷新令牌
  POST /mcp-services/{id}/oauth/revoke     - 撤销授权
  GET  /mcp-services/{id}/oauth/status     - 查询 OAuth 状态
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from common.schemas import ApiResponse
from common.config import settings
from common.logger import get_logger
from infrastructure.db import get_db
from services.oauth_service import oauth_service, OAUTH_STATUS_AUTHORIZED

logger = get_logger("oauth-router")

oauth_router = APIRouter()


class AuthorizeRequest(BaseModel):
    """发起授权请求"""
    callback_base_url: Optional[str] = None  # 可选, 默认从请求推断


class OAuthConfigUpdate(BaseModel):
    """手动配置 OAuth 参数"""
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    scopes: Optional[list[str]] = None
    auth_server_url: Optional[str] = None


@oauth_router.post("/mcp-services/{mcp_id}/oauth/discover", response_model=ApiResponse)
async def oauth_discover(
    mcp_id: str,
    db: AsyncSession = Depends(get_db),
):
    """发现授权服务器元数据 (RFC 9728 + RFC 8414)

    从 MCP 服务器获取 Protected Resource Metadata,
    然后获取 Authorization Server Metadata.
    """
    from sqlalchemy import select
    from domain.models import MCPService

    result = await db.execute(select(MCPService).where(MCPService.id == mcp_id))
    mcp = result.scalar_one_or_none()
    if not mcp:
        return ApiResponse(code=404, message="MCP 服务不存在")

    if not mcp.sse_url:
        return ApiResponse(code=1001, message="MCP 服务器 URL 为空")

    try:
        metadata = await oauth_service.discover_auth_server(mcp.sse_url)

        # 保存到 oauth_config
        oauth_config = mcp.oauth_config or {}
        oauth_config.update(metadata)

        from sqlalchemy import update
        await db.execute(
            update(MCPService)
            .where(MCPService.id == mcp_id)
            .values(oauth_config=oauth_config)
        )
        await db.commit()

        return ApiResponse(data=metadata)
    except Exception as e:
        logger.error(f"OAuth 发现失败: {e}", exc_info=True)
        return ApiResponse(code=2000, message=f"OAuth 发现失败: {e}")


@oauth_router.post("/mcp-services/{mcp_id}/oauth/config", response_model=ApiResponse)
async def oauth_update_config(
    mcp_id: str,
    payload: OAuthConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    """手动配置 OAuth 参数 (client_id, client_secret, scopes 等)"""
    from sqlalchemy import select, update
    from domain.models import MCPService

    result = await db.execute(select(MCPService).where(MCPService.id == mcp_id))
    mcp = result.scalar_one_or_none()
    if not mcp:
        return ApiResponse(code=404, message="MCP 服务不存在")

    oauth_config = mcp.oauth_config or {}
    if payload.client_id is not None:
        oauth_config["client_id"] = payload.client_id
    if payload.client_secret is not None:
        oauth_config["client_secret"] = payload.client_secret
    if payload.scopes is not None:
        oauth_config["scopes"] = payload.scopes
    if payload.auth_server_url is not None:
        oauth_config["auth_server_url"] = payload.auth_server_url

    await db.execute(
        update(MCPService)
        .where(MCPService.id == mcp_id)
        .values(oauth_config=oauth_config)
    )
    await db.commit()

    return ApiResponse(data=oauth_config)


@oauth_router.post("/mcp-services/{mcp_id}/oauth/authorize", response_model=ApiResponse)
async def oauth_authorize(
    mcp_id: str,
    request: Request,
    payload: Optional[AuthorizeRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """发起 OAuth 2.1 + PKCE 授权流程

    返回授权 URL, 前端应在新窗口/标签页中打开此 URL.
    """
    # 确定 callback_base_url
    if payload and payload.callback_base_url:
        callback_base_url = payload.callback_base_url
    else:
        # 从请求推断
        base_url = str(request.base_url)
        callback_base_url = base_url.rstrip("/")

    try:
        result = await oauth_service.start_authorization(
            db, mcp_id, callback_base_url
        )
        return ApiResponse(data=result)
    except Exception as e:
        logger.error(f"OAuth 授权发起失败: {e}", exc_info=True)
        return ApiResponse(code=2000, message=f"OAuth 授权发起失败: {e}")


@oauth_router.get("/oauth/callback")
async def oauth_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """OAuth 2.1 回调处理

    授权服务器在用户授权后重定向到此端点.
    处理令牌交换, 然后重定向到前端结果页面.
    """
    logger.info(
        f"OAuth 回调: code={'***' if code else 'None'}, state={state[:8] if state else 'None'}..., "
        f"error={error}"
    )

    try:
        result = await oauth_service.handle_callback(
            db,
            code=code or "",
            state=state or "",
            error=error,
            error_description=error_description,
        )

        mcp_id = result.get("mcp_id", "")
        status = result.get("status", "error")
        error_msg = result.get("error", "")

        # 返回 HTML 页面, 通知前端授权结果
        # 前端可通过 postMessage 或轮询获取结果
        if status == "authorized":
            html = f"""
            <!DOCTYPE html>
            <html>
            <head><meta charset="utf-8"><title>OAuth 授权结果</title></head>
            <body>
            <script>
              window.opener && window.opener.postMessage({{
                type: 'oauth_callback',
                status: 'authorized',
                mcp_id: '{mcp_id}'
              }}, '*');
              document.write('<div style="text-align:center;padding:60px;font-family:sans-serif">' +
                '<h2 style="color:#52c41a">✓ 授权成功</h2>' +
                '<p>MCP 服务已成功授权, 您可以关闭此窗口.</p></div>');
              setTimeout(function() {{ window.close(); }}, 3000);
            </script>
            </body>
            </html>
            """
        else:
            html = f"""
            <!DOCTYPE html>
            <html>
            <head><meta charset="utf-8"><title>OAuth 授权结果</title></head>
            <body>
            <script>
              window.opener && window.opener.postMessage({{
                type: 'oauth_callback',
                status: 'error',
                mcp_id: '{mcp_id}',
                error: {repr(error_msg)}
              }}, '*');
              document.write('<div style="text-align:center;padding:60px;font-family:sans-serif">' +
                '<h2 style="color:#ff4d4f">✗ 授权失败</h2>' +
                '<p>{error_msg or "未知错误"}</p></div>');
            </script>
            </body>
            </html>
            """
        return HTMLResponse(content=html)
    except Exception as e:
        logger.error(f"OAuth 回调处理失败: {e}", exc_info=True)
        html = f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="utf-8"><title>OAuth 授权结果</title></head>
        <body>
        <script>
          window.opener && window.opener.postMessage({{
            type: 'oauth_callback',
            status: 'error',
            error: {repr(str(e))}
          }}, '*');
        </script>
        <div style="text-align:center;padding:60px;font-family:sans-serif">
          <h2 style="color:#ff4d4f">✗ 授权失败</h2>
          <p>{e}</p>
        </div>
        </body>
        </html>
        """
        return HTMLResponse(content=html)


@oauth_router.post("/mcp-services/{mcp_id}/oauth/refresh", response_model=ApiResponse)
async def oauth_refresh(
    mcp_id: str,
    db: AsyncSession = Depends(get_db),
):
    """手动刷新 OAuth 令牌"""
    try:
        result = await oauth_service.refresh_token(db, mcp_id)
        return ApiResponse(data=result)
    except Exception as e:
        logger.error(f"OAuth 令牌刷新失败: {e}", exc_info=True)
        return ApiResponse(code=2000, message=f"令牌刷新失败: {e}")


@oauth_router.post("/mcp-services/{mcp_id}/oauth/revoke", response_model=ApiResponse)
async def oauth_revoke(
    mcp_id: str,
    db: AsyncSession = Depends(get_db),
):
    """撤销 OAuth 授权"""
    try:
        result = await oauth_service.revoke(db, mcp_id)
        return ApiResponse(data=result)
    except Exception as e:
        logger.error(f"OAuth 撤销失败: {e}", exc_info=True)
        return ApiResponse(code=2000, message=f"撤销失败: {e}")


@oauth_router.get("/mcp-services/{mcp_id}/oauth/status", response_model=ApiResponse)
async def oauth_status(
    mcp_id: str,
    db: AsyncSession = Depends(get_db),
):
    """查询 OAuth 授权状态"""
    from sqlalchemy import select
    from domain.models import MCPService

    result = await db.execute(select(MCPService).where(MCPService.id == mcp_id))
    mcp = result.scalar_one_or_none()
    if not mcp:
        return ApiResponse(code=404, message="MCP 服务不存在")

    oauth_tokens = mcp.oauth_tokens or {}
    import time
    expires_at = oauth_tokens.get("expires_at", 0)
    is_expired = expires_at > 0 and time.time() >= expires_at

    # 令牌加密状态 + 受众验证告警
    is_encrypted = bool(oauth_tokens.get("_encrypted"))
    audience_warning = oauth_tokens.get("audience_warning", "")

    return ApiResponse(data={
        "oauth_status": mcp.oauth_status,
        "oauth_config": mcp.oauth_config or {},
        "has_access_token": bool(oauth_tokens.get("access_token")),
        "has_refresh_token": bool(oauth_tokens.get("refresh_token")),
        "expires_at": expires_at,
        "is_expired": is_expired,
        "scope": oauth_tokens.get("scope", ""),
        "encrypted": is_encrypted,
        "audience_warning": audience_warning,
        "audience_valid": not bool(audience_warning),
    })
