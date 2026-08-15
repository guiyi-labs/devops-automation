"""E5：备份恢复测试——创建、Worker 校验、恢复一致性、保留策略（mock Celery）。"""
from unittest.mock import patch

from services.backup_service import BackupEngine, validate_dump_bytes, sha256_of, fake_dump_bytes
from tasks.backup_tasks import run_backup_job, run_restore_job


class _FakeDelay:
    def __init__(self, *a, **kw):
        pass
    def delay(self, *a, **kw):
        return self


def _auth(token):
    return {'Authorization': f'Bearer {token}'}


# ---------- 纯函数校验 ----------
def test_validate_dump_gzip_ok():
    data = fake_dump_bytes()
    result = validate_dump_bytes(data)
    assert result['ok'] is True
    assert result['gzip_ok'] is True
    assert result['size_bytes'] > 0
    assert result['checksum'] == sha256_of(data)


def test_validate_dump_non_gzip():
    data = b'CREATE TABLE t(id INT);'
    result = validate_dump_bytes(data)
    assert result['ok'] is True
    assert result['gzip_ok'] is False  # 非 gzip，不是错误（plain sql dump）
    assert result['size_bytes'] == len(data)


def test_validate_dump_empty():
    result = validate_dump_bytes(b'')
    assert result['ok'] is False


def test_validate_dump_corrupt_gzip():
    # 以 gzip magic 开头但内容损坏
    result = validate_dump_bytes(b'\x1f\x8b\x08corrupt-data')
    assert result['ok'] is False


def test_backup_engine_dump_and_check():
    engine = BackupEngine()
    data = engine.dump()
    assert len(data) > 0
    v = validate_dump_bytes(data)
    assert v['ok'] is True
    check = engine.consistency_check(data)
    assert check['consistent'] is True
    assert check['restored_rows'] >= 0
    assert 'sys_user' in check['restored_tables']


# ---------- API + Worker ----------
def test_backup_create_and_run(client, admin_token):
    with patch('tasks.backup_tasks.run_backup_job', _FakeDelay()):
        resp = client.post('/api/v1/backup/create', json={'database': 'easyops'},
                           headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    record_id = resp.json()['id']
    result = run_backup_job.run(record_id)
    assert result['status'] == 'succeeded'
    assert result['checksum']
    records = client.get('/api/v1/backup/records', headers=_auth(admin_token)).json()
    assert any(r['id'] == record_id and r['status'] == 'succeeded' for r in records)


def test_backup_restore_flow(client, admin_token):
    with patch('tasks.backup_tasks.run_backup_job', _FakeDelay()):
        backup_resp = client.post('/api/v1/backup/create', json={},
                                  headers=_auth(admin_token)).json()
    run_backup_job.run(backup_resp['id'])

    with patch('tasks.backup_tasks.run_restore_job', _FakeDelay()):
        resp = client.post('/api/v1/backup/restore',
                           json={'backup_id': backup_resp['id']}, headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    restore_id = resp.json()['id']
    result = run_restore_job.run(restore_id)
    assert result['status'] == 'succeeded'
    assert result['consistent'] is True


def test_backup_restore_reject_invalid(client, admin_token):
    """只能从校验通过的备份恢复。"""
    with patch('tasks.backup_tasks.run_backup_job', _FakeDelay()):
        bad = client.post('/api/v1/backup/create', json={}, headers=_auth(admin_token)).json()
    # Worker 未运行 → status 仍为 running（非 succeeded）
    resp = client.post('/api/v1/backup/restore', json={'backup_id': bad['id']},
                       headers=_auth(admin_token))
    assert resp.status_code == 400
    assert '校验通过' in resp.json()['detail']


def test_backup_restore_no_missing_id(client, admin_token):
    resp = client.post('/api/v1/backup/restore', json={'backup_id': 99999},
                       headers=_auth(admin_token))
    assert resp.status_code in (400, 404)


def test_backup_policy(client, admin_token):
    resp = client.get('/api/v1/backup/policy', headers=_auth(admin_token))
    assert resp.status_code == 200
    assert '不覆盖' in resp.json()['strategy']


def test_backup_permission_viewer(client, viewer_token):
    resp = client.post('/api/v1/backup/create', json={}, headers=_auth(viewer_token))
    assert resp.status_code in (400, 403)


def test_backup_records_requires_login(client):
    resp = client.get('/api/v1/backup/records')
    assert resp.status_code == 401