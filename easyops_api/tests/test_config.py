"""E1 验收 1/2：配置校验 —— 生产环境缺少关键 Secret 或使用危险默认值时拒绝启动。"""
import pytest

from config import settings, validate_settings

DEV_SECRET_KEY = 'easyops-secret-key-2026-devops-project'
DEV_CREDENTIAL_KEY = 'dev-only-insecure-credential-key-not-for-production'


def _set_prod(monkeypatch, **overrides):
    """切到生产模式并覆盖指定字段。"""
    for key, value in overrides.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(settings, 'APP_ENV', 'production')


def test_development_allows_defaults(monkeypatch):
    """开发环境允许本地演示默认值，不抛异常。"""
    monkeypatch.setattr(settings, 'APP_ENV', 'development')
    validate_settings()  # 不应抛 SystemExit


def test_production_rejects_default_secret_key(monkeypatch):
    """生产环境使用危险默认 SECRET_KEY 时拒绝启动。"""
    _set_prod(monkeypatch, SECRET_KEY=DEV_SECRET_KEY,
              CREDENTIAL_ENCRYPTION_KEY='a' * 48, MYSQL_PASSWORD='strong-pass', INITIAL_ADMIN_PASSWORD='strong-admin')
    with pytest.raises(SystemExit):
        validate_settings()


def test_production_rejects_missing_secret_key(monkeypatch):
    """生产环境缺少 SECRET_KEY 时拒绝启动。"""
    _set_prod(monkeypatch, SECRET_KEY='',
              CREDENTIAL_ENCRYPTION_KEY='a' * 48, MYSQL_PASSWORD='strong-pass', INITIAL_ADMIN_PASSWORD='strong-admin')
    with pytest.raises(SystemExit):
        validate_settings()


def test_production_rejects_default_credential_key(monkeypatch):
    """生产环境使用开发默认 CREDENTIAL_ENCRYPTION_KEY 时拒绝启动。"""
    _set_prod(monkeypatch, SECRET_KEY='x' * 48, CREDENTIAL_ENCRYPTION_KEY=DEV_CREDENTIAL_KEY,
              MYSQL_PASSWORD='strong-pass', INITIAL_ADMIN_PASSWORD='strong-admin')
    with pytest.raises(SystemExit):
        validate_settings()


def test_production_rejects_default_mysql_password(monkeypatch):
    """生产环境使用默认数据库密码时拒绝启动。"""
    _set_prod(monkeypatch, SECRET_KEY='x' * 48, CREDENTIAL_ENCRYPTION_KEY='a' * 48,
              MYSQL_PASSWORD='root123456', INITIAL_ADMIN_PASSWORD='strong-admin')
    with pytest.raises(SystemExit):
        validate_settings()


def test_production_accepts_secure_settings(monkeypatch, capsys):
    """生产环境全部使用强随机值时允许启动。"""
    _set_prod(monkeypatch, SECRET_KEY='s' * 48, CREDENTIAL_ENCRYPTION_KEY='c' * 48,
              MYSQL_PASSWORD='S3cure!Password', INITIAL_ADMIN_PASSWORD='Adm1n!Secure')
    validate_settings()  # 不应抛 SystemExit