"""E5 备份/恢复 API：创建备份、查询记录、恢复、保留策略。

保留策略：创建备份先落 running 记录；Worker 校验通过才 succeeded。
仅 succeeded 备份可恢复；失败/校验失败的备份不会成为「最后一份有效备份」。
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database.models import BackupRecord, SysUser
from database.session import get_db
from dependencies import get_current_user, require_write
from schemas.all import BackupRecordOut

router = APIRouter()


def _audit(request, db, username, action, status_code, detail) -> None:
    from database.models import AuditLog
    db.add(AuditLog(username=username, action=action, method=request.method,
                    path=str(request.url.path)[:255], status_code=status_code,
                    ip_address=request.client.host if request.client else None,
                    detail=detail[:512]))
    db.commit()


@router.post('/create', response_model=BackupRecordOut)
def create_backup(body: dict | None = None, request: Request = None,
                  user: SysUser = Depends(require_write), db: Session = Depends(get_db)):
    """创建一次 MySQL 逻辑备份任务。"""
    body = body or {}
    record = BackupRecord(
        op_type='backup', status='running', backup_engine='mysql_dump',
        database=body.get('database') or 'easyops', exec_user=user.username,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    from tasks.backup_tasks import run_backup_job
    run_backup_job.delay(record.id)
    _audit(request, db, user.username, 'backup_create', 200, f'创建备份 #{record.id}')
    return record


@router.post('/restore', response_model=BackupRecordOut)
def restore_backup(body: dict, request: Request, user: SysUser = Depends(require_write),
                   db: Session = Depends(get_db)):
    """从一份 validated 备份执行恢复。"""
    backup_id = body.get('backup_id')
    if not backup_id:
        raise HTTPException(status_code=400, detail='backup_id 必填')
    backup = db.query(BackupRecord).filter(BackupRecord.id == backup_id).first()
    if not backup or backup.op_type != 'backup':
        raise HTTPException(status_code=404, detail='备份记录不存在')
    if backup.status != 'succeeded' or not backup.checksum_ok:
        raise HTTPException(status_code=400, detail='只能从校验通过的备份恢复')
    record = BackupRecord(
        op_type='restore', status='running', backup_engine=backup.backup_engine,
        database=backup.database, exec_user=user.username,
        result='{"restore_from": %d}' % backup.id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    from tasks.backup_tasks import run_restore_job
    run_restore_job.delay(record.id)
    _audit(request, db, user.username, 'backup_restore', 200,
           f'从备份 #{backup_id} 恢复（restore #{record.id}）')
    return record


@router.get('/records', response_model=list[BackupRecordOut])
def list_records(user: SysUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(BackupRecord).order_by(BackupRecord.id.desc()).limit(100).all()


@router.get('/records/{record_id}', response_model=BackupRecordOut)
def get_record(record_id: int, user: SysUser = Depends(get_current_user),
               db: Session = Depends(get_db)):
    record = db.query(BackupRecord).filter(BackupRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail='备份记录不存在')
    return record


@router.get('/policy')
def backup_policy(user: SysUser = Depends(get_current_user)):
    """当前保留策略（返回说明；真实保留数为 E5 第二阶段对接文件系统）。"""
    return {
        'strategy': '失败备份不覆盖最后一份有效备份；仅校验通过的备份可恢复',
        'valid_engine': 'mysql_dump',
        'max_records_shown': 100,
    }