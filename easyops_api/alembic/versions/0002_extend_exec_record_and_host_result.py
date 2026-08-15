"""extend exec_record and create exec_host_result

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-14

E3 受控批量运维：exec_record 增加幂等键/操作目录/确认令牌/聚合状态；
新增 exec_host_result 实现逐主机状态与输出追踪。
exec_status(SmallInteger) 改为 status(String(20))；SQLite 不支持 DROP COLUMN
因此使用 batch 模式：迁移在 SQLite 上重建 exec_record，在 MySQL 上 ALTER。
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

NOW = sa.text('CURRENT_TIMESTAMP')


def _is_sqlite():
    bind = op.get_bind()
    url = getattr(bind, 'engine', None)
    if url is None or not hasattr(url, 'url'):  # 兼容 Connection / Engine
        # Connection.engine 存在；直接 str(bind) 也可能带 dialect
        engine = getattr(bind, 'engine', bind)
        return str(getattr(engine, 'url', bind)).startswith('sqlite')
    return str(url.url).startswith('sqlite')


def upgrade() -> None:
    if _is_sqlite():
        # SQLite：新建表（含新列）→ 复制数据 → 删旧表 → 重命名
        op.create_table(
            '_exec_record_v2',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('asset_ids', sa.String(255), nullable=False),
            sa.Column('exec_type', sa.String(20), nullable=False, server_default='fixed'),
            sa.Column('operation', sa.String(50)),
            sa.Column('params', sa.Text()),
            sa.Column('command', sa.Text(), nullable=False),
            sa.Column('exec_user', sa.String(50), nullable=False),
            sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
            sa.Column('idempotency_key', sa.String(128)),
            sa.Column('confirm_token', sa.String(64)),
            sa.Column('worker_concurrency', sa.Integer(), nullable=False, server_default='5'),
            sa.Column('total_hosts', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('succeeded', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('failed', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('running', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('timed_out', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('exec_result', sa.Text()),
            sa.Column('create_time', sa.DateTime(), nullable=False, server_default=NOW),
        )
        op.execute("""
            INSERT INTO _exec_record_v2 (id, asset_ids, command, exec_user, exec_result, create_time)
            SELECT id, asset_ids, command, exec_user, exec_result, create_time FROM exec_record
        """)
        op.drop_table('exec_record')
        op.rename_table('_exec_record_v2', 'exec_record')
        op.create_index('ix_exec_record_idempotency_key', 'exec_record', ['idempotency_key'])
    else:
        # MySQL：原生 ALTER 加列、改类型、创建索引
        op.add_column('exec_record', sa.Column('exec_type', sa.String(20), nullable=False, server_default='fixed'))
        op.add_column('exec_record', sa.Column('operation', sa.String(50)))
        op.add_column('exec_record', sa.Column('params', sa.Text()))
        op.add_column('exec_record', sa.Column('status', sa.String(20), nullable=False, server_default='pending'))
        op.add_column('exec_record', sa.Column('idempotency_key', sa.String(128)))
        op.add_column('exec_record', sa.Column('confirm_token', sa.String(64)))
        op.add_column('exec_record', sa.Column('worker_concurrency', sa.Integer(), nullable=False, server_default='5'))
        op.add_column('exec_record', sa.Column('total_hosts', sa.Integer(), nullable=False, server_default='0'))
        op.add_column('exec_record', sa.Column('succeeded', sa.Integer(), nullable=False, server_default='0'))
        op.add_column('exec_record', sa.Column('failed', sa.Integer(), nullable=False, server_default='0'))
        op.add_column('exec_record', sa.Column('running', sa.Integer(), nullable=False, server_default='0'))
        op.add_column('exec_record', sa.Column('timed_out', sa.Integer(), nullable=False, server_default='0'))
        op.execute('UPDATE exec_record SET status = "pending" WHERE exec_status = 0')
        op.drop_column('exec_record', 'exec_status')
        op.create_index('ix_exec_record_idempotency_key', 'exec_record', ['idempotency_key'])

    # 逐主机结果表（新增）
    op.create_table(
        'exec_host_result',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('record_id', sa.Integer(), sa.ForeignKey('exec_record.id'), nullable=False),
        sa.Column('asset_id', sa.Integer(), nullable=False),
        sa.Column('host', sa.String(50), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='queued'),
        sa.Column('exit_code', sa.Integer()),
        sa.Column('stdout', sa.Text()),
        sa.Column('stderr', sa.Text()),
        sa.Column('error_type', sa.String(50)),
        sa.Column('error', sa.Text()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=NOW),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=NOW),
    )
    op.create_index('ix_exec_host_result_record_id', 'exec_host_result', ['record_id'])
    op.create_index('ix_exec_host_result_asset_id', 'exec_host_result', ['asset_id'])


def downgrade() -> None:
    op.drop_table('exec_host_result')
    if _is_sqlite():
        op.execute('DROP INDEX IF EXISTS ix_exec_record_idempotency_key')
        op.create_table(
            '_exec_record_v1',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('asset_ids', sa.String(255), nullable=False),
            sa.Column('command', sa.Text(), nullable=False),
            sa.Column('exec_user', sa.String(50), nullable=False),
            sa.Column('exec_status', sa.SmallInteger(), nullable=False, server_default='0'),
            sa.Column('exec_result', sa.Text()),
            sa.Column('create_time', sa.DateTime(), nullable=False, server_default=NOW),
        )
        op.execute("""
            INSERT INTO _exec_record_v1 (id, asset_ids, command, exec_user, exec_result, create_time)
            SELECT id, asset_ids, command, exec_user, exec_result, create_time FROM exec_record
        """)
        op.drop_table('exec_record')
        op.rename_table('_exec_record_v1', 'exec_record')
    else:
        op.execute('DROP INDEX IF EXISTS ix_exec_record_idempotency_key')
        op.execute('ALTER TABLE exec_record DROP COLUMN status, DROP COLUMN idempotency_key, DROP COLUMN confirm_token, DROP COLUMN worker_concurrency, DROP COLUMN total_hosts, DROP COLUMN succeeded, DROP COLUMN failed, DROP COLUMN running, DROP COLUMN timed_out, DROP COLUMN exec_type, DROP COLUMN operation, DROP COLUMN params')
