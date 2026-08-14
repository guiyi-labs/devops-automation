"""E2：业务 CRUD、错误响应与权限矩阵补充测试。"""


def _auth(token):
    return {'Authorization': f'Bearer {token}'}


# ---------- 资产 CRUD 全流程 ----------
def test_asset_crud_flow(client, admin_token):
    h = _auth(admin_token)
    # create
    created = client.post('/api/v1/asset/', json={
        'asset_name': 'crud-box', 'ip_address': '10.3.3.3', 'ssh_user': 'root',
        'env_type': 'prod',
    }, headers=h)
    assert created.status_code == 200
    asset_id = created.json()['id']

    # list contains it
    listed = client.get('/api/v1/asset/', headers=h).json()
    assert any(a['id'] == asset_id for a in listed)

    # update
    updated = client.put(f'/api/v1/asset/{asset_id}', json={'asset_name': 'crud-renamed'}, headers=h)
    assert updated.status_code == 200
    assert updated.json()['asset_name'] == 'crud-renamed'

    # delete
    deleted = client.delete(f'/api/v1/asset/{asset_id}', headers=h)
    assert deleted.status_code == 200
    assert deleted.json()['ok'] is True

    # gone
    gone = client.get('/api/v1/asset/', headers=h).json()
    assert all(a['id'] != asset_id for a in gone)


def test_asset_update_missing_returns_404(client, admin_token):
    resp = client.put('/api/v1/asset/99999', json={'asset_name': 'x'}, headers=_auth(admin_token))
    assert resp.status_code == 404


def test_asset_delete_missing_returns_404(client, admin_token):
    resp = client.delete('/api/v1/asset/99999', headers=_auth(admin_token))
    assert resp.status_code == 404


# ---------- 告警规则 ----------
def _alert_payload(name='cpu-high'):
    return {'rule_name': name, 'metric': 'cpu_usage', 'threshold': '90', 'level': '严重', 'webhook': 'http://example.com/hook'}


def test_alert_list_and_create(client, admin_token, viewer_token):
    h_admin, h_viewer = _auth(admin_token), _auth(viewer_token)
    assert client.get('/api/v1/alert/rules', headers=h_viewer).status_code == 200
    created = client.post('/api/v1/alert/rules', json=_alert_payload(), headers=h_admin)
    assert created.status_code == 200
    assert created.json()['metric'] == 'cpu_usage'
    assert client.get('/api/v1/alert/rules', headers=h_viewer).json()[0]['rule_name'] == 'cpu-high'


def test_alert_create_forbidden_for_viewer(client, viewer_token):
    resp = client.post('/api/v1/alert/rules', json=_alert_payload(), headers=_auth(viewer_token))
    assert resp.status_code == 403


# ---------- Cron ----------
def test_cron_list_and_create(client, admin_token, viewer_token):
    h_admin, h_viewer = _auth(admin_token), _auth(viewer_token)
    assert client.get('/api/v1/cron/tasks', headers=h_viewer).status_code == 200
    created = client.post('/api/v1/cron/tasks', json={
        'task_name': 'nightly-backup', 'cron_expr': '0 2 * * *',
        'task_type': 'backup', 'task_content': 'run backup',
    }, headers=h_admin)
    assert created.status_code == 200
    assert created.json()['cron_expr'] == '0 2 * * *'


def test_cron_create_forbidden_for_viewer(client, viewer_token):
    resp = client.post('/api/v1/cron/tasks', json={
        'task_name': 'x', 'cron_expr': '* * * * *', 'task_type': 'shell', 'task_content': 'echo 1',
    }, headers=_auth(viewer_token))
    assert resp.status_code == 403


# ---------- 部署项目 ----------
def test_deploy_list_create_run(client, admin_token, viewer_token):
    h_admin, h_viewer = _auth(admin_token), _auth(viewer_token)
    assert client.get('/api/v1/deploy/projects', headers=h_viewer).status_code == 200
    created = client.post('/api/v1/deploy/projects', json={
        'project_name': 'demo-app', 'git_url': 'https://github.com/demo/app.git', 'env_type': 'prod',
    }, headers=h_admin)
    assert created.status_code == 200
    run = client.post(f"/api/v1/deploy/projects/{created.json()['id']}/run", headers=h_admin)
    assert run.status_code == 200
    assert run.json()['status'] == 'submitted'


def test_deploy_run_forbidden_for_viewer(client, admin_token, viewer_token):
    created = client.post('/api/v1/deploy/projects', json={
        'project_name': 'a', 'git_url': 'https://github.com/a/b.git', 'env_type': 'dev',
    }, headers=_auth(admin_token)).json()
    resp = client.post(f"/api/v1/deploy/projects/{created['id']}/run", headers=_auth(viewer_token))
    assert resp.status_code == 403


# ---------- 用户管理边界 ----------
def test_user_create_duplicate_returns_409(client, admin_token):
    resp = client.post('/api/v1/user/', json={
        'username': 'admin', 'password': 'whatever1', 'nickname': 'dup',
    }, headers=_auth(admin_token))
    assert resp.status_code == 409


def test_user_create_invalid_role_returns_400(client, admin_token):
    resp = client.post('/api/v1/user/', json={
        'username': 'ghost', 'password': 'whatever1', 'nickname': 'g', 'role_id': 999,
    }, headers=_auth(admin_token))
    assert resp.status_code == 400


def test_user_list_admin_only(client, admin_token, viewer_token):
    assert client.get('/api/v1/user/', headers=_auth(admin_token)).status_code == 200
    assert client.get('/api/v1/user/', headers=_auth(viewer_token)).status_code == 403


# ---------- 批量执行记录 ----------
def test_exec_records_listing(client, admin_token):
    resp = client.get('/api/v1/exec/records', headers=_auth(admin_token))
    assert resp.status_code == 200
    assert resp.json() == []  # 尚无执行记录


# ---------- 无效载荷（422） ----------
def test_invalid_payload_returns_422(client, admin_token):
    resp = client.post('/api/v1/asset/', json={'asset_name': 'no-ip'}, headers=_auth(admin_token))
    assert resp.status_code == 422