"""加密解密单元测试。"""
import pytest

from common.crypto import decrypt_value, encrypt_value, is_encrypted


def test_encrypt_decrypt_roundtrip():
    plaintext = 'SuperSecret!Password123'
    encrypted = encrypt_value(plaintext)
    assert encrypted.startswith('v1:')
    assert encrypted != plaintext
    assert is_encrypted(encrypted)
    assert decrypt_value(encrypted) == plaintext


def test_encrypt_produces_different_ciphertext_for_same_input():
    """Fernet 带随机盐，同一明文两次加密密文不同。"""
    assert encrypt_value('same') != encrypt_value('same')


def test_decrypt_invalid_format_raises():
    with pytest.raises(ValueError):
        decrypt_value('no-prefix-plaintext')


def test_decrypt_tampered_token_raises():
    encrypted = encrypt_value('secret')
    with pytest.raises(Exception):
        decrypt_value('v1:' + encrypted[3:-2] + 'XX')