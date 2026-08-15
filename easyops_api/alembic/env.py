# Alembic 环境配置（EasyOps）。
#
# - 迁移连接优先使用 DATABASE_URL（生产部署注入），否则回退到 config.Settings 的 MySQL 连接串。
# - 迁移元数据从 database.models 导入，确保与运行时模型一致。
# - SQLite（测试/CI）批量变更时需要 batch 模式；MySQL 不需要。
#
# 命令示例：
#   DATABASE_URL=sqlite:///easyops.db alembic upgrade head
#   DATABASE_URL=mysql+pymysql://root:pass@127.0.0.1:3306/easyops alembic upgrade head
import os

from alembic import context
from sqlalchemy import create_engine

from config import settings
from database import models  # noqa: F401  确保模型已注册
from database.session import Base

target_metadata = Base.metadata

# 迁移连接优先读取实时 DATABASE_URL（env.py 每次执行都重新读取，CI/测试可用
# 环境变量注入；与 CLI 行为一致），未设置时回退到 config.Settings 的 MySQL 连接串
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    DATABASE_URL = (
        f'mysql+pymysql://{settings.MYSQL_USER}:{settings.MYSQL_PASSWORD}'
        f'@{settings.MYSQL_HOST}:{settings.MYSQL_PORT}/{settings.MYSQL_DB}?charset=utf8mb4'
    )

# SQLite 的 ALTER/DROP 需要 batch 模式渲染，MySQL 不需要
is_sqlite = DATABASE_URL.startswith('sqlite')


def run_migrations_offline():
    """离线模式：只输出 SQL，不连接数据库。"""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """在线模式：连接数据库执行迁移。"""
    connectable = create_engine(DATABASE_URL)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=is_sqlite,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()