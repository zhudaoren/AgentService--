from typing import Optional

from cryptography.fernet import Fernet

from ...common.config import settings
from ...common.logger import get_logger

logger = get_logger(__name__)


class CryptoService:
    """AES加密服务 - 保护API密钥和敏感数据"""

    def __init__(self, key: Optional[str] = None):
        self._key = key or settings.ENCRYPTION_KEY
        if isinstance(self._key, str):
            self._key = self._key.encode()
        if len(self._key) < 32:
            self._key = self._key.ljust(32, b"0")[:32]
        self._cipher = Fernet(Fernet.generate_key())

    def encrypt(self, plaintext: str) -> str:
        return self._cipher.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._cipher.decrypt(ciphertext.encode()).decode()
        except Exception as e:
            logger.error(f"解密失败: {e}")
            raise ValueError("解密失败，请检查密钥")


crypto_service = CryptoService()
