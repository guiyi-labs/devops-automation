"""0006: E5-P2 real deployment target binding.

Real releases must point at a registered ServerAsset. The column stays nullable
for historical mock-only DeployProject rows; the real executor fails closed
when it is absent.

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def _is_sqlite() -> bool:
    bind = op.get_bind()
    engine = getattr(bind, 'engine', None)
    return str(getattr(engine, 'url', '')).startswith('sqlite')


def upgrade() -> None:
    column = sa.Column('target_asset_id', sa.Integer(), nullable=True)
    if _is_sqlite():
        with op.batch_alter_table('deploy_project') as batch_op:
            batch_op.add_column(column)
            batch_op.create_index('ix_deploy_project_target_asset_id', ['target_asset_id'])
    else:
        op.add_column('deploy_project', column)
        op.create_index('ix_deploy_project_target_asset_id', 'deploy_project', ['target_asset_id'])
        op.create_foreign_key(
            'fk_deploy_project_target_asset_id', 'deploy_project', 'server_asset',
            ['target_asset_id'], ['id'],
        )


def downgrade() -> None:
    if _is_sqlite():
        with op.batch_alter_table('deploy_project') as batch_op:
            batch_op.drop_index('ix_deploy_project_target_asset_id')
            batch_op.drop_column('target_asset_id')
    else:
        op.drop_constraint('fk_deploy_project_target_asset_id', 'deploy_project', type_='foreignkey')
        op.drop_index('ix_deploy_project_target_asset_id', table_name='deploy_project')
        op.drop_column('deploy_project', 'target_asset_id')
