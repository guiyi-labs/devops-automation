"""SSH 凭据加密。

使用 Fernet（对称加密）对资产密码 / 私钥加密后落库。密文带版本前缀：
    v1:<token>
这样未来更换算法时可以按前缀做版本迁移。
"""
from base64 import b64encode
from hashlib import sha256

from cryptography.fernet import Fernet

from config import settings

_PREFIX = 'v1:'

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        digest = sha256(settings.CREDENTIAL_ENCRYPTION_KEY.encode()).digest()
        _fernet = Fernet(b64encode(digest))
    return _fernet


def encrypt_value(plaintext: str) -> str:
    """加密一个明文字符串，返回 'v1:<token>'。"""
    if not plaintext:
        return plaintext
    token = _get_fernet().encrypt(plaintext.encode('utf-8')).decode('utf-8')
    return f'{_PREFIX}{token}'


def decrypt_value(ciphertext: str) -> str:
    """解密 'v1:<token>'，返回明文。格式非法时抛 ValueError。"""
    if not ciphertext:
        return ciphertext
    if not ciphertext.startswith(_PREFIX):
        raise ValueError('无效的加密值格式（缺少 v1: 前缀）')
    token = ciphertext[len(_PREFIX):]
    return _get_fernet().decrypt(token.encode('utf-8')).decode('utf-8')


def is_encrypted(value: str | None) -> bool:
    """判断一个值是否已是加密格式。"""
    return bool(value) and value.startswith(_PREFIX)