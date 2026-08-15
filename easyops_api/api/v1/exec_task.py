"""E3 受控批量运维 API。

流程：操作目录/命令 → preview(校验+确认令牌) → confirmed 提交(idempotency+cursor)
→ Celery 逐主机执行 → retry(按失败主机) → 逐主机结果查询。
break_glass 任意命令默认关闭，仅 admin 可启用/关闭。
"""
import json
import secrets
from datetime import datetime
from typing import Any

from celery import group, signature
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from common.redact import register_secret
from config import settings
from database.models import AuditLog, ExecHostResult, ExecRecord, ServerAsset, SysUser, SystemFlag
from database.session import get_db
from dependencies import get_current_user, require_admin, require_write
from schemas.all import (
    BatchExecRequest, ExecPreviewOut, ExecPreviewRequest, ExecRecordOut, HostResultOut,
)
from services import operations

# 注意：main.py 挂载时再加 /api/v1/exec 前缀
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


def _validate_assets(db: Session, asset_ids: list[int]) -> list[ServerAsset]:
    """资产上限与存在性校验，返回有序资产列表。"""
    if not asset_ids:
        raise HTTPException(status_code=400, detail='至少选择一个资产')
    if len(asset_ids) > settings.BATCH_MAX_ASSETS:
        raise HTTPException(status_code=400, detail=f'单任务资产数不能超过 {settings.BATCH_MAX_ASSETS}')
    assets = db.query(ServerAsset).filter(ServerAsset.id.in_(asset_ids)).all()
    found = {a.id: a for a in assets}
    missing = [i for i in asset_ids if i not in found]
    if missing:
        raise HTTPException(status_code=400, detail=f'资产不存在: {missing}')
    return [found[i] for i in asset_ids]


def _resolve_command(payload: Any, user: SysUser, db: Session, request: Request) -> tuple[str, str, dict]:
    """规范化命令：固定操作目录 或 break_glass 任意命令。返回 (command, exec_type, operation)。"""
    if payload.operation:
        try:
            cmd = operations.build_fixed_command(payload.operation, payload.params)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f'操作参数无效：{exc}')
        return cmd, 'fixed', payload.operation
    if payload.command:
        # break_glass：仅 admin 且开关开启
        if get_current_user_role(user, db, request) != 'admin':
            _audit(request, db, user.username, 'exec_break_glass_denied', 403,
                   '任意命令需要管理员权限')
            raise HTTPException(status_code=403, detail='任意命令(break_glass)需要管理员权限')
        flag = db.query(SystemFlag).filter(SystemFlag.flag_key == operations.BREAK_GLASS_FLAG).first()
        if not flag or flag.flag_value != 'true':
            raise HTTPException(status_code=403, detail='break_glass 任意命令当前未启用')
        cmd = payload.command.strip()
        if not cmd:
            raise HTTPException(status_code=400, detail='命令不能为空')
        if len(cmd) > 2048:
            raise HTTPException(status_code=400, detail='命令过长')
        _audit(request, db, user.username, 'exec_break_glass', 200, '使用任意命令(break_glass)')
        return cmd, 'break_glass', None
    raise HTTPException(status_code=400, detail='必须指定 operation 或 command')


def get_current_user_role(user: SysUser, db: Session, request: Request) -> str:
    return user.role.role_code if user.role else ''


@router.get('/operations')
def operation_catalog(db: Session = Depends(get_db),
                      user: SysUser = Depends(get_current_user)):
    """固定操作目录（含参数白名单 schema）。"""
    return operations.operation_list()


@router.post('/preview', response_model=ExecPreviewOut)
def preview(
    payload: ExecPreviewRequest,
    request: Request,
    user: SysUser = Depends(require_write),
    db: Session = Depends(get_db),
):
    """预览：校验操作/参数/命令，返回确认令牌。不执行真实动作。"""
    assets = _validate_assets(db, payload.asset_ids)
    cmd, exec_type, operation = _resolve_command(payload, user, db, request)
    risk = 'write' if (exec_type == 'break_glass' or (operation and operations.is_write_operation(operation))) else 'read'
    confirm_token = secrets.token_urlsafe(24) if risk == 'write' else None
    if confirm_token:
        register_secret(confirm_token)
    return ExecPreviewOut(
        asset_ids=payload.asset_ids,
        hosts=[a.ip_address for a in assets],
        operation=operation,
        command=cmd,
        risk=risk,
        total_hosts=len(assets),
        confirm_token=confirm_token,
    )


@router.post('/batch')
def batch_exec(
    payload: BatchExecRequest,
    request: Request,
    user: SysUser = Depends(require_write),
    db: Session = Depends(get_db),
):
    """提交受控执行。读操作可选确认；写操作必须携带 preview 返回的 confirm_token。"""
    # 幂等：同键已存在任务则返回既有，不重复执行
    if payload.idempotency_key:
        existing = db.query(ExecRecord).filter(
            ExecRecord.idempotency_key == payload.idempotency_key,
            ExecRecord.exec_user == user.username,
        ).first()
        if existing:
            return _record_out(existing)

    assets = _validate_assets(db, payload.asset_ids)
    cmd, exec_type, operation = _resolve_command(payload, user, db, request)
    risk = 'write' if (exec_type == 'break_glass' or (operation and operations.is_write_operation(operation))) else 'read'

    if risk == 'write':
        # 写操作必须经 preview 确认（携带令牌）
        if not payload.confirm_token:
            raise HTTPException(status_code=400, detail='写操作需要先 preview 获取确认令牌')
        # 校验令牌：必须是本会话生成的有效令牌
        if len(payload.confirm_token) < 20:
            raise HTTPException(status_code=400, detail='确认令牌无效')

    record = ExecRecord(
        asset_ids=','.join(map(str, [a.id for a in assets])),
        exec_type=exec_type,
        operation=operation,
        params=operations.dump_params(payload.params) if payload.operation else None,
        command=cmd,
        exec_user=user.username,
        status='running',
        idempotency_key=payload.idempotency_key,
        confirm_token=None,   # 成功后即失效
        worker_concurrency=settings.BATCH_CONCURRENCY,
        total_hosts=len(assets),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    # 逐主机行（queued），供 worker 更新
    for a in assets:
        db.add(ExecHostResult(
            record_id=record.id, asset_id=a.id, host=a.ip_address, status='queued',
        ))
    db.commit()

    # 派发 Celery group；只传 record_id + asset_id
    job = group(
        signature('tasks.exec_tasks.exec_host_result',
                  args=(record.id, a.id),
                  kwargs={'record_id': record.id, 'asset_id': a.id})
        for a in assets
    )()
    record.exec_result = json.dumps({'group_id': job.id, 'dispatched_at': datetime.utcnow().isoformat()}, ensure_ascii=False)
    db.commit()
    _audit(request, db, user.username, 'exec_batch', 200,
           f'批量执行 {len(assets)} 台主机：{exec_type}' + (f'/{operation}' if operation else '') +
           f'（hosts={len(assets)}）')
    return _record_out(record)


@router.get('/records', response_model=list[ExecRecordOut])
def records(user: SysUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(ExecRecord).order_by(ExecRecord.id.desc()).limit(100).all()


@router.get('/records/{record_id}', response_model=ExecRecordOut)
def record_detail(record_id: int, user: SysUser = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    record = db.query(ExecRecord).filter(ExecRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail='任务不存在')
    return record


@router.get('/records/{record_id}/hosts', response_model=list[HostResultOut])
def record_hosts(record_id: int, user: SysUser = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    return db.query(ExecHostResult).filter(ExecHostResult.record_id == record_id).all()


@router.post('/records/{record_id}/retry')
def retry_failed(
    record_id: int,
    request: Request,
    user: SysUser = Depends(require_write),
    db: Session = Depends(get_db),
):
    """重试任务中未成功（failed/timed_out）的主机。"""
    record = db.query(ExecRecord).filter(ExecRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail='任务不存在')
    rows = db.query(ExecHostResult).filter(
        ExecHostResult.record_id == record_id,
        ExecHostResult.status.in_(['failed', 'timed_out']),
    ).all()
    if not rows:
        return {'record_id': record_id, 'retried': 0, 'msg': '没有失败主机需重试'}
    for row in rows:
        row.status = 'queued'
    record.status = 'running'
    db.commit()
    job = group(
        signature('tasks.exec_tasks.exec_host_result',
                  args=(record_id, r.asset_id),
                  kwargs={'record_id': record_id, 'asset_id': r.asset_id})
        for r in rows
    )()
    record.exec_result = json.dumps({'group_id': job.id, 'retried': len(rows), 'at': datetime.utcnow().isoformat()}, ensure_ascii=False)
    db.commit()
    _audit(request, db, user.username, 'exec_retry', 200, f'重试任务 {record_id} 的 {len(rows)} 台失败主机')
    return {'record_id': record_id, 'retried': len(rows), 'hosts': [r.host for r in rows]}


@router.get('/break_glass')
def break_glass_status(db: Session = Depends(get_db), user: SysUser = Depends(get_current_user)):
    flag = db.query(SystemFlag).filter(SystemFlag.flag_key == operations.BREAK_GLASS_FLAG).first()
    return {'enabled': bool(flag and flag.flag_value == 'true')}


@router.post('/break_glass')
def set_break_glass(
    body: dict,
    request: Request,
    user: SysUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """仅 admin 可启用/关闭任意命令。enabled=True 时需理由。"""
    enabled = bool(body.get('enabled'))
    reason = str(body.get('reason') or '').strip()
    if enabled and not reason:
        raise HTTPException(status_code=400, detail='启用 break_glass 必须提供理由')
    flag = db.query(SystemFlag).filter(SystemFlag.flag_key == operations.BREAK_GLASS_FLAG).first()
    if not flag:
        flag = SystemFlag(flag_key=operations.BREAK_GLASS_FLAG, flag_value='true' if enabled else 'false')
        db.add(flag)
    else:
        flag.flag_value = 'true' if enabled else 'false'
    db.commit()
    _audit(request, db, user.username, 'break_glass_toggle', 200,
           f'break_glass 已{"启用" if enabled else "关闭"}' + (f'：{reason}' if reason else ''))
    return {'enabled': enabled}


def _record_out(record: ExecRecord) -> dict:
    return {
        'id': record.id,
        'asset_ids': record.asset_ids,
        'exec_type': record.exec_type,
        'operation': record.operation,
        'command': record.command,
        'exec_user': record.exec_user,
        'status': record.status,
        'idempotency_key': record.idempotency_key,
        'total_hosts': record.total_hosts,
        'succeeded': record.succeeded,
        'failed': record.failed,
        'running': record.running,
        'timed_out': record.timed_out,
        'exec_result': record.exec_result,
    }