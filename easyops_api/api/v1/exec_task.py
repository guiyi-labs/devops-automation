import json
from celery import group
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database.session import get_db
from database.models import ExecRecord, ServerAsset, SysUser
from dependencies import get_current_user
from schemas.all import BatchExecRequest, ExecRecordOut
from tasks.exec_tasks import batch_exec_command
router = APIRouter()
@router.post('/batch')
def batch_exec(payload: BatchExecRequest, db: Session = Depends(get_db), user: SysUser = Depends(get_current_user)):
    assets = db.query(ServerAsset).filter(ServerAsset.id.in_(payload.asset_ids)).all()
    record = ExecRecord(asset_ids=','.join(map(str,payload.asset_ids)), command=payload.command, exec_user=user.username, exec_status=0)
    db.add(record); db.commit(); db.refresh(record)
    job = group(batch_exec_command.s(a.ip_address, a.ssh_port, a.ssh_user, a.ssh_pwd or '', payload.command) for a in assets)()
    record.exec_result = json.dumps({'record_id': record.id, 'celery_group_id': job.id}, ensure_ascii=False); db.commit()
    return {'record_id': record.id, 'group_id': job.id, 'hosts': [a.ip_address for a in assets]}
@router.get('/records', response_model=list[ExecRecordOut])
def records(db: Session = Depends(get_db)): return db.query(ExecRecord).order_by(ExecRecord.id.desc()).limit(100).all()
