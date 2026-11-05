"""Google refresh token 的加密（ADR-0020）：存進 google_grant 前加密，錯誤不帶出內容。"""

import pytest
from app.core.token_cipher import CURRENT_KEY_VERSION, TokenCipher, TokenDecryptError
from cryptography.fernet import Fernet

TOKEN = "1//refresh-token-from-google"


def make_cipher() -> TokenCipher:
    return TokenCipher(Fernet.generate_key().decode())


def test_encrypted_token_can_be_decrypted() -> None:
    cipher = make_cipher()
    assert cipher.decrypt(cipher.encrypt(TOKEN)) == TOKEN


def test_encrypted_bytes_do_not_contain_the_token() -> None:
    assert TOKEN.encode() not in make_cipher().encrypt(TOKEN)


def test_new_tokens_use_the_current_key_version() -> None:
    assert make_cipher().key_version == CURRENT_KEY_VERSION


def test_a_different_key_cannot_decrypt() -> None:
    encrypted = make_cipher().encrypt(TOKEN)
    with pytest.raises(TokenDecryptError) as excinfo:
        make_cipher().decrypt(encrypted)
    assert TOKEN not in str(excinfo.value)


def test_damaged_data_cannot_be_decrypted() -> None:
    with pytest.raises(TokenDecryptError):
        make_cipher().decrypt(b"not-encrypted")
