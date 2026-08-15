"""0005: 巡检规则 operator 列加宽（E4 真实验收修复）。

Real-MySQL strictly-mode 暴露：inspection_rule.operator 原为 String(10)，
容不下内置规则 not_contains（12 字符）。SQLite 不校验列宽所以测试未暴露。
Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    engine = getattr(bind, 'engine', None)
    url = str(getattr(engine, 'url', ''))
    if url.startswith('sqlite'):
        # SQLite 需要 batch 重建表以修改列类型
        with op.batch_alter_table('inspection_rule') as batch_op:
            batch_op.alter_column('operator', existing_type=sa.String(10),
                                  type_=sa.String(20), existing_nullable=False)
    else:
        # MySQL 原生 ALTER
        op.alter_column('inspection_rule', 'operator',
                        existing_type=sa.String(10), type_=sa.String(20),
                        existing_nullable=False)


def downgrade() -> None:
    bind = op.get_bind()
    engine = getattr(bind, 'engine', None)
    url = str(getattr(engine, 'url', ''))
    if url.startswith('sqlite'):
        with op.batch_alter_table('inspection_rule') as batch_op:
            batch_op.alter_column('operator', existing_type=sa.String(20),
                                  type_=sa.String(10), existing_nullable=False)
    else:
        op.alter_column('inspection_rule', 'operator',
                        existing_type=sa.String(20), type_=sa.String(10),
                        existing_nullable=False)