from datetime import datetime, timedelta

import jwt
from passlib.context import CryptContext

from config import settings
pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
def hash_password(password: str) -> str: return pwd_context.hash(password)
def verify_password(plain: str, hashed: str) -> bool: return pwd_context.verify(plain, hashed)
def create_access_token(data: dict, expires_minutes: int | None = None) -> str:
    payload = data.copy()
    payload['exp'] = datetime.utcnow() + timedelta(minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
