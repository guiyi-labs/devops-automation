from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config import settings

# 确定数据库 URL：DATABASE_URL 优先（测试注入），其次拼 MySQL
if settings.DATABASE_URL:
    SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL
else:
    SQLALCHEMY_DATABASE_URL = (
        f'mysql+pymysql://{settings.MYSQL_USER}:{settings.MYSQL_PASSWORD}'
        f'@{settings.MYSQL_HOST}:{settings.MYSQL_PORT}/{settings.MYSQL_DB}?charset=utf8mb4'
    )

# SQLite 需要 check_same_thread=False 且 StaticPool 才能让内存库在多线程中共享
engine_kwargs: dict = {'pool_pre_ping': True}
if SQLALCHEMY_DATABASE_URL.startswith('sqlite'):
    engine_kwargs = {
        'connect_args': {'check_same_thread': False},
    }
    # 内存 SQLite 在多线程下用 StaticPool 保持同一连接
    if ':memory:' in SQLALCHEMY_DATABASE_URL:
        from sqlalchemy.pool import StaticPool
        engine_kwargs['poolclass'] = StaticPool
else:
    engine_kwargs['pool_recycle'] = 3600

engine = create_engine(SQLALCHEMY_DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()