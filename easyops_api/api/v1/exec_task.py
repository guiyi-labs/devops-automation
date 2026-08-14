import json

from celery import group
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database.models import AuditLog, ExecRecord, ServerAsset, SysUser
from database.session import get_db
from dependencies import get_current_user, require_write
from schemas.all import BatchExecRequest, ExecRecordOut
from tasks.exec_tasks import batch_exec_command

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


@router.post('/batch')
def batch_exec(
    payload: BatchExecRequest,
    request: Request,
    user: SysUser = Depends(require_write),
    db: Session = Depends(get_db),
):
    if not payload.asset_ids:
        raise HTTPException(status_code=400, detail='至少选择一个资产')
    if len(payload.asset_ids) > 50:
        raise HTTPException(status_code=400, detail='单任务资产数不能超过 50')
    assets = db.query(ServerAsset).filter(ServerAsset.id.in_(payload.asset_ids)).all()
    found_ids = {a.id for a in assets}
    missing = [i for i in payload.asset_ids if i not in found_ids]
    if missing:
        raise HTTPException(status_code=400, detail=f'资产不存在: {missing}')

    record = ExecRecord(
        asset_ids=','.join(map(str, payload.asset_ids)),
        command=payload.command,
        exec_user=user.username,
        exec_status=0,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    # 只传 asset_id 与命令：SSH 凭据由 Worker 从数据库读取并在内存中解密，
    # 不进入 Celery 消息/Redis。
    job = group(batch_exec_command.s(a.id, payload.command) for a in assets)()
    record.exec_result = json.dumps({'record_id': record.id, 'celery_group_id': job.id}, ensure_ascii=False)
    db.commit()
    _audit(request, db, user.username, 'exec_batch', 200,
           f'批量执行：{len(assets)} 台主机，命令长度 {len(payload.command)}')
    return {'record_id': record.id, 'group_id': job.id, 'hosts': [a.ip_address for a in assets]}


@router.get('/records', response_model=list[ExecRecordOut])
def records(user: SysUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(ExecRecord).order_by(ExecRecord.id.desc()).limit(100).all()