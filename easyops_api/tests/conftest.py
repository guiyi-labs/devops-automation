"""pytest 共享 fixture。

重要：必须在导入任何应用模块前设置 DATABASE_URL 指向 SQLite，
这样 database/session.py 才会创建 SQLite engine 而非 MySQL。
"""
import os

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
os.environ['APP_ENV'] = 'development'

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from common.security import hash_password  # noqa: E402
from database.models import SysRole, SysUser  # noqa: E402
from database.session import Base, SessionLocal, engine  # noqa: E402
from main import app  # noqa: E402

ROLE_SEEDS = [
    ('admin', '系统管理员', '拥有全部权限'),
    ('operator', '运维操作员', '可执行写操作'),
    ('viewer', '只读用户', '只能查看'),
]

USER_SEEDS = [
    ('admin', 'admin123', 'admin', 1),
    ('operator', 'operator123', 'operator', 1),
    ('viewer', 'viewer123', 'viewer', 1),
    ('disabled', 'disabled123', 'viewer', 0),
]


def _seed_roles():
    db = SessionLocal()
    try:
        for code, name, desc in ROLE_SEEDS:
            if not db.query(SysRole).filter(SysRole.role_code == code).first():
                db.add(SysRole(role_name=name, role_code=code, description=desc))
        db.commit()
    finally:
        db.close()


def _seed_users():
    db = SessionLocal()
    try:
        roles = {r.role_code: r for r in db.query(SysRole).all()}
        for username, password, role_code, status in USER_SEEDS:
            if not db.query(SysUser).filter(SysUser.username == username).first():
                db.add(SysUser(
                    username=username,
                    password=hash_password(password),
                    nickname=username,
                    role_id=roles[role_code].id,
                    status=status,
                ))
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _db():
    Base.metadata.create_all(bind=engine)
    _seed_roles()
    _seed_users()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client():
    return TestClient(app)


def _login(client, username: str, password: str) -> str:
    resp = client.post('/api/v1/user/login', json={'username': username, 'password': password})
    assert resp.status_code == 200, resp.text
    return resp.json()['access_token']


@pytest.fixture()
def admin_token(client):
    return _login(client, 'admin', 'admin123')


@pytest.fixture()
def operator_token(client):
    return _login(client, 'operator', 'operator123')


@pytest.fixture()
def viewer_token(client):
    return _login(client, 'viewer', 'viewer123')


def disabled_token(client):
    """禁用用户旧 Token：直接签发一个（禁用用户无法重新登录）。"""
    from common.security import create_access_token
    return create_access_token({'sub': 'disabled'})