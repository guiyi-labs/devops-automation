import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    MYSQL_HOST: str = os.getenv('MYSQL_HOST', 'localhost')
    MYSQL_PORT: int = int(os.getenv('MYSQL_PORT', '3306'))
    MYSQL_USER: str = os.getenv('MYSQL_USER', 'root')
    MYSQL_PASSWORD: str = os.getenv('MYSQL_PASSWORD', 'root123456')
    MYSQL_DB: str = os.getenv('MYSQL_DB', 'easyops')
    REDIS_HOST: str = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT: int = int(os.getenv('REDIS_PORT', '6379'))
    SECRET_KEY: str = os.getenv('SECRET_KEY', 'easyops-secret-key-2026-devops-project')
    ALGORITHM: str = 'HS256'
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120
    CELERY_BROKER_URL: str = os.getenv('CELERY_BROKER_URL', f'redis://{REDIS_HOST}:{REDIS_PORT}/0')
    CELERY_RESULT_BACKEND: str = os.getenv('CELERY_RESULT_BACKEND', f'redis://{REDIS_HOST}:{REDIS_PORT}/0')

settings = Settings()
