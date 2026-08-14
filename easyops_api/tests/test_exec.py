"""E2：批量执行边界（空资产/超限/资产缺失/重复请求）与单主机失败隔离。"""
from unittest.mock import patch

from tasks.exec_tasks import batch_exec_command


class _FakeGroup:
    """替代 Celery group：不连接 broker、不执行 Worker，仅保留 group_id。"""

    def __init__(self, *args, **kwargs):
        self.id = 'fake-group-id'

    def __call__(self, *args, **kwargs):
        return self


def _auth(token):
    return {'Authorization': f'Bearer {token}'}


def _create_asset(client, token, ip, name='box', pwd='pw123'):
    resp = client.post('/api/v1/asset/', json={
        'asset_name': name, 'ip_address': ip, 'ssh_user': 'root', 'ssh_pwd': pwd,
    }, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------- 创建边界 ----------
def test_batch_empty_assets_returns_400(client, admin_token):
    resp = client.post('/api/v1/exec/batch', json={'asset_ids': [], 'command': 'uptime'},
                       headers=_auth(admin_token))
    assert resp.status_code == 400


def test_batch_too_many_assets_returns_400(client, admin_token):
    resp = client.post('/api/v1/exec/batch', json={'asset_ids': list(range(1, 52)), 'command': 'uptime'},
                       headers=_auth(admin_token))
    assert resp.status_code == 400


def test_batch_with_missing_asset_returns_400(client, admin_token, operator_token):
    asset = _create_asset(client, admin_token, '10.4.4.4')
    resp = client.post('/api/v1/exec/batch', json={'asset_ids': [asset['id'], 99999], 'command': 'uptime'},
                       headers=_auth(operator_token))
    assert resp.status_code == 400
    assert '99999' in resp.json()['detail']


def test_batch_success_creates_record(client, admin_token):
    asset = _create_asset(client, admin_token, '10.5.5.5')
    with patch('api.v1.exec_task.group', _FakeGroup):
        resp = client.post('/api/v1/exec/batch', json={'asset_ids': [asset['id']], 'command': 'uptime'},
                           headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()['hosts'] == ['10.5.5.5']
    records = client.get('/api/v1/exec/records', headers=_auth(admin_token)).json()
    assert len(records) == 1
    assert records[0]['exec_user'] == 'admin'


def test_batch_duplicate_requests_create_separate_records(client, admin_token):
    """当前尚无幂等键（E3 引入 Idempotency-Key）：重复请求各自成记录且不报错。"""
    asset = _create_asset(client, admin_token, '10.6.6.6')
    payload = {'asset_ids': [asset['id']], 'command': 'uptime'}
    with patch('api.v1.exec_task.group', _FakeGroup):
        first = client.post('/api/v1/exec/batch', json=payload, headers=_auth(admin_token))
        second = client.post('/api/v1/exec/batch', json=payload, headers=_auth(admin_token))
    assert first.status_code == 200 and second.status_code == 200
    records = client.get('/api/v1/exec/records', headers=_auth(admin_token)).json()
    assert len(records) == 2


# ---------- 单主机失败隔离（E2 部分失败） ----------
def test_batch_worker_partial_failure_isolates_hosts(client, admin_token):
    """两台主机：一台成功、一台认证失败——失败不拖垮另一台。"""
    ok_asset = _create_asset(client, admin_token, '10.7.7.7', name='ok')
    bad_asset = _create_asset(client, admin_token, '10.8.8.8', name='bad')

    from services.ssh_service import AuthError

    def fake_connect_and_run(**kwargs):
        if kwargs.get('host') == '10.8.8.8':
            raise AuthError('10.8.8.8', 'SSH 认证失败')
        return {'host': kwargs['host'], 'stdout': 'ok output', 'stderr': '', 'exit_code': 0, 'status': 1}

    with patch('services.ssh_service.connect_and_run', side_effect=fake_connect_and_run):
        ok_result = batch_exec_command.run(ok_asset['id'], 'uptime')
        bad_result = batch_exec_command.run(bad_asset['id'], 'uptime')

    assert ok_result['status'] == 1
    assert ok_result['stdout'] == 'ok output'
    assert bad_result['status'] == 2
    assert bad_result['error_type'] == 'auth_error'
    assert '10.8.8.8' in bad_result['host']


def test_batch_worker_missing_asset_returns_error(client):
    result = batch_exec_command.run(99999, 'uptime')
    assert result['status'] == 2
    assert '不存在' in result['error']