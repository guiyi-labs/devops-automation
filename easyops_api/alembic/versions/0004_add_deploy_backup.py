"""0004: 部署与备份（E5）— deploy_release / backup_record。

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-15
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None

NOW = sa.text('CURRENT_TIMESTAMP')


def upgrade() -> None:
    op.create_table(
        'deploy_release',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('deploy_project.id'), nullable=False),
        sa.Column('release_type', sa.String(20), nullable=False, server_default='deploy'),
        sa.Column('status', sa.String(30), nullable=False, server_default='requested'),
        sa.Column('git_ref', sa.String(100)),
        sa.Column('image', sa.String(255)),
        sa.Column('image_digest', sa.String(255)),
        sa.Column('version', sa.String(50)),
        sa.Column('exec_user', sa.String(50), nullable=False),
        sa.Column('result', sa.Text()),
        sa.Column('create_time', sa.DateTime(), nullable=False, server_default=NOW),
        sa.Column('update_time', sa.DateTime(), nullable=False, server_default=NOW),
    )
    op.create_index('ix_deploy_release_project_id', 'deploy_release', ['project_id'])

    op.create_table(
        'backup_record',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('op_type', sa.String(20), nullable=False, server_default='backup'),
        sa.Column('status', sa.String(20), nullable=False, server_default='running'),
        sa.Column('file_path', sa.String(255)),
        sa.Column('file_size_bytes', sa.Integer()),
        sa.Column('mysql_dump_path', sa.String(255)),
        sa.Column('backup_engine', sa.String(50), nullable=False, server_default='mysql_dump'),
        sa.Column('database', sa.String(50)),
        sa.Column('checksum', sa.String(64)),
        sa.Column('checksum_ok', sa.SmallInteger(), nullable=False, server_default='0'),
        sa.Column('validation', sa.Text()),
        sa.Column('exec_user', sa.String(50), nullable=False),
        sa.Column('result', sa.Text()),
        sa.Column('create_time', sa.DateTime(), nullable=False, server_default=NOW),
        sa.Column('update_time', sa.DateTime(), nullable=False, server_default=NOW),
    )


def downgrade() -> None:
    op.drop_table('deploy_release')
    op.drop_table('backup_record')