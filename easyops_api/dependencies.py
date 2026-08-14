from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
import jwt as pyjwt
from sqlalchemy.orm import Session

from common.redact import register_secret
from config import settings
from database.models import AuditLog, SysUser
from database.session import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl='/api/v1/user/login')

# 角色码：admin(系统管理员) / operator(运维操作员) / viewer(只读)
ROLE_ADMIN = 'admin'
ROLE_OPERATOR = 'operator'
ROLE_VIEWER = 'viewer'
WRITE_ROLES = (ROLE_ADMIN, ROLE_OPERATOR)


def _decode_username(token: str) -> str:
    payload = pyjwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    username = payload.get('sub')
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='认证失败')
    return username


def _audit(request: Request, db: Session, username: str, action: str, status_code: int, detail: str) -> None:
    db.add(AuditLog(
        username=username or 'anonymous',
        action=action,
        method=request.method,
        path=str(request.url.path)[:255],
        status_code=status_code,
        ip_address=request.client.host if request.client else None,
        detail=detail[:512],
    ))
    db.commit()


def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> SysUser:
    """统一登录校验：Token 有效 + 用户存在 + 未被禁用。"""
    exc = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='认证失败')
    try:
        username = _decode_username(token)
    except pyjwt.InvalidTokenError:
        raise exc
    user = db.query(SysUser).filter(SysUser.username == username).first()
    if not user:
        raise exc
    if user.status != 1:
        _audit(request, db, user.username, 'permission_denied', 401, '账号已禁用，Token 失效')
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='账号已禁用')
    return user


def require_write(
    request: Request,
    user: SysUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SysUser:
    """写操作：仅 admin / operator 可用；viewer 或匿名返回 403 并审计。"""
    role_code = user.role.role_code if user.role else None
    if role_code not in WRITE_ROLES:
        _audit(request, db, user.username, 'permission_denied', 403,
               f'写权限不足（role={role_code or "none"}，path={request.url.path}）')
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='无写权限')
    return user


def require_admin(
    request: Request,
    user: SysUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SysUser:
    """管理操作：仅 admin 可用。"""
    role_code = user.role.role_code if user.role else None
    if role_code != ROLE_ADMIN:
        _audit(request, db, user.username, 'permission_denied', 403,
               f'需要管理员权限（role={role_code or "none"}，path={request.url.path}）')
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail='需要管理员权限')
    return user


def audit_register_credentials(*values: str | None) -> None:
    """把涉及明文的凭据注册进脱敏池，防止进入日志/异常。"""
    for value in values:
        if value:
            register_secret(value)