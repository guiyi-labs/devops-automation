"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-14

EasyOps 全量初始表结构（E2 引入 Alembic 时的基线迁移）。
包含 E1 新增的 audit_log / system_flag / host_key_fingerprint。
MySQL 5.7 与 SQLite 通用；server_default 使用 CURRENT_TIMESTAMP 保证跨库一致。
"""
from alembic import op
import sqlalchemy as sa

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

NOW = sa.text('CURRENT_TIMESTAMP')


def upgrade() -> None:
    op.create_table(
        'sys_role',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('role_name', sa.String(50), nullable=False),
        sa.Column('role_code', sa.String(50), nullable=False, unique=True),
        sa.Column('description', sa.String(255), nullable=True),
        sa.Column('create_time', sa.DateTime(), nullable=False, server_default=NOW),
    )

    op.create_table(
        'sys_user',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('username', sa.String(50), nullable=False, unique=True),
        sa.Column('password', sa.String(128), nullable=False),
        sa.Column('nickname', sa.String(50), nullable=False),
        sa.Column('email', sa.String(100), nullable=True),
        sa.Column('phone', sa.String(20), nullable=True),
        sa.Column('role_id', sa.Integer(), sa.ForeignKey('sys_role.id'), nullable=False, server_default='1'),
        sa.Column('status', sa.SmallInteger(), nullable=False, server_default='1'),
        sa.Column('create_time', sa.DateTime(), nullable=False, server_default=NOW),
        sa.Column('update_time', sa.DateTime(), nullable=False, server_default=NOW, onupdate=NOW),
    )

    op.create_table(
        'server_asset',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('asset_name', sa.String(100), nullable=False),
        sa.Column('ip_address', sa.String(50), nullable=False),
        sa.Column('ssh_port', sa.Integer(), nullable=False, server_default='22'),
        sa.Column('ssh_user', sa.String(50), nullable=False),
        sa.Column('ssh_pwd', sa.String(512), nullable=True),
        sa.Column('ssh_key', sa.Text(), nullable=True),
        sa.Column('host_key_fingerprint', sa.String(255), nullable=True),
        sa.Column('os_type', sa.String(50), nullable=True),
        sa.Column('env_type', sa.String(20), nullable=False, server_default='dev'),
        sa.Column('business_group', sa.String(100), nullable=True),
        sa.Column('online_status', sa.SmallInteger(), nullable=False, server_default='0'),
        sa.Column('cpu', sa.String(50), nullable=True),
        sa.Column('mem', sa.String(50), nullable=True),
        sa.Column('disk', sa.String(50), nullable=True),
        sa.Column('create_time', sa.DateTime(), nullable=False, server_default=NOW),
        sa.Column('update_time', sa.DateTime(), nullable=False, server_default=NOW, onupdate=NOW),
    )
    op.create_index('ix_server_asset_ip_address', 'server_asset', ['ip_address'])

    op.create_table(
        'exec_record',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('asset_ids', sa.String(255), nullable=False),
        sa.Column('command', sa.Text(), nullable=False),
        sa.Column('exec_user', sa.String(50), nullable=False),
        sa.Column('exec_status', sa.SmallInteger(), nullable=False, server_default='0'),
        sa.Column('exec_result', sa.Text(), nullable=True),
        sa.Column('create_time', sa.DateTime(), nullable=False, server_default=NOW),
    )

    op.create_table(
        'deploy_project',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('project_name', sa.String(100), nullable=False),
        sa.Column('git_url', sa.String(255), nullable=False),
        sa.Column('git_branch', sa.String(50), nullable=False, server_default='main'),
        sa.Column('build_script', sa.Text(), nullable=True),
        sa.Column('deploy_script', sa.Text(), nullable=True),
        sa.Column('env_type', sa.String(20), nullable=False),
        sa.Column('status', sa.SmallInteger(), nullable=False, server_default='1'),
        sa.Column('create_time', sa.DateTime(), nullable=False, server_default=NOW),
    )

    op.create_table(
        'cron_task',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('task_name', sa.String(100), nullable=False),
        sa.Column('cron_expr', sa.String(50), nullable=False),
        sa.Column('task_type', sa.String(50), nullable=False),
        sa.Column('task_content', sa.Text(), nullable=False),
        sa.Column('status', sa.SmallInteger(), nullable=False, server_default='1'),
        sa.Column('create_time', sa.DateTime(), nullable=False, server_default=NOW),
    )

    op.create_table(
        'alert_rule',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('rule_name', sa.String(100), nullable=False),
        sa.Column('metric', sa.String(100), nullable=False),
        sa.Column('threshold', sa.String(50), nullable=False),
        sa.Column('level', sa.String(20), nullable=False),
        sa.Column('webhook', sa.String(255), nullable=False),
        sa.Column('status', sa.SmallInteger(), nullable=False, server_default='1'),
        sa.Column('create_time', sa.DateTime(), nullable=False, server_default=NOW),
    )

    op.create_table(
        'audit_log',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('username', sa.String(50), nullable=False, server_default='anonymous'),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('method', sa.String(10), nullable=True),
        sa.Column('path', sa.String(255), nullable=True),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('ip_address', sa.String(50), nullable=True),
        sa.Column('detail', sa.String(512), nullable=True),
        sa.Column('create_time', sa.DateTime(), nullable=False, server_default=NOW),
    )

    op.create_table(
        'system_flag',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('flag_key', sa.String(50), nullable=False, unique=True),
        sa.Column('flag_value', sa.String(255), nullable=False),
        sa.Column('update_time', sa.DateTime(), nullable=False, server_default=NOW, onupdate=NOW),
    )


def downgrade() -> None:
    op.drop_table('system_flag')
    op.drop_table('audit_log')
    op.drop_table('alert_rule')
    op.drop_table('cron_task')
    op.drop_table('deploy_project')
    op.drop_table('exec_record')
    op.drop_index('ix_server_asset_ip_address', table_name='server_asset')
    op.drop_table('server_asset')
    op.drop_table('sys_user')
    op.drop_table('sys_role')
