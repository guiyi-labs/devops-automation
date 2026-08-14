from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from common.crypto import encrypt_value, is_encrypted
from common.redact import register_secret
from database.models import AuditLog, ServerAsset, SysUser
from database.session import get_db
from dependencies import get_current_user, require_write
from schemas.all import AssetCreate, AssetOut, AssetUpdate

router = APIRouter()


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


def _asset_to_out(asset: ServerAsset) -> dict:
    """资产输出：只暴露凭据存在性标记，绝不返回明文密码 / 私钥。"""
    return {
        'id': asset.id,
        'asset_name': asset.asset_name,
        'ip_address': asset.ip_address,
        'ssh_port': asset.ssh_port,
        'ssh_user': asset.ssh_user,
        'has_password': bool(asset.ssh_pwd),
        'has_private_key': bool(asset.ssh_key),
        'host_key_fingerprint': asset.host_key_fingerprint,
        'os_type': asset.os_type,
        'env_type': asset.env_type,
        'business_group': asset.business_group,
        'online_status': asset.online_status,
        'cpu': asset.cpu,
        'mem': asset.mem,
        'disk': asset.disk,
    }


def _encrypt_credential(value: str | None) -> str | None:
    """加密凭据；已是密文则原样保留。明文会同时注册进脱敏池。"""
    if not value:
        return None
    if is_encrypted(value):
        return value
    register_secret(value)
    return encrypt_value(value)


@router.get('/', response_model=list[AssetOut])
def list_assets(user: SysUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_asset_to_out(a) for a in db.query(ServerAsset).order_by(ServerAsset.id.desc()).all()]


@router.post('/', response_model=AssetOut)
def create_asset(payload: AssetCreate, request: Request, user: SysUser = Depends(require_write), db: Session = Depends(get_db)):
    data = payload.model_dump()
    data['ssh_pwd'] = _encrypt_credential(data.get('ssh_pwd'))
    data['ssh_key'] = _encrypt_credential(data.get('ssh_key'))
    item = ServerAsset(**data)
    db.add(item)
    db.commit()
    db.refresh(item)
    _audit(request, db, user.username, 'asset_create', 200, f'创建资产 {item.asset_name} ({item.ip_address})')
    return _asset_to_out(item)


@router.put('/{asset_id}', response_model=AssetOut)
def update_asset(asset_id: int, payload: AssetUpdate, request: Request, user: SysUser = Depends(require_write), db: Session = Depends(get_db)):
    item = db.get(ServerAsset, asset_id)
    if not item:
        raise HTTPException(status_code=404, detail='资产不存在')
    data = payload.model_dump(exclude_unset=True)
    if 'ssh_pwd' in data:
        data['ssh_pwd'] = _encrypt_credential(data['ssh_pwd'])
    if 'ssh_key' in data:
        data['ssh_key'] = _encrypt_credential(data['ssh_key'])
    for k, v in data.items():
        setattr(item, k, v)
    db.commit()
    db.refresh(item)
    _audit(request, db, user.username, 'asset_update', 200, f'更新资产 {item.asset_name} ({item.ip_address})')
    return _asset_to_out(item)


@router.delete('/{asset_id}')
def delete_asset(asset_id: int, request: Request, user: SysUser = Depends(require_write), db: Session = Depends(get_db)):
    item = db.get(ServerAsset, asset_id)
    if not item:
        raise HTTPException(status_code=404, detail='资产不存在')
    db.delete(item)
    db.commit()
    _audit(request, db, user.username, 'asset_delete', 200, f'删除资产 {item.asset_name} ({item.ip_address})')
    return {'ok': True}