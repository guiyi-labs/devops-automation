from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database.session import get_db
from database.models import SysUser, SysRole
from schemas.all import LoginRequest, UserCreate, UserOut
from common.security import create_access_token, hash_password, verify_password
router = APIRouter()
@router.post('/login')
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(SysUser).filter(SysUser.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password): raise HTTPException(status_code=401, detail='用户名或密码错误')
    return {'access_token': create_access_token({'sub': user.username}), 'token_type': 'bearer', 'user': UserOut.model_validate(user)}
@router.post('/', response_model=UserOut)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    user = SysUser(**payload.model_dump(exclude={'password'}), password=hash_password(payload.password)); db.add(user); db.commit(); db.refresh(user); return user
@router.get('/', response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)): return db.query(SysUser).order_by(SysUser.id.desc()).all()
@router.post('/init-admin')
def init_admin(db: Session = Depends(get_db)):
    if not db.query(SysRole).filter(SysRole.role_code == 'admin').first(): db.add(SysRole(role_name='管理员', role_code='admin', description='系统管理员'))
    if not db.query(SysUser).filter(SysUser.username == 'admin').first(): db.add(SysUser(username='admin', password=hash_password('admin123'), nickname='系统管理员', role_id=1, status=1))
    db.commit(); return {'username':'admin','password':'admin123'}
