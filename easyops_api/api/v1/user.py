from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from common.security import create_access_token, hash_password, verify_password
from config import settings
from database.models import AuditLog, SysRole, SysUser, SystemFlag
from database.session import get_db
from dependencies import require_admin
from schemas.all import LoginRequest, UserCreate, UserOut

router = APIRouter()

# 角色种子：admin(系统管理员) / operator(运维操作员) / viewer(只读)
ROLE_SEEDS = [
    ('admin', '系统管理员', '拥有全部权限'),
    ('operator', '运维操作员', '可执行资产、批量任务、部署等写操作'),
    ('viewer', '只读用户', '只能查看数据，不能执行写操作'),
]


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


@router.post('/login')
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.query(SysUser).filter(SysUser.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password):
        _audit(request, db, payload.username, 'login_failed', 401, '用户名或密码错误')
        raise HTTPException(status_code=401, detail='用户名或密码错误')
    if user.status != 1:
        _audit(request, db, user.username, 'login_disabled', 401, '已禁用用户尝试登录')
        raise HTTPException(status_code=401, detail='账号已禁用')
    _audit(request, db, user.username, 'login_success', 200, '登录成功')
    return {
        'access_token': create_access_token({'sub': user.username}),
        'token_type': 'bearer',
        'user': UserOut.model_validate(user),
    }


@router.post('/init-admin')
def init_admin(request: Request, db: Session = Depends(get_db)):
    """一次性 bootstrap：创建三角色 + admin 用户；完成后自动关闭。

    重复调用返回 409。管理员初始密码取自 INITIAL_ADMIN_PASSWORD 环境变量。
    """
    flag = db.query(SystemFlag).filter(SystemFlag.flag_key == 'admin_bootstrapped').first()
    if flag and flag.flag_value == 'true':
        raise HTTPException(status_code=409, detail='管理员已初始化，无法重复执行')
    if db.query(SysUser).filter(SysUser.username == 'admin').first():
        # 已有 admin 用户但未打标记，视为已初始化，补打标记后拒绝继续使用默认流程
        if not flag:
            db.add(SystemFlag(flag_key='admin_bootstrapped', flag_value='true'))
            db.commit()
        raise HTTPException(status_code=409, detail='管理员已存在，无法重复执行')

    for role_code, role_name, desc in ROLE_SEEDS:
        if not db.query(SysRole).filter(SysRole.role_code == role_code).first():
            db.add(SysRole(role_name=role_name, role_code=role_code, description=desc))
    db.flush()
    admin_role = db.query(SysRole).filter(SysRole.role_code == 'admin').first()
    db.add(SysUser(
        username='admin',
        password=hash_password(settings.INITIAL_ADMIN_PASSWORD),
        nickname='系统管理员',
        role_id=admin_role.id,
        status=1,
    ))
    if not flag:
        db.add(SystemFlag(flag_key='admin_bootstrapped', flag_value='true'))
    else:
        flag.flag_value = 'true'
    db.commit()
    _audit(request, db, 'admin', 'init_admin', 200, '一次性管理员初始化完成')
    return {'username': 'admin', 'message': '管理员初始化成功（请立即修改默认密码）'}


@router.get('/', response_model=list[UserOut])
def list_users(user: SysUser = Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(SysUser).order_by(SysUser.id.desc()).all()


@router.post('/', response_model=UserOut)
def create_user(payload: UserCreate, request: Request, user: SysUser = Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(SysUser).filter(SysUser.username == payload.username).first():
        raise HTTPException(status_code=409, detail='用户名已存在')
    role = db.get(SysRole, payload.role_id)
    if not role:
        raise HTTPException(status_code=400, detail='角色不存在')
    new_user = SysUser(
        **payload.model_dump(exclude={'password'}),
        password=hash_password(payload.password),
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    _audit(request, db, user.username, 'user_create', 200, f'创建用户 {new_user.username}（角色 {role.role_name}）')
    return new_user