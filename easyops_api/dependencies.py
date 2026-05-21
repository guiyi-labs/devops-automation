from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from config import settings
from database.session import get_db
from database.models import SysUser
oauth2_scheme = OAuth2PasswordBearer(tokenUrl='/api/v1/user/login')
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> SysUser:
    exc = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='认证失败')
    try:
        username = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]).get('sub')
    except JWTError:
        raise exc
    user = db.query(SysUser).filter(SysUser.username == username).first()
    if not user: raise exc
    return user
