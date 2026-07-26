"""AES加密服务 - 保护API密钥和敏感数据

使用Fernet对称加密，密钥从环境变量ENCRYPTION_KEY派生，
确保重启后能正确解密。
"""
import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet

from common.config import settings
from common.logger import get_logger

logger = get_logger(__name__)


class CryptoService:
    """AES加密服务 - 保护API密钥和敏感数据"""

    def __init__(self, key: Optional[str] = None):
        raw_key = key or settings.ENCRYPTION_KEY
        if isinstance(raw_key, str):
            raw_key = raw_key.encode()
        # 用SHA256派生固定32字节密钥，再base64编码为Fernet密钥
        derived = hashlib.sha256(raw_key).digest()
        fernet_key = base64.urlsafe_b64encode(derived)
        self._cipher = Fernet(fernet_key)

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return ""
        return self._cipher.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            return ""
        try:
            return self._cipher.decrypt(ciphertext.encode()).decode()
        except Exception as e:
            logger.error(f"解密失败: {e}")
            raise ValueError("解密失败，请检查密钥")


crypto_service = CryptoService()
