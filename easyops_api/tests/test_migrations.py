"""E3：Alembic 迁移往返测试（upgrade 0001→0002 → downgrade → 重升 → 0002）。

验证 0002 在 SQLite batch 模式下的数据保存、新表创建和回滚正确。
此测试在独立 SQLite 文件上运行，与 conftest 的 create_all 隔离。
"""
import os
import sqlite3

from alembic import command as alembic_cmd
from alembic.config import Config as AlembicConfig

# Alembic 环境配置（相对 easyops_api 目录）
_HERE = os.path.dirname(__file__)
_ALEMBIC_CFG = AlembicConfig(os.path.join(_HERE, '..', 'alembic.ini'))
_ALEMBIC_CFG.attributes['connect_args'] = {'check_same_thread': False}


def _make_db_url(path: str) -> str:
    return f'sqlite:///{path}'


def _get_tables(db_path: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    conn.close()
    # 排除 alembic_version 与 SQLite 内部/临时表
    return {t for t in tables
            if not t.startswith('sqlite_')
            and not t.startswith('_exec_record')}


def _get_columns(db_path: str, table: str) -> list[str]:
    conn = sqlite3.connect(db_path)
    cols = [r[1] for r in conn.execute(f'PRAGMA table_info({table})')]
    conn.close()
    return cols


def _insert_seed(db_path: str) -> None:
    """在 0001 的 exec_record（exec_status 列）写入种子数据。"""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO exec_record(asset_ids, command, exec_user, exec_status) VALUES('1','uptime','admin',0)"
    )
    conn.commit()
    conn.close()


def _get_exec_record_row(db_path: str) -> tuple:
    conn = sqlite3.connect(db_path)
    row = conn.execute('SELECT id, asset_ids, command, exec_user, status, exec_result FROM exec_record').fetchone()
    conn.close()
    return row


def test_migration_round_trip(tmp_path: str) -> None:
    db_path = os.path.join(str(tmp_path), 'test_mig.db')

    # --- upgrade to 0001 ---
    os.environ['DATABASE_URL'] = _make_db_url(db_path)  # env.py 优先使用此变量
    _ALEMBIC_CFG.set_main_option('sqlalchemy.url', _make_db_url(db_path))
    alembic_cmd.upgrade(_ALEMBIC_CFG, '0001')
    tables_0001 = _get_tables(db_path)
    assert 'exec_record' in tables_0001
    assert 'exec_host_result' not in tables_0001
    assert 'server_asset' in tables_0001

    # 插入种子行（使用旧 schema：exec_status 列存在）
    _insert_seed(db_path)

    # --- upgrade to 0002 ---
    alembic_cmd.upgrade(_ALEMBIC_CFG, '0002')
    tables_0002 = _get_tables(db_path)
    assert 'exec_host_result' in tables_0002
    er_cols = _get_columns(db_path, 'exec_record')
    assert 'status' in er_cols
    assert 'idempotency_key' in er_cols
    assert 'exec_status' not in er_cols  # 旧列已删
    hr_cols = _get_columns(db_path, 'exec_host_result')
    assert 'record_id' in hr_cols
    assert 'stdout' in hr_cols
    assert 'stderr' in hr_cols

    # 种子数据保留，status 映射为 pending
    row = _get_exec_record_row(db_path)
    assert row is not None, '种子行应保留'
    assert row[4] == 'pending'  # status = pending（exec_status=0 默认）

    # --- downgrade to 0001 ---
    alembic_cmd.downgrade(_ALEMBIC_CFG, '0001')
    tables_d = _get_tables(db_path)
    assert 'exec_host_result' not in tables_d
    er_cols_d = _get_columns(db_path, 'exec_record')
    assert 'exec_status' in er_cols_d

    # --- re-upgrade to 0002 ---
    alembic_cmd.upgrade(_ALEMBIC_CFG, '0002')
    tables_r = _get_tables(db_path)
    assert 'exec_host_result' in tables_r
    row_r = _get_exec_record_row(db_path)
    assert row_r is not None

    # --- upgrade to 0003（E4 巡检表） ---
    alembic_cmd.upgrade(_ALEMBIC_CFG, '0003')
    tables_0003 = _get_tables(db_path)
    for t in ('inspection_record', 'host_inspection', 'inspection_rule'):
        assert t in tables_0003, f'0003 缺少表 {t}'
    assert 'rule_results' in _get_columns(db_path, 'host_inspection')

    # --- downgrade back to 0002 ---
    alembic_cmd.downgrade(_ALEMBIC_CFG, '0002')
    tables_d2 = _get_tables(db_path)
    assert not ({'inspection_record', 'host_inspection', 'inspection_rule'} & tables_d2)

    # --- upgrade to 0004（E5 部署/备份表） ---
    alembic_cmd.upgrade(_ALEMBIC_CFG, '0004')
    tables_0004 = _get_tables(db_path)
    for t in ('deploy_release', 'backup_record'):
        assert t in tables_0004, f'0004 缺少表 {t}'
    dr_cols = _get_columns(db_path, 'deploy_release')
    assert 'project_id' in dr_cols and 'image_digest' in dr_cols and 'exec_user' in dr_cols
    br_cols = _get_columns(db_path, 'backup_record')
    assert 'checksum' in br_cols and 'checksum_ok' in br_cols and 'exec_user' in br_cols

    # --- downgrade back to 0003 ---
    alembic_cmd.downgrade(_ALEMBIC_CFG, '0003')
    tables_d3 = _get_tables(db_path)
    assert not ({'deploy_release', 'backup_record'} & tables_d3)


def test_migration_head_matches_models(tmp_path: str) -> None:
    """迁移 head 建表与模型声明元数据表名完全匹配。"""
    db_path = os.path.join(str(tmp_path), 'head.db')
    os.environ['DATABASE_URL'] = _make_db_url(db_path)
    _ALEMBIC_CFG.set_main_option('sqlalchemy.url', _make_db_url(db_path))
    alembic_cmd.upgrade(_ALEMBIC_CFG, 'head')
    from database.models import BackupRecord, DeployRelease, ExecRecord, ExecHostResult
    from database.models import HostInspection, InspectionRecord, InspectionRule
    expected = {t.__tablename__ for t in [ExecRecord, ExecHostResult, HostInspection,
                                          InspectionRecord, InspectionRule,
                                          DeployRelease, BackupRecord]}
    actual = _get_tables(db_path)
    missing = expected - actual
    assert not missing, f'迁移 head 缺少表: {missing}'

    er_cols = _get_columns(db_path, 'exec_record')
    assert 'idempotency_key' in er_cols
    assert 'confirm_token' in er_cols

    hr_cols = _get_columns(db_path, 'exec_host_result')
    assert 'host' in hr_cols
    assert 'exit_code' in hr_cols

    hi_cols = _get_columns(db_path, 'host_inspection')
    assert 'facts' in hi_cols
    assert 'rule_results' in hi_cols
    assert 'unavailable_reason' in hi_cols


def _get_operator_declared_type(db_path: str) -> str | None:
    """返回 inspection_rule.operator 列的 SQLite 类型声明。"""
    conn = sqlite3.connect(db_path)
    row = conn.execute('PRAGMA table_info(inspection_rule)').fetchall()
    conn.close()
    for col in row:
        if col[1] == 'operator':
            return col[2]
    return None


def test_migration_0005_widens_rule_operator(tmp_path: str) -> None:
    """0005：inspection_rule.operator 从 VARCHAR(10) 加宽到 VARCHAR(20)。

    真实 MySQL 严格模式暴露 not_contains（12 字符）超长；SQLite 不校验宽度，
    所以该测试验证迁移往返 + 加宽后默认规则可完整写入。
    """
    db_path = os.path.join(str(tmp_path), 'rule_op.db')
    os.environ['DATABASE_URL'] = _make_db_url(db_path)
    _ALEMBIC_CFG.set_main_option('sqlalchemy.url', _make_db_url(db_path))

    # 升到 0004（修复前宽度）
    alembic_cmd.upgrade(_ALEMBIC_CFG, '0004')
    assert _get_operator_declared_type(db_path) == 'VARCHAR(10)'

    # 0005 加宽
    alembic_cmd.upgrade(_ALEMBIC_CFG, '0005')
    assert _get_operator_declared_type(db_path) == 'VARCHAR(20)'

    # 加宽后默认规则（含 not_contains）可写入
    conn = sqlite3.connect(db_path)
    try:
        from services.inspection_rules import default_rules
        for rule in default_rules():
            conn.execute(
                'INSERT INTO inspection_rule(name, description, metric, operator, threshold, severity, enabled)'
                ' VALUES(?,?,?,?,?,?,1)',
                (rule['name'], rule.get('description'), rule['metric'],
                 rule['operator'], rule['threshold'], rule['severity']),
            )
        conn.commit()
        n = conn.execute('SELECT COUNT(*) FROM inspection_rule').fetchone()[0]
        assert n == len(default_rules()), f'应写入 {len(default_rules())} 条规则，实际 {n}'
    finally:
        conn.close()

    # 往返：downgrade 回 0004 恢复 VARCHAR(10)
    alembic_cmd.downgrade(_ALEMBIC_CFG, '0004')
    assert _get_operator_declared_type(db_path) == 'VARCHAR(10)'

    # 重新升级到 head 保持一致
    alembic_cmd.upgrade(_ALEMBIC_CFG, 'head')
    assert _get_operator_declared_type(db_path) == 'VARCHAR(20)'
