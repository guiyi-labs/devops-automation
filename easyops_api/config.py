import os
import sys

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 环境标识: development | production | testing
    APP_ENV: str = os.getenv('APP_ENV', 'development')

    # 数据库（DATABASE_URL 存在时优先，测试用 sqlite）
    DATABASE_URL: str | None = os.getenv('DATABASE_URL')
    MYSQL_HOST: str = os.getenv('MYSQL_HOST', 'localhost')
    MYSQL_PORT: int = int(os.getenv('MYSQL_PORT', '3306'))
    MYSQL_USER: str = os.getenv('MYSQL_USER', 'root')
    MYSQL_PASSWORD: str = os.getenv('MYSQL_PASSWORD', 'root123456')
    MYSQL_DB: str = os.getenv('MYSQL_DB', 'easyops')

    # Redis
    REDIS_HOST: str = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT: int = int(os.getenv('REDIS_PORT', '6379'))

    # JWT
    SECRET_KEY: str = os.getenv('SECRET_KEY', 'dev-only-insecure-default-secret-key-not-for-production')
    ALGORITHM: str = 'HS256'
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120

    # Celery
    CELERY_BROKER_URL: str = os.getenv('CELERY_BROKER_URL', f'redis://{REDIS_HOST}:{REDIS_PORT}/0')
    CELERY_RESULT_BACKEND: str = os.getenv('CELERY_RESULT_BACKEND', f'redis://{REDIS_HOST}:{REDIS_PORT}/0')

    # 管理员初始化密码（init-admin 一次性 bootstrap 使用）
    INITIAL_ADMIN_PASSWORD: str = os.getenv('INITIAL_ADMIN_PASSWORD', 'admin123')

    # SSH 凭据加密主密钥（账密/私钥落库前使用 Fernet 加密）
    CREDENTIAL_ENCRYPTION_KEY: str = os.getenv(
        'CREDENTIAL_ENCRYPTION_KEY', 'dev-only-insecure-credential-key-not-for-production'
    )

    # CORS 白名单（逗号分隔），禁止 allow_origins=['*'] 与 credentials 组合
    CORS_ORIGINS: str = os.getenv('CORS_ORIGINS', 'http://localhost:8080,http://localhost:5173')

    # SSH host key：false 时未登记指纹的主机默认拒绝连接
    SSH_ALLOW_UNVERIFIED_HOST_KEY: bool = os.getenv('SSH_ALLOW_UNVERIFIED_HOST_KEY', 'false').lower() == 'true'

    # E3 受控批量执行：
    # - 单任务资产上限（前端/后端双重校验）
    BATCH_MAX_ASSETS: int = 50
    # - 单任务 Celery Worker 并发上限
    BATCH_CONCURRENCY: int = int(os.getenv('BATCH_CONCURRENCY', '8'))
    # - Celery 硬超时（秒），超过则任务被终止并记为 failed
    EXEC_TASK_HARD_TIMEOUT: int = int(os.getenv('EXEC_TASK_HARD_TIMEOUT', '90'))
    # - break_glass 任意命令默认关闭；仅 admin 可经 API 打开
    BREAK_GLASS_DEFAULT: bool = os.getenv('BREAK_GLASS_DEFAULT', 'false').lower() == 'true'

    # E5 第二阶段：真实执行必须由 Compose 显式开启。默认 mock 保持本地单元测试
    # 与未配置环境的可预测性，避免误在未知主机或数据库上执行写操作。
    DEPLOY_EXECUTION_MODE: str = os.getenv('DEPLOY_EXECUTION_MODE', 'mock').lower()
    BACKUP_EXECUTION_MODE: str = os.getenv('BACKUP_EXECUTION_MODE', 'mock').lower()
    BACKUP_STORAGE_DIR: str = os.getenv('BACKUP_STORAGE_DIR', '/var/lib/easyops/backups')
    BACKUP_RETENTION_COUNT: int = int(os.getenv('BACKUP_RETENTION_COUNT', '7'))

    def is_production(self) -> bool:
        return self.APP_ENV.lower() in ('production', 'prod')

    def get_cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(',') if origin.strip()]

    def deploy_uses_real_executor(self) -> bool:
        return self.DEPLOY_EXECUTION_MODE == 'real'

    def backup_uses_real_executor(self) -> bool:
        return self.BACKUP_EXECUTION_MODE == 'real'


# 明显的开发/演示默认值，生产环境必须替换
DANGEROUS_DEFAULTS: dict[str, str] = {
    'SECRET_KEY': 'easyops-secret-key-2026-devops-project',
    'MYSQL_PASSWORD': 'root123456',
    'INITIAL_ADMIN_PASSWORD': 'admin123',
    'CREDENTIAL_ENCRYPTION_KEY': 'dev-only-insecure-credential-key-not-for-production',
}

settings = Settings()


def validate_settings() -> None:
    """非开发环境缺少关键 Secret 或使用危险默认值时拒绝启动。

    development/testing 允许使用本地演示默认值；production 必须显式提供
    SECRET_KEY / CREDENTIAL_ENCRYPTION_KEY，且不能使用默认密码。
    """
    if not settings.is_production():
        return

    errors: list[str] = []

    if not settings.SECRET_KEY:
        errors.append('SECRET_KEY 未配置（生产环境必填）')
    elif settings.SECRET_KEY == DANGEROUS_DEFAULTS['SECRET_KEY'] or 'dev-only' in settings.SECRET_KEY:
        errors.append('SECRET_KEY 使用了开发默认值（生产环境禁止）')

    if not settings.CREDENTIAL_ENCRYPTION_KEY:
        errors.append('CREDENTIAL_ENCRYPTION_KEY 未配置（生产环境必填）')
    elif 'dev-only' in settings.CREDENTIAL_ENCRYPTION_KEY.lower():
        errors.append('CREDENTIAL_ENCRYPTION_KEY 使用了开发默认值（生产环境禁止）')

    if not settings.MYSQL_PASSWORD or settings.MYSQL_PASSWORD == DANGEROUS_DEFAULTS['MYSQL_PASSWORD']:
        errors.append('MYSQL_PASSWORD 未配置或使用了默认值（生产环境禁止）')

    if not settings.INITIAL_ADMIN_PASSWORD or settings.INITIAL_ADMIN_PASSWORD == DANGEROUS_DEFAULTS['INITIAL_ADMIN_PASSWORD']:
        errors.append('INITIAL_ADMIN_PASSWORD 未配置或使用了默认值（生产环境禁止）')

    if errors:
        print('\n[EasyOps] 配置校验失败（APP_ENV=%s）:' % settings.APP_ENV, file=sys.stderr)
        for err in errors:
            print('  - ' + err, file=sys.stderr)
        print('[EasyOps] 请在启动前设置环境变量或写入 .env，参考 .env.example。退出。', file=sys.stderr)
        sys.exit(1)


validate_settings()
