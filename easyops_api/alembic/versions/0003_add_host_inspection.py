"""0003: 主机巡检（E4）— inspection_record / host_inspection / inspection_rule。

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-15
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 批量巡检记录（一次触发覆盖多台主机）
    op.create_table(
        'inspection_record',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('asset_ids', sa.String(512), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='running'),
        sa.Column('total_hosts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('succeeded', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('unknown', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('exec_user', sa.String(50), nullable=False),
        sa.Column('create_time', sa.DateTime(), nullable=False, server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('update_time', sa.DateTime(), nullable=False, server_default=sa.text('(CURRENT_TIMESTAMP)')),
    )
    op.create_index('ix_inspection_record_id', 'inspection_record', ['id'])

    # 单主机巡检结果
    op.create_table(
        'host_inspection',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('record_id', sa.Integer(), sa.ForeignKey('inspection_record.id'), nullable=True),
        sa.Column('asset_id', sa.Integer(), sa.ForeignKey('server_asset.id'), nullable=False),
        sa.Column('host', sa.String(50), nullable=False),
        sa.Column('overall_status', sa.String(20), nullable=False, server_default='unknown'),
        sa.Column('facts', sa.Text(), nullable=True),
        sa.Column('rule_results', sa.Text(), nullable=True),
        sa.Column('observed_at', sa.DateTime(), nullable=True),
        sa.Column('source', sa.String(20), nullable=False, server_default='ssh'),
        sa.Column('timeout_ms', sa.Integer(), nullable=True),
        sa.Column('unavailable_reason', sa.String(512), nullable=True),
        sa.Column('create_time', sa.DateTime(), nullable=False, server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('update_time', sa.DateTime(), nullable=False, server_default=sa.text('(CURRENT_TIMESTAMP)')),
    )
    op.create_index('ix_host_inspection_id', 'host_inspection', ['id'])
    op.create_index('ix_host_inspection_asset_id', 'host_inspection', ['asset_id'])
    op.create_index('ix_host_inspection_record_id', 'host_inspection', ['record_id'])

    # 可配置巡检规则
    op.create_table(
        'inspection_rule',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False, unique=True),
        sa.Column('description', sa.String(255), nullable=True),
        sa.Column('metric', sa.String(50), nullable=False),
        sa.Column('operator', sa.String(10), nullable=False),
        sa.Column('threshold', sa.String(100), nullable=False),
        sa.Column('severity', sa.String(20), nullable=False, server_default='warning'),
        sa.Column('enabled', sa.SmallInteger(), nullable=False, server_default='1'),
        sa.Column('create_time', sa.DateTime(), nullable=False, server_default=sa.text('(CURRENT_TIMESTAMP)')),
        sa.Column('update_time', sa.DateTime(), nullable=False, server_default=sa.text('(CURRENT_TIMESTAMP)')),
    )
    op.create_index('ix_inspection_rule_id', 'inspection_rule', ['id'])


def downgrade() -> None:
    op.drop_table('inspection_rule')
    op.drop_table('host_inspection')
    op.drop_table('inspection_record')