"""OAuth 2.1 + PKCE 服务 - 实现 MCP 规范的完整 OAuth 流程

参考规范:
  - OAuth 2.1 IETF DRAFT (draft-ietf-oauth-v2-1-13)
  - RFC 8414: OAuth 2.0 Authorization Server Metadata
  - RFC 7591: OAuth 2.0 Dynamic Client Registration Protocol
  - RFC 7636: PKCE (Proof Key for Code Exchange)
  - RFC 8707: Resource Indicators for OAuth 2.0
  - RFC 9728: OAuth 2.0 Protected Resource Metadata

流程概述:
  1. 发现: 从 MCP 服务器获取 Protected Resource Metadata (RFC 9728)
     → 获取 Authorization Server URL
     → 从 Auth Server 获取 Metadata (RFC 8414)
     → 获取 authorization_endpoint, token_endpoint, registration_endpoint
  2. 动态客户端注册 (可选, RFC 7591):
     → 向 registration_endpoint 发送注册请求
     → 获取 client_id (和可选的 client_secret)
  3. PKCE 生成:
     → 生成 code_verifier (43-128 字符随机串)
     → 计算 code_challenge = BASE64URL(SHA256(code_verifier))
     → code_challenge_method = "S256"
  4. 授权:
     → 构建 authorization URL, 包含:
       response_type=code, client_id, redirect_uri,
       code_challenge, code_challenge_method=S256,
       resource=MCP服务器URL, state, scope
     → 用户在浏览器中授权
  5. 回调 + 令牌交换:
     → Auth Server 重定向回 callback URL, 携带 code 和 state
     → 向 token_endpoint 发送令牌交换请求:
       grant_type=authorization_code, code, redirect_uri,
       client_id, code_verifier, resource
     → 获取 access_token, refresh_token, expires_in
  6. 令牌刷新:
     → access_token 过期后, 使用 refresh_token 获取新的 access_token
  7. 访问 MCP 服务器:
     → 使用 access_token 作为 Bearer Token 访问 MCP 服务器
"""
import secrets
import hashlib
import base64
import json
import time
import uuid
from typing import Optional
from urllib.parse import urlencode, urlparse

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.logger import get_logger
from common.exceptions import AppException, ValidationException
from common.utils.crypto import crypto_service
from domain.models import MCPService

logger = get_logger("oauth-service")

# OAuth 状态常量
OAUTH_STATUS_NOT_CONFIGURED = "not_configured"
OAUTH_STATUS_PENDING = "pending"
OAUTH_STATUS_AUTHORIZED = "authorized"
OAUTH_STATUS_EXPIRED = "expired"
OAUTH_STATUS_ERROR = "error"

# PKCE 参数
PKCE_VERIFIER_LENGTH = 64  # 43-128 字符
PKCE_CHALLENGE_METHOD = "S256"

# 存储进行中的 OAuth 会话 (state → session_data)
# 生产环境应使用 Redis 或数据库, 这里用内存字典 (单实例够用)
_oauth_sessions: dict[str, dict] = {}

# 令牌加密存储标记字段名
ENCRYPTED_FLAG = "_encrypted"
# 需要加密的敏感字段
SENSITIVE_TOKEN_FIELDS = ("access_token", "refresh_token")


class OAuthService:
    """OAuth 2.1 + PKCE 服务"""

    # ── 令牌加密存储 ──────────────────────────────────────

    @staticmethod
    def _encrypt_tokens(tokens: dict) -> dict:
        """加密令牌中的敏感字段 (access_token, refresh_token)

        使用 Fernet 对称加密 (ENCRYPTION_KEY 派生), 存储密文 + 标记字段.
        非敏感字段 (expires_at, scope, token_type 等) 保持明文.
        """
        if not tokens:
            return tokens
        encrypted = dict(tokens)
        for field in SENSITIVE_TOKEN_FIELDS:
            value = encrypted.get(field)
            if value and isinstance(value, str):
                try:
                    encrypted[field] = crypto_service.encrypt(value)
                except Exception as e:
                    logger.error(f"令牌字段加密失败 {field}: {e}")
                    # 加密失败保留明文 (降级), 避免阻断授权流程
        encrypted[ENCRYPTED_FLAG] = True
        return encrypted

    @staticmethod
    def _decrypt_tokens(tokens: dict) -> dict:
        """解密令牌中的敏感字段

        如果检测到 _encrypted 标记, 则解密; 否则视为明文 (兼容历史数据).
        """
        if not tokens:
            return tokens
        decrypted = dict(tokens)
        if not decrypted.get(ENCRYPTED_FLAG):
            # 历史明文数据, 直接返回
            return decrypted
        for field in SENSITIVE_TOKEN_FIELDS:
            value = decrypted.get(field)
            if value and isinstance(value, str):
                try:
                    decrypted[field] = crypto_service.decrypt(value)
                except Exception as e:
                    logger.error(f"令牌字段解密失败 {field}: {e}")
                    # 解密失败返回空字符串, 避免泄露密文
                    decrypted[field] = ""
        return decrypted

    def _get_decrypted_tokens(self, mcp: MCPService) -> dict:
        """从 MCPService 读取并解密 oauth_tokens"""
        return self._decrypt_tokens(mcp.oauth_tokens or {})

    # ── 令牌受众验证 (RFC 8707) ────────────────────────────

    @staticmethod
    def _decode_jwt_payload_unverified(token: str) -> dict:
        """解码 JWT payload (不验证签名, 仅解析 base64)

        用于受众验证场景: 我们信任授权服务器签发的 token,
        仅检查 aud claim 是否包含预期的 resource URL.

        Args:
            token: JWT 字符串 (header.payload.signature)

        Returns:
            payload 字典; 解析失败返回空字典
        """
        if not token or not isinstance(token, str):
            return {}
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        try:
            # JWT 使用 base64url 编码 (无 padding)
            payload_b64 = parts[1]
            # 补齐 padding
            padding = 4 - len(payload_b64) % 4
            if padding != 4:
                payload_b64 += "=" * padding
            payload_bytes = base64.urlsafe_b64decode(payload_b64)
            payload = json.loads(payload_bytes.decode("utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception as e:
            logger.debug(f"JWT payload 解码失败 (可能非 JWT): {e}")
            return {}

    @staticmethod
    def _normalize_url_for_aud(url: str) -> str:
        """规范化 URL 用于受众比对

        去除尾部斜杠, 转小写 host, 保留 scheme+host+port+path.
        """
        if not url:
            return ""
        normalized = url.rstrip("/").lower()
        return normalized

    def validate_token_audience(
        self,
        access_token: str,
        expected_resource: str,
    ) -> tuple[bool, str]:
        """验证 access_token 的受众 (aud) 是否匹配预期的 MCP 资源

        遵循 RFC 8707 (Resource Indicators for OAuth 2.0):
          - 如果 token 是 JWT 且包含 aud claim, 则验证 aud 是否包含 expected_resource
          - 如果 token 不是 JWT 或无 aud claim, 则跳过验证 (兼容性, 不阻断)
          - 如果 aud 存在但不匹配, 返回失败

        Args:
            access_token: access_token 字符串 (可能是 JWT 或不透明 token)
            expected_resource: 预期的资源 URL (RFC 8707 resource 参数值)

        Returns:
            (is_valid, message): 是否通过验证 + 说明信息
        """
        if not access_token or not expected_resource:
            # 缺少参数, 跳过验证
            return True, "跳过受众验证 (缺少 token 或 resource)"

        payload = self._decode_jwt_payload_unverified(access_token)
        if not payload:
            # 非 JWT 或解析失败, 不透明 token 无法验证受众, 跳过
            return True, "令牌非 JWT 格式, 跳过受众验证"

        aud = payload.get("aud")
        if aud is None:
            # JWT 但无 aud claim, 跳过 (某些授权服务器不签发 aud)
            return True, "令牌未包含 aud claim, 跳过受众验证"

        # aud 可能是字符串或列表
        if isinstance(aud, str):
            aud_list = [aud]
        elif isinstance(aud, list):
            aud_list = [str(a) for a in aud]
        else:
            aud_list = []

        expected = self._normalize_url_for_aud(expected_resource)

        # 比对: expected 与任一 aud 匹配 (规范化后比较)
        for a in aud_list:
            if self._normalize_url_for_aud(a) == expected:
                return True, f"受众验证通过: aud={a}"

        # 不匹配
        return False, (
            f"受众验证失败: token aud={aud_list} 不包含预期 resource={expected_resource}"
        )

    # ── PKCE 工具方法 ──────────────────────────────────────

    @staticmethod
    def generate_pkce_pair() -> tuple[str, str]:
        """生成 PKCE code_verifier 和 code_challenge

        Returns:
            (code_verifier, code_challenge)
        """
        # 生成 64 字符的随机字符串作为 code_verifier
        code_verifier = secrets.token_urlsafe(PKCE_VERIFIER_LENGTH)
        # S256: code_challenge = BASE64URL(SHA256(code_verifier))
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return code_verifier, code_challenge

    @staticmethod
    def generate_state() -> str:
        """生成随机的 state 参数, 用于防止 CSRF"""
        return secrets.token_urlsafe(32)

    # ── 授权服务器发现 (RFC 9728 + RFC 8414) ────────────────

    async def discover_auth_server(
        self, mcp_server_url: str
    ) -> dict:
        """发现授权服务器元数据

        流程:
        1. 从 MCP 服务器获取 Protected Resource Metadata (RFC 9728)
           GET {mcp_server_url}/.well-known/oauth-protected-resource
        2. 从返回的 authorization_servers 中获取 Auth Server URL
        3. 从 Auth Server 获取 Metadata (RFC 8414)
           GET {auth_server_url}/.well-known/oauth-authorization-server

        Args:
            mcp_server_url: MCP 服务器 URL (如 https://mcp.example.com)

        Returns:
            合并的元数据, 包含:
            - resource: MCP 服务器 URL (用于 resource 参数)
            - authorization_servers: 授权服务器 URL 列表
            - issuer: Auth Server issuer
            - authorization_endpoint: 授权端点
            - token_endpoint: 令牌端点
            - registration_endpoint: 动态注册端点 (可选)
            - code_challenge_methods_supported: 支持的 PKCE 方法
            - scopes_supported: 支持的 scope 列表
        """
        base_url = mcp_server_url.rstrip("/")
        headers = {
            "MCP-Protocol-Version": "2025-06-18",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=15) as client:
            # Step 1: 获取 Protected Resource Metadata (RFC 9728)
            resource_metadata_url = f"{base_url}/.well-known/oauth-protected-resource"
            logger.info(f"OAuth 发现: 获取 Protected Resource Metadata: {resource_metadata_url}")

            try:
                resp = await client.get(resource_metadata_url, headers=headers, follow_redirects=True)
            except httpx.RequestError as e:
                raise AppException(
                    code=2001,
                    message=f"无法连接到 MCP 服务器进行 OAuth 发现: {e}",
                    status_code=502,
                )

            if resp.status_code == 404:
                # MCP 服务器不支持 Protected Resource Metadata, 尝试直接从 base_url 推断
                logger.warning("MCP 服务器未提供 Protected Resource Metadata, 尝试直接发现")
                resource_metadata = {
                    "resource": base_url,
                    "authorization_servers": [self._extract_base_url(base_url)],
                }
            elif resp.status_code != 200:
                raise AppException(
                    code=2002,
                    message=f"获取 Protected Resource Metadata 失败: HTTP {resp.status_code}",
                    status_code=502,
                )
            else:
                try:
                    resource_metadata = resp.json()
                except json.JSONDecodeError:
                    raise AppException(
                        code=2003,
                        message="Protected Resource Metadata 响应不是有效的 JSON",
                        status_code=502,
                    )

            logger.info(f"Protected Resource Metadata: {resource_metadata}")

            auth_servers = resource_metadata.get("authorization_servers", [])
            if not auth_servers:
                # 如果没有 authorization_servers, 尝试直接用 MCP 服务器作为 Auth Server
                auth_servers = [self._extract_base_url(base_url)]

            # 取第一个授权服务器
            auth_server_url = auth_servers[0].rstrip("/")

            # Step 2: 获取 Authorization Server Metadata (RFC 8414)
            auth_metadata_url = f"{auth_server_url}/.well-known/oauth-authorization-server"
            logger.info(f"OAuth 发现: 获取 Authorization Server Metadata: {auth_metadata_url}")

            try:
                resp = await client.get(auth_metadata_url, headers=headers, follow_redirects=True)
            except httpx.RequestError as e:
                raise AppException(
                    code=2004,
                    message=f"无法连接到授权服务器进行元数据发现: {e}",
                    status_code=502,
                )

            if resp.status_code == 404:
                # 尝试 OpenID Connect Discovery
                oidc_url = f"{auth_server_url}/.well-known/openid-configuration"
                logger.info(f"尝试 OpenID Connect Discovery: {oidc_url}")
                resp = await client.get(oidc_url, headers=headers, follow_redirects=True)

            if resp.status_code != 200:
                raise AppException(
                    code=2005,
                    message=f"获取 Authorization Server Metadata 失败: HTTP {resp.status_code}",
                    status_code=502,
                )

            try:
                auth_metadata = resp.json()
            except json.JSONDecodeError:
                raise AppException(
                    code=2006,
                    message="Authorization Server Metadata 响应不是有效的 JSON",
                    status_code=502,
                )

            logger.info(f"Authorization Server Metadata: {auth_metadata}")

            # 合并元数据
            merged = {
                "resource": resource_metadata.get("resource", base_url),
                "authorization_servers": auth_servers,
                "issuer": auth_metadata.get("issuer", auth_server_url),
                "authorization_endpoint": auth_metadata.get("authorization_endpoint"),
                "token_endpoint": auth_metadata.get("token_endpoint"),
                "registration_endpoint": auth_metadata.get("registration_endpoint"),
                "code_challenge_methods_supported": auth_metadata.get(
                    "code_challenge_methods_supported", ["S256"]
                ),
                "scopes_supported": auth_metadata.get("scopes_supported", []),
                "grant_types_supported": auth_metadata.get(
                    "grant_types_supported", ["authorization_code", "refresh_token"]
                ),
                "response_types_supported": auth_metadata.get(
                    "response_types_supported", ["code"]
                ),
                "token_endpoint_auth_methods_supported": auth_metadata.get(
                    "token_endpoint_auth_methods_supported", ["client_secret_post", "none"]
                ),
            }

            return merged

    @staticmethod
    def _extract_base_url(url: str) -> str:
        """从 URL 提取 base URL (scheme + host + port)"""
        parsed = urlparse(url.rstrip("/"))
        base = f"{parsed.scheme}://{parsed.hostname}"
        if parsed.port:
            base += f":{parsed.port}"
        return base

    # ── 动态客户端注册 (RFC 7591) ───────────────────────────

    async def dynamic_register(
        self,
        registration_endpoint: str,
        redirect_uri: str,
        scopes: Optional[list[str]] = None,
    ) -> dict:
        """动态客户端注册 (RFC 7591)

        Args:
            registration_endpoint: 注册端点 URL
            redirect_uri: 回调 URL
            scopes: 请求的 scope 列表

        Returns:
            注册响应, 包含 client_id 和可选的 client_secret
        """
        body = {
            "client_name": "AgentService MCP Client",
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",  # 公共客户端 (PKCE)
            "scope": " ".join(scopes) if scopes else "",
        }

        logger.info(f"动态客户端注册: {registration_endpoint}")

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                registration_endpoint,
                json=body,
                headers={"Accept": "application/json"},
                follow_redirects=True,
            )

            if resp.status_code not in (200, 201):
                raise AppException(
                    code=2007,
                    message=f"动态客户端注册失败: HTTP {resp.status_code} - {resp.text[:500]}",
                    status_code=502,
                )

            result = resp.json()
            logger.info(f"动态客户端注册成功: client_id={result.get('client_id')}")
            return result

    # ── 发起授权流程 ────────────────────────────────────────

    async def start_authorization(
        self,
        db: AsyncSession,
        mcp_id: str,
        callback_base_url: str,
    ) -> dict:
        """发起 OAuth 2.1 授权流程

        1. 如果 oauth_config 中没有元数据, 先进行发现
        2. 如果没有 client_id, 尝试动态注册
        3. 生成 PKCE pair 和 state
        4. 构建授权 URL
        5. 将 session 数据存储在内存中
        6. 更新 oauth_status 为 "pending"

        Args:
            db: 数据库会话
            mcp_id: MCP 服务 ID
            callback_base_url: 回调基础 URL (如 http://localhost:8003)

        Returns:
            {
                "authorization_url": "https://auth.example.com/authorize?...",
                "state": "...",
                "mcp_id": "..."
            }
        """
        # 获取 MCP 服务
        result = await db.execute(select(MCPService).where(MCPService.id == mcp_id))
        mcp = result.scalar_one_or_none()
        if not mcp:
            raise ValidationException(f"MCP 服务不存在: {mcp_id}")

        if mcp.mode not in ("sse", "streamable_http"):
            raise ValidationException("OAuth 仅支持远程模式 (SSE/Streamable HTTP)")

        mcp_server_url = mcp.sse_url or ""
        if not mcp_server_url:
            raise ValidationException("MCP 服务器 URL 为空, 无法发起 OAuth")

        oauth_config = mcp.oauth_config or {}

        # Step 1: 发现授权服务器元数据 (如果尚未发现)
        if not oauth_config.get("authorization_endpoint"):
            logger.info("OAuth 配置中缺少授权端点, 开始发现...")
            metadata = await self.discover_auth_server(mcp_server_url)
            oauth_config.update(metadata)

        redirect_uri = f"{callback_base_url.rstrip('/')}/api/v1/oauth/callback"

        # Step 2: 动态客户端注册 (如果没有 client_id)
        if not oauth_config.get("client_id"):
            reg_endpoint = oauth_config.get("registration_endpoint")
            if reg_endpoint:
                try:
                    reg_result = await self.dynamic_register(
                        reg_endpoint,
                        redirect_uri,
                        oauth_config.get("scopes_supported", []),
                    )
                    oauth_config["client_id"] = reg_result.get("client_id")
                    oauth_config["client_secret"] = reg_result.get("client_secret")
                except Exception as e:
                    logger.warning(f"动态客户端注册失败: {e}")
                    raise AppException(
                        code=2008,
                        message=f"动态客户端注册失败, 请手动配置 client_id: {e}",
                        status_code=500,
                    )
            else:
                raise ValidationException(
                    "授权服务器不支持动态客户端注册, 请手动配置 client_id"
                )

        client_id = oauth_config.get("client_id")
        if not client_id:
            raise ValidationException("缺少 client_id, 无法发起 OAuth 授权")

        # Step 3: 生成 PKCE pair 和 state
        code_verifier, code_challenge = self.generate_pkce_pair()
        state = self.generate_state()

        # Step 4: 构建授权 URL
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": PKCE_CHALLENGE_METHOD,
            "state": state,
        }

        # 添加 resource 参数 (RFC 8707)
        resource = oauth_config.get("resource", mcp_server_url)
        if resource:
            params["resource"] = resource

        # 添加 scope 参数
        configured_scopes = oauth_config.get("scopes") or oauth_config.get("scopes_supported")
        if configured_scopes:
            if isinstance(configured_scopes, list):
                params["scope"] = " ".join(configured_scopes)
            else:
                params["scope"] = str(configured_scopes)

        auth_endpoint = oauth_config["authorization_endpoint"]
        authorization_url = f"{auth_endpoint}?{urlencode(params)}"

        # Step 5: 存储 session 数据
        _oauth_sessions[state] = {
            "mcp_id": mcp_id,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
            "oauth_config": oauth_config,
            "created_at": time.time(),
        }

        # Step 6: 更新数据库
        await db.execute(
            update(MCPService)
            .where(MCPService.id == mcp_id)
            .values(
                oauth_config=oauth_config,
                oauth_status=OAUTH_STATUS_PENDING,
            )
        )
        await db.commit()

        logger.info(f"OAuth 授权已发起: mcp_id={mcp_id}, state={state[:8]}...")
        return {
            "authorization_url": authorization_url,
            "state": state,
            "mcp_id": mcp_id,
        }

    # ── OAuth 回调处理 ──────────────────────────────────────

    async def handle_callback(
        self,
        db: AsyncSession,
        code: str,
        state: str,
        error: Optional[str] = None,
        error_description: Optional[str] = None,
    ) -> dict:
        """处理 OAuth 回调

        1. 验证 state, 获取 session 数据
        2. 使用 code + code_verifier 交换令牌
        3. 存储令牌到数据库
        4. 更新 oauth_status 为 "authorized"

        Args:
            db: 数据库会话
            code: 授权码
            state: 状态参数
            error: 错误信息 (如果授权失败)
            error_description: 错误描述

        Returns:
            {
                "mcp_id": "...",
                "status": "authorized" | "error",
                "error": "..." (如果有)
            }
        """
        # 检查是否有错误
        if error:
            # 清理 session
            _oauth_sessions.pop(state, None)
            # 更新数据库状态
            session_data = _oauth_sessions.get(state, {})
            mcp_id = session_data.get("mcp_id")
            if mcp_id:
                await db.execute(
                    update(MCPService)
                    .where(MCPService.id == mcp_id)
                    .values(
                        oauth_status=OAUTH_STATUS_ERROR,
                        error_message=f"{error}: {error_description or ''}",
                    )
                )
                await db.commit()
            return {
                "mcp_id": mcp_id,
                "status": "error",
                "error": f"{error}: {error_description or ''}",
            }

        # 验证 state
        session_data = _oauth_sessions.pop(state, None)
        if not session_data:
            raise ValidationException(
                f"无效的 OAuth state 参数: state 可能已过期或不存在"
            )

        mcp_id = session_data["mcp_id"]
        code_verifier = session_data["code_verifier"]
        redirect_uri = session_data["redirect_uri"]
        oauth_config = session_data["oauth_config"]

        # 交换令牌
        token_endpoint = oauth_config.get("token_endpoint")
        if not token_endpoint:
            raise ValidationException("OAuth 配置中缺少 token_endpoint")

        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": oauth_config.get("client_id"),
            "code_verifier": code_verifier,
        }

        # 添加 resource 参数 (RFC 8707)
        resource = oauth_config.get("resource")
        if resource:
            token_data["resource"] = resource

        # 如果有 client_secret, 添加到请求中
        client_secret = oauth_config.get("client_secret")
        if client_secret:
            token_data["client_secret"] = client_secret

        logger.info(f"OAuth 令牌交换: mcp_id={mcp_id}, token_endpoint={token_endpoint}")

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                token_endpoint,
                data=token_data,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                follow_redirects=True,
            )

            if resp.status_code != 200:
                error_text = resp.text[:500]
                logger.error(f"OAuth 令牌交换失败: HTTP {resp.status_code} - {error_text}")
                await db.execute(
                    update(MCPService)
                    .where(MCPService.id == mcp_id)
                    .values(
                        oauth_status=OAUTH_STATUS_ERROR,
                        error_message=f"令牌交换失败: HTTP {resp.status_code}",
                    )
                )
                await db.commit()
                return {
                    "mcp_id": mcp_id,
                    "status": "error",
                    "error": f"令牌交换失败: HTTP {resp.status_code}",
                }

            try:
                tokens = resp.json()
            except json.JSONDecodeError:
                raise AppException(
                    code=2009,
                    message="令牌交换响应不是有效的 JSON",
                    status_code=502,
                )

        # 存储令牌 (加密敏感字段)
        expires_in = tokens.get("expires_in", 3600)
        access_token_raw = tokens.get("access_token")
        oauth_tokens = {
            "access_token": access_token_raw,
            "refresh_token": tokens.get("refresh_token"),
            "token_type": tokens.get("token_type", "Bearer"),
            "expires_in": expires_in,
            "expires_at": int(time.time()) + expires_in,
            "scope": tokens.get("scope", ""),
            "obtained_at": int(time.time()),
        }

        # 令牌受众验证 (RFC 8707): 验证 access_token 的 aud 是否匹配 resource
        expected_resource = oauth_config.get("resource", "")
        audience_valid, audience_msg = self.validate_token_audience(
            access_token_raw or "", expected_resource
        )
        if audience_valid:
            logger.info(f"OAuth 令牌受众验证: mcp_id={mcp_id}, {audience_msg}")
        else:
            # 受众不匹配: 记录警告但仍然存储令牌 (由调用方决定是否使用)
            # 严格模式下可拒绝授权, 这里采用宽松策略: 警告 + 标记
            logger.warning(
                f"OAuth 令牌受众验证失败: mcp_id={mcp_id}, {audience_msg}"
            )
            oauth_tokens["audience_warning"] = audience_msg

        # 加密 access_token / refresh_token 后再持久化
        encrypted_tokens = self._encrypt_tokens(oauth_tokens)

        await db.execute(
            update(MCPService)
            .where(MCPService.id == mcp_id)
            .values(
                oauth_tokens=encrypted_tokens,
                oauth_status=OAUTH_STATUS_AUTHORIZED,
                error_message="",
            )
        )
        await db.commit()

        logger.info(f"OAuth 授权成功: mcp_id={mcp_id}")
        return {
            "mcp_id": mcp_id,
            "status": "authorized",
            "audience_valid": audience_valid,
            "audience_message": audience_msg,
        }

    # ── 令牌刷新 ────────────────────────────────────────────

    async def refresh_token(
        self,
        db: AsyncSession,
        mcp_id: str,
    ) -> dict:
        """使用 refresh_token 获取新的 access_token

        Args:
            db: 数据库会话
            mcp_id: MCP 服务 ID

        Returns:
            新的令牌信息
        """
        result = await db.execute(select(MCPService).where(MCPService.id == mcp_id))
        mcp = result.scalar_one_or_none()
        if not mcp:
            raise ValidationException(f"MCP 服务不存在: {mcp_id}")

        oauth_config = mcp.oauth_config or {}
        # 读取时解密 (兼容历史明文数据)
        oauth_tokens = self._get_decrypted_tokens(mcp)

        refresh_token = oauth_tokens.get("refresh_token")
        if not refresh_token:
            raise ValidationException("没有 refresh_token, 需要重新授权")

        token_endpoint = oauth_config.get("token_endpoint")
        if not token_endpoint:
            raise ValidationException("OAuth 配置中缺少 token_endpoint")

        token_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": oauth_config.get("client_id"),
        }

        client_secret = oauth_config.get("client_secret")
        if client_secret:
            token_data["client_secret"] = client_secret

        resource = oauth_config.get("resource")
        if resource:
            token_data["resource"] = resource

        logger.info(f"OAuth 令牌刷新: mcp_id={mcp_id}")

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                token_endpoint,
                data=token_data,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                follow_redirects=True,
            )

            if resp.status_code != 200:
                error_text = resp.text[:500]
                logger.error(f"OAuth 令牌刷新失败: HTTP {resp.status_code} - {error_text}")
                await db.execute(
                    update(MCPService)
                    .where(MCPService.id == mcp_id)
                    .values(
                        oauth_status=OAUTH_STATUS_ERROR,
                        error_message=f"令牌刷新失败: HTTP {resp.status_code}",
                    )
                )
                await db.commit()
                raise AppException(
                    code=2010,
                    message=f"令牌刷新失败: HTTP {resp.status_code}",
                    status_code=502,
                )

            tokens = resp.json()

        # 如果返回了新的 refresh_token, 使用新的; 否则保留旧的
        new_refresh_token = tokens.get("refresh_token", refresh_token)
        expires_in = tokens.get("expires_in", 3600)
        new_access_token = tokens.get("access_token")
        new_oauth_tokens = {
            "access_token": new_access_token,
            "refresh_token": new_refresh_token,
            "token_type": tokens.get("token_type", "Bearer"),
            "expires_in": expires_in,
            "expires_at": int(time.time()) + expires_in,
            "scope": tokens.get("scope", oauth_tokens.get("scope", "")),
            "obtained_at": int(time.time()),
        }

        # 令牌受众验证 (RFC 8707): 刷新后同样验证新 access_token 的受众
        expected_resource = oauth_config.get("resource", "")
        audience_valid, audience_msg = self.validate_token_audience(
            new_access_token or "", expected_resource
        )
        if not audience_valid:
            logger.warning(
                f"OAuth 刷新令牌受众验证失败: mcp_id={mcp_id}, {audience_msg}"
            )
            new_oauth_tokens["audience_warning"] = audience_msg
        else:
            logger.info(f"OAuth 刷新令牌受众验证: mcp_id={mcp_id}, {audience_msg}")

        # 加密敏感字段后持久化
        encrypted_tokens = self._encrypt_tokens(new_oauth_tokens)

        await db.execute(
            update(MCPService)
            .where(MCPService.id == mcp_id)
            .values(
                oauth_tokens=encrypted_tokens,
                oauth_status=OAUTH_STATUS_AUTHORIZED,
                error_message="",
            )
        )
        await db.commit()

        logger.info(f"OAuth 令牌刷新成功: mcp_id={mcp_id}")
        return {"mcp_id": mcp_id, "status": "authorized"}

    # ── 获取有效的 access_token ─────────────────────────────

    async def get_valid_access_token(
        self,
        db: AsyncSession,
        mcp_id: str,
    ) -> Optional[str]:
        """获取有效的 access_token, 如果过期则自动刷新

        Args:
            db: 数据库会话
            mcp_id: MCP 服务 ID

        Returns:
            access_token 字符串, 或 None
        """
        result = await db.execute(select(MCPService).where(MCPService.id == mcp_id))
        mcp = result.scalar_one_or_none()
        if not mcp:
            return None

        if mcp.oauth_status != OAUTH_STATUS_AUTHORIZED:
            return None

        # 读取时解密
        oauth_tokens = self._get_decrypted_tokens(mcp)
        access_token = oauth_tokens.get("access_token")
        if not access_token:
            return None

        # 检查是否过期 (提前 60 秒刷新)
        expires_at = oauth_tokens.get("expires_at", 0)
        if time.time() < expires_at - 60:
            return access_token

        # 需要刷新
        if oauth_tokens.get("refresh_token"):
            try:
                await self.refresh_token(db, mcp_id)
                # 重新获取 (refresh_token 已加密存储, 需解密读取)
                result = await db.execute(select(MCPService).where(MCPService.id == mcp_id))
                mcp = result.scalar_one_or_none()
                if mcp and mcp.oauth_tokens:
                    refreshed = self._get_decrypted_tokens(mcp)
                    return refreshed.get("access_token")
            except Exception as e:
                logger.error(f"自动刷新令牌失败: {e}")
                return None

        return access_token

    # ── 撤销 OAuth ──────────────────────────────────────────

    async def revoke(
        self,
        db: AsyncSession,
        mcp_id: str,
    ) -> dict:
        """撤销 OAuth 授权, 清除令牌

        Args:
            db: 数据库会话
            mcp_id: MCP 服务 ID

        Returns:
            {"mcp_id": mcp_id, "status": "revoked"}
        """
        await db.execute(
            update(MCPService)
            .where(MCPService.id == mcp_id)
            .values(
                oauth_tokens=None,
                oauth_status=OAUTH_STATUS_NOT_CONFIGURED,
                error_message="",
            )
        )
        await db.commit()

        logger.info(f"OAuth 授权已撤销: mcp_id={mcp_id}")
        return {"mcp_id": mcp_id, "status": "revoked"}


# 全局单例
oauth_service = OAuthService()
