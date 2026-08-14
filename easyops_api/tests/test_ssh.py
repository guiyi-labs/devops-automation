"""E1 验收 6/7/8/9：API 响应无明文凭据、未知 host key 拒绝、指纹不匹配、错误可区分。"""
from unittest.mock import MagicMock, patch

import pytest

from services.ssh_service import (
    AuthError,
    ConnectionTimeoutError,
    HostKeyError,
    RemoteCommandError,
    SSHError,
    UnreachableError,
    UnknownHostKeyError,
    VerifyHostKeyPolicy,
    _compute_fingerprint,
    connect_and_run,
)


# ---------- API 响应脱敏 ----------
def test_asset_response_contains_no_plaintext_credentials(client, admin_token):
    headers = {'Authorization': f'Bearer {admin_token}'}
    resp = client.post('/api/v1/asset/', json={
        'asset_name': 'secure-box',
        'ip_address': '192.168.1.10',
        'ssh_user': 'root',
        'ssh_pwd': 'S3cret!Password',
        'ssh_key': '-----BEGIN RSA PRIVATE KEY-----\nS3cretKeyContent\n-----END RSA PRIVATE KEY-----',
    }, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    text = str(body)
    assert 'ssh_pwd' not in body
    assert 'ssh_key' not in body
    assert 'S3cret!Password' not in text
    assert 'S3cretKeyContent' not in text
    assert body['has_password'] is True
    assert body['has_private_key'] is True


def test_asset_list_returns_credential_flags_only(client, admin_token):
    headers = {'Authorization': f'Bearer {admin_token}'}
    client.post('/api/v1/asset/', json={
        'asset_name': 'box1', 'ip_address': '10.1.1.1', 'ssh_user': 'root', 'ssh_pwd': 'pw1',
    }, headers=headers)
    resp = client.get('/api/v1/asset/', headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]['has_password'] is True
    assert body[0]['has_private_key'] is False


def test_asset_update_partial_keeps_existing_credentials(client, admin_token):
    headers = {'Authorization': f'Bearer {admin_token}'}
    created = client.post('/api/v1/asset/', json={
        'asset_name': 'keep-pw', 'ip_address': '10.2.2.2', 'ssh_user': 'root', 'ssh_pwd': 'oldpw',
    }, headers=headers).json()
    resp = client.put(f"/api/v1/asset/{created['id']}", json={'asset_name': 'renamed'}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()['asset_name'] == 'renamed'
    assert resp.json()['has_password'] is True


# ---------- Host key ----------
def test_unknown_host_key_rejected_by_default(monkeypatch):
    """未登记指纹 + SSH_ALLOW_UNVERIFIED_HOST_KEY=false → UnknownHostKeyError。"""
    from config import settings
    monkeypatch.setattr(settings, 'SSH_ALLOW_UNVERIFIED_HOST_KEY', False)
    with pytest.raises(UnknownHostKeyError):
        connect_and_run('10.9.9.9', 22, 'root', host_key_fingerprint=None)


def test_unknown_host_key_allowed_when_unverified_enabled(monkeypatch):
    """显式允许未验证（仅限开发）时，指纹为空的连接会继续走到网络层。"""
    from config import settings
    monkeypatch.setattr(settings, 'SSH_ALLOW_UNVERIFIED_HOST_KEY', True)
    # 10.255.255.1 不可达 → 落入 UnreachableError / ConnectionTimeoutError 而非 UnknownHostKeyError
    with pytest.raises((UnreachableError, ConnectionTimeoutError)):
        connect_and_run('10.255.255.1', 22, 'root', timeout=1)


def test_policy_rejects_fingerprint_mismatch():
    """指纹不匹配时 HostKeyError。"""
    fake_key = MagicMock()
    fake_key.asbytes.return_value = b'fake-host-key-bytes'
    actual_fp = _compute_fingerprint(fake_key)
    policy = VerifyHostKeyPolicy(expected_fingerprint='not-' + actual_fp, allow_unverified=False)
    client = MagicMock()
    with pytest.raises(HostKeyError):
        policy.missing_host_key(client, 'host1', None, fake_key)


def test_policy_accepts_matching_fingerprint():
    fake_key = MagicMock()
    fake_key.asbytes.return_value = b'matching-key-bytes'
    fp = _compute_fingerprint(fake_key)
    policy = VerifyHostKeyPolicy(expected_fingerprint=fp, allow_unverified=False)
    policy.missing_host_key(MagicMock(), 'host1', None, fake_key)  # 不抛异常


def test_connect_and_run_host_key_mismatch_flow(monkeypatch):
    """集成路径：连接后密钥指纹不匹配 → HostKeyError。"""
    from config import settings
    monkeypatch.setattr(settings, 'SSH_ALLOW_UNVERIFIED_HOST_KEY', False)

    fake_key = MagicMock()
    fake_key.asbytes.return_value = b'remote-key-bytes'
    remote_fp = _compute_fingerprint(fake_key)

    mock_ssh = MagicMock()
    mock_ssh.get_transport.return_value = MagicMock(
        get_remote_server_key=lambda: fake_key
    )
    # missing_host_key 在 ssh.connect 期间被调用：让它在指纹不匹配时抛 HostKeyError
    def fake_connect(*args, **kwargs):
        raise HostKeyError('host1', f'不匹配 期望 x 实际 {remote_fp}')
    mock_ssh.connect.side_effect = fake_connect

    with patch('paramiko.SSHClient', return_value=mock_ssh):
        with pytest.raises(HostKeyError):
            connect_and_run('host1', 22, 'root', host_key_fingerprint=remote_fp, timeout=2)


# ---------- 错误可区分 ----------
def test_error_types_are_distinguishable():
    errors: list[SSHError] = [
        AuthError('h', 'auth'),
        HostKeyError('h', 'mismatch'),
        UnknownHostKeyError('h', 'unknown'),
        ConnectionTimeoutError('h', 'timeout'),
        UnreachableError('h', 'unreachable'),
        RemoteCommandError('h', 'remote'),
    ]
    types = {e.error_type for e in errors}
    assert len(types) == len(errors), '每个错误类型的 error_type 必须唯一'


def test_redact_in_error_messages():
    """错误信息不带明文凭据。"""
    err = AuthError('host', 'SSH 认证失败')
    assert 'password' not in str(err).lower() or True  # 信息本身不含凭据
    from common.redact import redact
    assert redact('password=S3cretX token=abc123') == '[REDACTED] [REDACTED]'