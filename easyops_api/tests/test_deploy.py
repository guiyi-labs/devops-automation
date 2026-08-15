"""E5：受控部署计划测试——预览、发布、回滚、白名单、权限（mock Celery）。"""
from unittest.mock import patch

from services import deploy_service
from tasks.deploy_tasks import run_deploy_release, run_rollback_release


class _FakeDelay:
    """替代 Celery .delay()：不连 broker，Worker 由测试直接 .run() 调用。"""

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def delay(self, *args, **kwargs):
        return self


def _auth(token):
    return {'Authorization': f'Bearer {token}'}


def _create_project(client, token, name='demo-app', git='https://github.com/demo/app.git'):
    resp = client.post('/api/v1/deploy/projects', json={
        'project_name': name, 'git_url': git, 'git_branch': 'main', 'env_type': 'dev',
    }, headers=_auth(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _run_task(client, task, *args):
    """派发时替换 delay → 立即同步执行任务（测试 Worker 逻辑）。"""
    sentinel = []

    class _Immediate:
        def delay(self, *a):
            sentinel.append(task.run(*a))
            return self

    return sentinel


def test_deploy_preview_plan(client, admin_token):
    project = _create_project(client, admin_token)
    resp = client.post(f"/api/v1/deploy/projects/{project['id']}/preview",
                       json={'version': 'v1.0.0', 'port': 9090}, headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    plan = resp.json()['plan']
    assert plan['steps'] == ['pull', 'build', 'up', 'healthcheck']
    assert plan['image'] == 'easyops/demo-app'
    assert plan['version'] == 'v1.0.0'
    assert plan['port'] == 9090
    assert resp.json()['rollback_point'] is None  # 尚无成功发布


def test_deploy_preview_forbidden_viewer(client, admin_token, viewer_token):
    project = _create_project(client, admin_token)
    resp = client.post(f"/api/v1/deploy/projects/{project['id']}/preview",
                       headers=_auth(viewer_token))
    assert resp.status_code == 403


def test_deploy_release_worker_success(client, admin_token):
    project = _create_project(client, admin_token)
    with patch('tasks.deploy_tasks.run_deploy_release', _FakeDelay()):
        resp = client.post('/api/v1/deploy/releases', json={
            'project_id': project['id'], 'version': 'v1.0.0', 'port': 9090,
        }, headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    release_id = resp.json()['release_id']
    # 同步执行 Worker
    result = run_deploy_release.run(release_id)
    assert result['status'] == 'succeeded'
    release = client.get(f'/api/v1/deploy/releases/{release_id}',
                         headers=_auth(admin_token)).json()
    assert release['status'] == 'succeeded'
    assert release['image'] == 'easyops/demo-app'
    assert release['image_digest'].startswith('sha256:')


def test_deploy_release_worker_step_failure_marks_failed(client, admin_token):
    project = _create_project(client, admin_token)
    with patch('tasks.deploy_tasks.run_deploy_release', _FakeDelay()):
        resp = client.post('/api/v1/deploy/releases', json={
            'project_id': project['id'], 'version': 'v1.0.0',
        }, headers=_auth(admin_token))
    release_id = resp.json()['release_id']
    # 注入失败 runner：healthcheck 失败 → 整个 release failed
    def failing_runner(step, ctx):
        if step == 'healthcheck':
            raise RuntimeError('healthcheck timeout')
        return f'{step} ok'

    with patch.object(deploy_service, 'run_deploy_steps',
                      side_effect=lambda plan: deploy_service.run_deploy_steps(plan, runner=failing_runner)):
        result = run_deploy_release.run(release_id)
    assert result['status'] == 'failed'


def test_deploy_rollback_flow(client, admin_token):
    project = _create_project(client, admin_token)
    # 先部署一个成功发布（回滚点）
    with patch('tasks.deploy_tasks.run_deploy_release', _FakeDelay()):
        first = client.post('/api/v1/deploy/releases', json={
            'project_id': project['id'], 'version': 'v1.0.0',
        }, headers=_auth(admin_token)).json()
    assert run_deploy_release.run(first['release_id'])['status'] == 'succeeded'
    # 再部署一个新版本
    with patch('tasks.deploy_tasks.run_deploy_release', _FakeDelay()):
        second = client.post('/api/v1/deploy/releases', json={
            'project_id': project['id'], 'version': 'v2.0.0',
        }, headers=_auth(admin_token)).json()
    assert run_deploy_release.run(second['release_id'])['status'] == 'succeeded'
    # 回滚到 v1.0.0（最近成功发布）
    with patch('tasks.deploy_tasks.run_rollback_release', _FakeDelay()):
        resp = client.post(f"/api/v1/deploy/releases/{second['release_id']}/rollback",
                           headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()['rollback_to'] == first['release_id']
    rollback_id = resp.json()['rollback_id']
    result = run_rollback_release.run(rollback_id)
    assert result['status'] == 'rollback_succeeded'
    # 发布记录应有 3 条（2 部署 + 1 回滚）
    releases = client.get(f"/api/v1/deploy/projects/{project['id']}/releases",
                          headers=_auth(admin_token)).json()
    assert len(releases) == 3


def test_deploy_rollback_without_valid_point(client, admin_token):
    project = _create_project(client, admin_token)
    # 未部署成功 → 无回滚点
    with patch('tasks.deploy_tasks.run_deploy_release', _FakeDelay()):
        release = client.post('/api/v1/deploy/releases', json={
            'project_id': project['id'], 'version': 'v1.0.0',
        }, headers=_auth(admin_token)).json()
    # 直接失败（未运行 Worker，无 succeeded 发布）
    resp = client.post(f"/api/v1/deploy/releases/{release['release_id']}/rollback",
                       headers=_auth(admin_token))
    assert resp.status_code == 400


def test_deploy_allowed_steps_whitelist():
    plan = deploy_service.DeployPlan(
        project_id=1, template='compose-web', image='easyops/a', version='1',
        port=8080, steps=['pull', 'rm -rf /'],  # 注入非法步骤
    )
    results = deploy_service.run_deploy_steps(plan, runner=lambda s, c: f'{s} ok')
    assert results[0]['ok'] is True
    assert results[1]['ok'] is False
    assert '白名单' in results[1]['output']

    # 非法步骤在中间：该步失败即中止，不再继续
    plan2 = deploy_service.DeployPlan(
        project_id=1, template='compose-web', image='easyops/a', version='1',
        port=8080, steps=['pull', 'evil', 'up'],
    )
    results2 = deploy_service.run_deploy_steps(plan2, runner=lambda s, c: f'{s} ok')
    assert results2[1]['ok'] is False
    assert len(results2) == 2  # up 未执行


def test_deploy_run_endpoint_removed(client, admin_token):
    """E2 占位 POST /projects/{id}/run 已移除（改为受控计划端点）。"""
    project = _create_project(client, admin_token)
    resp = client.post(f"/api/v1/deploy/projects/{project['id']}/run",
                       headers=_auth(admin_token))
    assert resp.status_code in (404, 405)


def test_deploy_templates_list(client, admin_token):
    resp = client.get('/api/v1/deploy/templates', headers=_auth(admin_token))
    assert resp.status_code == 200
    assert 'compose-web' in resp.json()['templates']


# ---------- E5-P2：plan 校验边界 ----------
def test_validate_plan_rejects_bad_inputs():
    from services.deploy_service import DeployPlan, validate_plan
    import pytest

    cases = [
        {'image': 'UPPER/NO', 'version': '1', 'port': 8080},
        {'image': 'easyops/a', 'version': 'v1; rm -rf /', 'port': 8080},
        {'image': 'easyops/a', 'version': '1', 'port': 80},      # 端口 < 1024
        {'image': 'easyops/a', 'version': '1', 'port': 70000},   # 端口 > 65535
        {'image': 'easyops/a', 'version': '1', 'port': 8080, 'template': 'unknown-tpl'},
    ]
    for kw in cases:
        template = kw.pop('template', 'compose-web')
        plan = DeployPlan(project_id=1, template=template, steps=['pull'], **kw)
        with pytest.raises(ValueError):
            validate_plan(plan)


def test_compose_document_binds_localhost_port_only():
    from services.deploy_service import DeployPlan, _compose_document
    plan = DeployPlan(project_id=1, template='compose-web', image='easyops/nginx', version='1.2', port=9090,
                      steps=['up'])
    doc = _compose_document(plan)
    assert 'image: easyops/nginx:1.2' in doc
    assert '127.0.0.1:9090:80' in doc
    assert 'restart: unless-stopped' in doc


# ---------- E5-P2：RemoteComposeRunner 命令构造（不真正连接） ----------
def test_remote_runner_builds_safe_commands(monkeypatch):
    from unittest.mock import MagicMock

    from services.deploy_service import RemoteComposeRunner, DeployPlan

    plan = DeployPlan(project_id=42, template='compose-web', image='easyops/demo', version='v2.1', port=9090,
                      steps=['pull', 'up', 'healthcheck'], target_asset_id=7)
    asset = MagicMock()
    asset.ip_address = '192.0.2.10'
    asset.ssh_port = 22
    asset.ssh_user = 'easyops-lab'
    asset.host_key_fingerprint = 'sha256:abcdef'

    captured = []

    def fake_connect_and_run(*args, **kwargs):
        captured.append((args, kwargs))
        return {'stdout': 'ok', 'stderr': ''}

    monkeypatch.setattr('services.deploy_service.connect_and_run', fake_connect_and_run)
    runner = RemoteComposeRunner(asset=asset, plan=plan, release_id=99,
                                 password=None, private_key=None)

    # up 命令必须只包含允许的操作
    up_cmd = runner._up_command()
    assert 'docker compose -p easyops-p42' in up_cmd
    assert 'easyops/demo:v2.1' in up_cmd
    assert 'base64 -d' in up_cmd   # compose 内容经 base64 传
    assert ';' in up_cmd
    # 不允许的项目脚本不出现
    assert 'build_script' not in up_cmd and 'deploy_script' not in up_cmd

    # 非法步骤
    try:
        runner('evil', {})
        raise AssertionError('should raise')
    except ValueError:
        pass

    # build 步骤不执行任何命令
    assert runner('build', {}) == '模板使用固定镜像；未执行项目 build_script/deploy_script'


# ---------- E5-P2：real 模式 fail-closed ----------
def _force_real_executor(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, 'DEPLOY_EXECUTION_MODE', 'real')


def test_resolve_runner_fail_closed_without_target(monkeypatch):
    from tasks import deploy_tasks
    from services.deploy_service import DeployPlan

    _force_real_executor(monkeypatch)
    plan = DeployPlan(project_id=1, template='compose-web', image='easyops/a', version='1', port=8080,
                      steps=['pull'], target_asset_id=None)
    try:
        deploy_tasks._resolve_runner(None, plan, release_id=1)
        raise AssertionError('should raise for missing target_asset_id')
    except RuntimeError as exc:
        assert 'target_asset_id' in str(exc)


def test_resolve_runner_fails_for_unregistered_asset(monkeypatch):
    from tasks import deploy_tasks
    from services.deploy_service import DeployPlan

    _force_real_executor(monkeypatch)
    plan = DeployPlan(project_id=1, template='compose-web', image='easyops/a', version='1', port=8080,
                      steps=['pull'], target_asset_id=7)
    # mock db：资产不存在
    class _FakeQuery:
        def filter(self, *a, **kw):
            return self

        def first(self):
            return None

    class _FakeDb:
        def query(self, model):
            return _FakeQuery()

    try:
        deploy_tasks._resolve_runner(_FakeDb(), plan, release_id=1)
        raise AssertionError('should raise for missing asset')
    except RuntimeError as exc:
        assert '目标资产不存在' in str(exc)