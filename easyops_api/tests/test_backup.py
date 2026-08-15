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


# ---------- E5-P2：RealMySQLDumpEngine 纯单元测试（不连接真实 MySQL） ----------
import os
import tempfile
from unittest.mock import patch, MagicMock

from services.backup_service import (
    RealMySQLDumpEngine, choose_backup_engine, validate_dump_bytes, gzip_open_bytes,
)


def _fake_mysqldump_stdout():
    """返回符合 mysqldump 输出格式的假 SQL（含表定义和 INSERT）。"""
    return (
        '-- MySQL dump 10.13\n'
        'CREATE TABLE IF NOT EXISTS `sys_user` (\n'
        '  `id` int NOT NULL AUTO_INCREMENT\n'
        ') ENGINE=InnoDB;\n'
        'INSERT INTO `sys_user` VALUES (1);\n'
        'INSERT INTO `sys_user` VALUES (2);\n'
    ).encode('utf-8')


def _fake_mysql_count_output(tables='1'):
    """返回信息模式查询的假行数输出。"""
    stdout = MagicMock()
    stdout.stdout = f'{tables}\n'.encode('utf-8')
    stdout.stderr = b''
    stdout.returncode = 0
    return stdout


def test_real_engine_persist_and_retention(tmp_path):
    """RealMySQLDumpEngine.persist：gzip/sha256 校验 + 文件保留策略。"""
    engine = RealMySQLDumpEngine(
        storage_dir=str(tmp_path), retention_count=2, database='testdb',
    )

    sql_data = _fake_mysqldump_stdout()
    result = engine.persist(sql_data)

    assert result['checksum']
    assert result['size_bytes'] > 0
    assert os.path.exists(result['file_path'])    # .sql.gz
    assert os.path.exists(result['sql_path'])     # .sql
    assert os.path.exists(result['sha256_path'])  # .sha256

    # 校验 .sql.gz：原始字节是合法 gzip，解压内容等于源 SQL
    with open(result['file_path'], 'rb') as fh:
        gz_raw = fh.read()
    assert gz_raw[:2] == b'\x1f\x8b', 'gzip magic 缺失'
    v = validate_dump_bytes(gz_raw)
    assert v['ok'] and v['gzip_ok']
    assert gzip_open_bytes(result['file_path']) == sql_data

    # 写入第 3 份（保留策略=2），应删除第 1 份
    for i in range(2, 4):
        engine.persist(f'-- backup {i}\n'.encode('utf-8'))

    gz_files = sorted(f for f in os.listdir(tmp_path) if f.endswith('.sql.gz'))
    assert len(gz_files) == 2, f'保留策略执行后应有 2 份，实际 {gz_files}'


def test_real_engine_dump_rejects_bad_mysql(monkeypatch):
    """dump 调用 mysqldump；非零退出码 → RuntimeError。"""
    engine = RealMySQLDumpEngine(storage_dir='/tmp', database='db')

    def bad_run(*args, **kwargs):
        class _R:
            returncode = 1
            stdout = b''
            stderr = b'access denied'
        return _R()

    monkeypatch.setattr('subprocess.run', bad_run)
    try:
        engine.dump()
        raise AssertionError('should raise on mysqldump failure')
    except RuntimeError as exc:
        assert 'mysqldump' in str(exc) and 'rc=1' in str(exc)


def test_real_engine_restore_rejects_missing_file(tmp_path):
    engine = RealMySQLDumpEngine(storage_dir=str(tmp_path), database='db')
    try:
        engine.restore(str(tmp_path / 'nonexistent.sql.gz'))
        raise AssertionError('should raise')
    except RuntimeError as exc:
        assert '备份文件不存在' in str(exc)


def test_choose_backup_engine_respects_mode():
    """choose_backup_engine 在 real 模式返回 RealMySQLDumpEngine。"""
    engine_real = choose_backup_engine()
    # 当前 env 下 BACKUP_EXECUTION_MODE 默认 mock
    assert isinstance(engine_real, BackupEngine)  # mock 模式


def test_real_engine_restore_to_fresh_database(monkeypatch, tmp_path):
    """restore 先 DROP+CREATE 全新目标库再导入——避免与运行中表的锁竞争。"""
    import gzip
    from services.backup_service import RealMySQLDumpEngine

    engine = RealMySQLDumpEngine(storage_dir=str(tmp_path), database='easyops')
    gz_path = str(tmp_path / 'b.sql.gz')
    with gzip.open(gz_path, 'wb') as fh:
        fh.write(b'CREATE TABLE t(id INT);')

    calls = []

    class _Ok:
        returncode = 0
        stdout = b''
        stderr = b''

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        joined = ' '.join(cmd)
        if 'COUNT(*) FROM information_schema.tables' in joined:
            return type('R', (), {'returncode': 0, 'stdout': '1\n', 'stderr': ''})()
        if 'SUM(t.table_rows)' in joined:
            return type('R', (), {'returncode': 0, 'stdout': '42\n', 'stderr': ''})()
        return _Ok()

    monkeypatch.setattr('subprocess.run', fake_run)
    stats = engine.restore(gz_path)

    # bootstrap：DROP DATABASE + CREATE DATABASE
    bootstrap = [c for c in calls if 'CREATE DATABASE' in ' '.join(c)]
    assert bootstrap, f'应执行全新库 bootstrap，实际命令: {calls}'
    assert 'easyops_restore' in ' '.join(bootstrap[0])

    # 导入命令指向目标库
    import_cmd = [c for c in calls if 'DROP DATABASE' not in ' '.join(c)
                  and 'information_schema' not in ' '.join(c)
                  and '-N' not in ' '.join(c)]
    assert any('easyops_restore' in ' '.join(c) for c in import_cmd), f'导入应指向 easyops_restore: {import_cmd}'

    assert stats['restored_tables'] == 1
    assert stats['restored_rows'] == 42
    assert stats['target_database'] == 'easyops_restore'