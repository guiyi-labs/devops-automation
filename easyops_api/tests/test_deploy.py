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