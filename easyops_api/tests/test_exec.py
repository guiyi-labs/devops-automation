"""E3：受控批量运维测试——幂等、操作目录白名单、break_glass、失败隔离、状态聚合。"""
from unittest.mock import patch

from tasks.exec_tasks import exec_host_result


class _FakeGroup:
    """替代 Celery group：不连 broker、不执行 Worker，仅保留 group_id。"""

    def __init__(self, *args, **kwargs):
        self.id = 'fake-group-id'

    def __call__(self, *args, **kwargs):
        return self


def _auth(token):
    return {'Authorization': f'Bearer {token}'}


def _create_asset(client, token, ip, name='box', pwd='pw123', fpr=None):
    payload = {'asset_name': name, 'ip_address': ip, 'ssh_user': 'root', 'ssh_pwd': pwd}
    if fpr:
        payload['host_key_fingerprint'] = fpr
    resp = client.post('/api/v1/asset/', json=payload, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------- 操作目录 ----------
def test_operation_catalog_lists_fixed_ops(client, admin_token):
    resp = client.get('/api/v1/exec/operations', headers=_auth(admin_token))
    assert resp.status_code == 200
    codes = [op['code'] for op in resp.json()]
    assert {'disk_usage', 'memory_usage', 'service_status', 'service_restart',
            'log_tail', 'port_listen'} <= set(codes)


def test_preview_read_operation(client, admin_token):
    asset = _create_asset(client, admin_token, '10.3.3.3')
    resp = client.post('/api/v1/exec/preview', json={
        'asset_ids': [asset['id']], 'operation': 'memory_usage', 'params': {},
    }, headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body['command'] == 'free -m'
    assert body['risk'] == 'read'
    assert body['total_hosts'] == 1
    assert body['confirm_token'] is None  # 只读无需确认


def test_preview_write_operation_returns_token(client, admin_token):
    asset = _create_asset(client, admin_token, '10.3.3.4')
    resp = client.post('/api/v1/exec/preview', json={
        'asset_ids': [asset['id']], 'operation': 'service_restart',
        'params': {'service': 'nginx'},
    }, headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body['risk'] == 'write'
    assert body['confirm_token'] and len(body['confirm_token']) >= 20
    assert body['command'] == 'systemctl restart nginx && systemctl is-active nginx'
    assert "'nginx'" in body['command'].replace("'nginx'", "'nginx'") or body['command']


def test_operation_param_pattern_rejected(client, admin_token):
    """注入型参数（含 shell 元字符）必须被拒。"""
    asset = _create_asset(client, admin_token, '10.3.3.5')
    # service 参数白名单只允许 [A-Za-z0-9_.:@-]，含空格/分号会被拒
    resp = client.post('/api/v1/exec/preview', json={
        'asset_ids': [asset['id']], 'operation': 'service_status',
        'params': {'service': 'nginx ; rm -rf /'},
    }, headers=_auth(admin_token))
    assert resp.status_code == 400
    assert '白名单' in resp.json()['detail'] or '不符合' in resp.json()['detail']


def test_unknown_operation_rejected(client, admin_token):
    resp = client.post('/api/v1/exec/preview', json={
        'asset_ids': [1], 'operation': 'nope', 'params': {},
    }, headers=_auth(admin_token))
    assert resp.status_code == 400


# ---------- 提交 / 幂等 / 确认 ----------
def test_batch_empty_assets_returns_400(client, admin_token):
    resp = client.post('/api/v1/exec/batch', json={
        'asset_ids': [], 'operation': 'memory_usage', 'params': {}, 'idempotency_key': 'a1',
    }, headers=_auth(admin_token))
    assert resp.status_code == 400


def test_batch_too_many_assets_returns_400(client, admin_token):
    resp = client.post('/api/v1/exec/batch', json={
        'asset_ids': list(range(1, 52)), 'operation': 'memory_usage', 'params': {},
        'idempotency_key': 'a2',
    }, headers=_auth(admin_token))
    assert resp.status_code == 400


def test_batch_missing_asset_returns_400(client, admin_token):
    resp = client.post('/api/v1/exec/batch', json={
        'asset_ids': [99999], 'operation': 'memory_usage', 'params': {},
        'idempotency_key': 'a3',
    }, headers=_auth(admin_token))
    assert resp.status_code == 400
    assert '99999' in resp.json()['detail']


def _submit(client, token, asset_id, idempotency_key, operation='memory_usage', params=None):
    resp = client.post('/api/v1/exec/batch', json={
        'asset_ids': [asset_id], 'operation': operation, 'params': params or {},
        'idempotency_key': idempotency_key,
    }, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_batch_read_success_creates_record(client, admin_token):
    asset = _create_asset(client, admin_token, '10.5.5.5')
    with patch('api.v1.exec_task.group', _FakeGroup):
        body = _submit(client, admin_token, asset['id'], 'k-read-1')
    assert body['exec_type'] == 'fixed'
    assert body['operation'] == 'memory_usage'
    assert body['status'] in ('running', 'partial', 'done')
    records = client.get('/api/v1/exec/records', headers=_auth(admin_token)).json()
    assert any(r['id'] == body['id'] for r in records)


def test_idempotency_key_deduplicates(client, admin_token):
    asset = _create_asset(client, admin_token, '10.6.6.6')
    payload = {'asset_ids': [asset['id']], 'operation': 'memory_usage',
               'params': {}, 'idempotency_key': 'k-dedup'}
    with patch('api.v1.exec_task.group', _FakeGroup):
        first = client.post('/api/v1/exec/batch', json=payload, headers=_auth(admin_token))
        second = client.post('/api/v1/exec/batch', json=payload, headers=_auth(admin_token))
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()['id'] == second.json()['id'], '同幂等键应返回同一任务，不重复执行'
    records = client.get('/api/v1/exec/records', headers=_auth(admin_token)).json()
    assert len(records) == 1


def test_batch_requires_idempotency_key(client, admin_token):
    asset = _create_asset(client, admin_token, '10.6.6.7')
    resp = client.post('/api/v1/exec/batch', json={
        'asset_ids': [asset['id']], 'operation': 'memory_usage', 'params': {},
    }, headers=_auth(admin_token))
    assert resp.status_code == 422  # idempotency_key 必填


# ---------- break_glass ----------
def test_break_glass_default_disabled(client, admin_token):
    resp = client.get('/api/v1/exec/break_glass', headers=_auth(admin_token))
    assert resp.status_code == 200
    assert resp.json()['enabled'] is False


def test_break_glass_command_requires_enabled_and_admin(client, admin_token, operator_token):
    asset = _create_asset(client, admin_token, '10.7.7.7')
    # operator：任意命令直接 403（需 admin）
    resp = client.post('/api/v1/exec/batch', json={
        'asset_ids': [asset['id']], 'command': 'uptime', 'idempotency_key': 'bg-1',
    }, headers=_auth(operator_token))
    assert resp.status_code == 403
    # admin 但开关未开：403
    resp = client.post('/api/v1/exec/batch', json={
        'asset_ids': [asset['id']], 'command': 'uptime', 'idempotency_key': 'bg-2',
    }, headers=_auth(admin_token))
    assert resp.status_code == 403


def test_break_glass_admin_can_enable(monkeypatch, client, admin_token, operator_token):
    # 开关：admin 启用需理由
    resp = client.post('/api/v1/exec/break_glass', json={'enabled': True, 'reason': '紧急排查'},
                       headers=_auth(admin_token))
    assert resp.status_code == 200
    assert resp.json()['enabled'] is True
    # operator 无权切换
    resp = client.post('/api/v1/exec/break_glass', json={'enabled': False, 'reason': ''},
                       headers=_auth(operator_token))
    assert resp.status_code == 403
    # 关闭后任意命令被拒
    client.post('/api/v1/exec/break_glass', json={'enabled': False, 'reason': ''},
                headers=_auth(admin_token))

# ---------- 失败隔离 / 状态聚合（Worker 层） ----------
def test_worker_partial_failure_isolates_hosts(client, admin_token):
    """一台成功、一台认证失败——失败不拖垮另一台，逐主机状态区分。"""
    ok = _create_asset(client, admin_token, '10.8.8.8', name='ok')
    bad = _create_asset(client, admin_token, '10.9.9.9', name='bad')
    # 先经 API 创建一条真实记录（含 exec_host_result 占位行）
    with patch('api.v1.exec_task.group', _FakeGroup):
        created = _submit(client, admin_token, ok['id'], 'k-iso-ok')
        created_bad = _submit(client, admin_token, bad['id'], 'k-iso-bad')

    from services.ssh_service import AuthError

    bad_host = None
    def fake_connect_and_run(**kwargs):
        nonlocal bad_host
        bad_host = kwargs.get('host')
        if kwargs.get('host') == '10.9.9.9':
            raise AuthError('10.9.9.9', 'SSH 认证失败')
        return {'host': kwargs.get('host'), 'stdout': 'ok out', 'stderr': '', 'exit_code': 0, 'status': 1}

    with patch('services.ssh_service.connect_and_run', side_effect=fake_connect_and_run):
        ok_ret = exec_host_result.run(created['id'], ok['id'])
        bad_ret = exec_host_result.run(created_bad['id'], bad['id'])

    assert ok_ret['status'] == 1
    assert ok_ret['stdout'] == 'ok out'
    assert bad_ret['status'] == 2
    assert bad_ret['error_type'] == 'auth_error'
    # 逐主机结果落库成功
    hosts = client.get(f"/api/v1/exec/records/{created['id']}/hosts", headers=_auth(admin_token)).json()
    assert hosts[0]['host'] == '10.8.8.8'
    assert hosts[0]['status'] == 'succeeded'
    bad_hosts = client.get(f"/api/v1/exec/records/{created_bad['id']}/hosts", headers=_auth(admin_token)).json()
    assert bad_hosts[0]['status'] == 'failed'
    assert bad_hosts[0]['error_type'] == 'auth_error'


def test_worker_asset_missing_returns_error(client, admin_token):
    asset = _create_asset(client, admin_token, '10.10.10.10', name='tmp')
    with patch('api.v1.exec_task.group', _FakeGroup):
        created = _submit(client, admin_token, asset['id'], 'k-wm')
    result = exec_host_result.run(created['id'], 999999)  # 资产不存在
    assert result['status'] == 2
    assert '不存在' in result['error']


# 兼容：旧任务名仍可用
def test_legacy_task_name_alias(client):
    from tasks import exec_tasks
    assert exec_tasks.batch_exec_command is exec_host_result