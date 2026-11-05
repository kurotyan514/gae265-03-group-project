"""加密 Google refresh token（ADR-0020）。

只有加密後的 refresh token 會進資料庫；金鑰來自 TOKEN_ENCRYPTION_KEY。
google_grant.key_version 記錄用哪一版金鑰加密，日後輪替金鑰時才分得出舊資料。
錯誤訊息不帶 token 或金鑰的內容，避免進 log（ADR-0009）。
"""

from cryptography.fernet import Fernet, InvalidToken

# 目前只有一把金鑰；輪替時遞增，並保留舊金鑰解舊資料
CURRENT_KEY_VERSION = 1


class TokenDecryptError(Exception):
    """解不開：金鑰換過或資料損毀。呼叫端應視為沒有授權，請使用者重新授權。"""


class TokenCipher:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key)
        self.key_version = CURRENT_KEY_VERSION

    def encrypt(self, token: str) -> bytes:
        return self._fernet.encrypt(token.encode())

    def decrypt(self, data: bytes) -> str:
        try:
            return self._fernet.decrypt(data).decode()
        except InvalidToken:
            raise TokenDecryptError("refresh token 解密失敗") from None


def cipher_from_settings() -> TokenCipher:
    """用 TOKEN_ENCRYPTION_KEY 建立；呼叫前要確認 Google 設定齊全（settings.google_login_enabled）。"""
    from app.core.config import settings

    assert settings.TOKEN_ENCRYPTION_KEY is not None
    return TokenCipher(settings.TOKEN_ENCRYPTION_KEY.get_secret_value())
