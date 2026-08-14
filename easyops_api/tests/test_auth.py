"""E1 验收 3/4/5/6：鉴权、角色矩阵、禁用用户、明文凭据脱敏。"""
import pytest

# 需要登录才能访问的业务端点（不含 /user/login 与 /user/init-admin）
PROTECTED_GET_ENDPOINTS = [
    '/api/v1/asset/',
    '/api/v1/exec/records',
    '/api/v1/alert/rules',
    '/api/v1/cron/tasks',
    '/api/v1/deploy/projects',
    '/api/v1/container/docker/containers',
    '/api/v1/container/k8s/pods',
]


@pytest.mark.parametrize('path', PROTECTED_GET_ENDPOINTS)
def test_unauthenticated_get_returns_401(client, path):
    resp = client.get(path)
    assert resp.status_code == 401, resp.text


def test_unauthenticated_write_returns_401(client):
    resp = client.post('/api/v1/asset/', json={
        'asset_name': 'x', 'ip_address': '10.0.0.1', 'ssh_user': 'root',
    })
    assert resp.status_code == 401, resp.text


def test_viewer_cannot_create_asset(client, viewer_token):
    resp = client.post('/api/v1/asset/', json={
        'asset_name': 'demo', 'ip_address': '10.0.0.2', 'ssh_user': 'root',
    }, headers={'Authorization': f'Bearer {viewer_token}'})
    assert resp.status_code == 403, resp.text


def test_viewer_cannot_batch_exec(client, viewer_token):
    resp = client.post('/api/v1/exec/batch', json={
        'asset_ids': [1], 'command': 'uptime',
    }, headers={'Authorization': f'Bearer {viewer_token}'})
    assert resp.status_code == 403, resp.text


def test_viewer_cannot_create_user(client, viewer_token):
    resp = client.post('/api/v1/user/', json={
        'username': 'newbie', 'password': 'pw123456', 'nickname': 'n',
    }, headers={'Authorization': f'Bearer {viewer_token}'})
    assert resp.status_code == 403, resp.text


def test_operator_can_create_asset(client, operator_token):
    resp = client.post('/api/v1/asset/', json={
        'asset_name': 'op-asset', 'ip_address': '10.0.0.3', 'ssh_user': 'root',
    }, headers={'Authorization': f'Bearer {operator_token}'})
    assert resp.status_code == 200, resp.text


def test_operator_cannot_create_user(client, operator_token):
    resp = client.post('/api/v1/user/', json={
        'username': 'newbie', 'password': 'pw123456', 'nickname': 'n',
    }, headers={'Authorization': f'Bearer {operator_token}'})
    assert resp.status_code == 403, resp.text


def test_viewer_can_read_assets(client, viewer_token):
    resp = client.get('/api/v1/asset/', headers={'Authorization': f'Bearer {viewer_token}'})
    assert resp.status_code == 200, resp.text


def test_disabled_user_cannot_login(client):
    resp = client.post('/api/v1/user/login', json={'username': 'disabled', 'password': 'disabled123'})
    assert resp.status_code == 401, resp.text


def test_disabled_user_old_token_rejected(client):
    from conftest import disabled_token
    token = disabled_token(client)
    resp = client.get('/api/v1/asset/', headers={'Authorization': f'Bearer {token}'})
    assert resp.status_code == 401, resp.text


def test_login_failure_writes_audit(client):
    client.post('/api/v1/user/login', json={'username': 'admin', 'password': 'wrong-password'})
    from database.models import AuditLog
    from database.session import SessionLocal
    db = SessionLocal()
    try:
        logs = db.query(AuditLog).filter(AuditLog.action == 'login_failed').all()
        assert len(logs) >= 1
        entry = logs[-1]
        assert entry.username == 'admin'
        assert 'wrong-password' not in (entry.detail or '')
    finally:
        db.close()


def test_permission_denied_writes_audit(client, viewer_token):
    client.post('/api/v1/asset/', json={
        'asset_name': 'x', 'ip_address': '10.0.0.1', 'ssh_user': 'root',
    }, headers={'Authorization': f'Bearer {viewer_token}'})
    from database.models import AuditLog
    from database.session import SessionLocal
    db = SessionLocal()
    try:
        denied = db.query(AuditLog).filter(AuditLog.action == 'permission_denied').all()
        assert len(denied) >= 1
        assert denied[-1].username == 'viewer'
    finally:
        db.close()


def test_init_admin_one_time(client):
    """一次性 bootstrap：首次成功，重复调用 409。"""
    from conftest import _seed_roles
    from database.session import Base, engine
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    _seed_roles()

    first = client.post('/api/v1/user/init-admin')
    assert first.status_code == 200, first.text
    second = client.post('/api/v1/user/init-admin')
    assert second.status_code == 409, second.text


def test_health_endpoints(client):
    live = client.get('/health/live')
    assert live.status_code == 200
    assert live.json()['status'] == 'alive'
    ready = client.get('/health/ready')
    assert ready.status_code in (200, 503)  # sqlite 内存库 + 无 Redis 可能 503