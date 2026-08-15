"""E4 主机巡检 API：触发巡检、查询记录/逐主机结果、管理规则。"""

from celery import group, signature
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from config import settings
from database.models import HostInspection, InspectionRecord, InspectionRule, ServerAsset
from database.session import get_db
from dependencies import get_current_user, require_write
from schemas.all import (
    HostInspectionOut, InspectionRecordOut, InspectionRuleIn, InspectionRuleOut,
)
from services import inspection_rules

router = APIRouter()


def _ensure_default_rules(db: Session) -> None:
    """若 inspection_rule 表为空，写入内置默认规则。"""
    if db.query(InspectionRule).count() > 0:
        return
    for seed in inspection_rules.default_rules():
        db.add(InspectionRule(**seed))
    db.commit()


def _audit(request: Request, db: Session, username: str, action: str, status_code: int, detail: str) -> None:
    from database.models import AuditLog
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


def _validate_asset_ids(db: Session, asset_ids: list[int]) -> list[ServerAsset]:
    if not asset_ids:
        raise HTTPException(status_code=400, detail='至少选择一个资产')
    if len(asset_ids) > settings.BATCH_MAX_ASSETS:
        raise HTTPException(status_code=400, detail=f'单次巡检资产数不能超过 {settings.BATCH_MAX_ASSETS}')
    assets = db.query(ServerAsset).filter(ServerAsset.id.in_(asset_ids)).all()
    found = {a.id: a for a in assets}
    missing = [i for i in asset_ids if i not in found]
    if missing:
        raise HTTPException(status_code=400, detail=f'资产不存在: {missing}')
    return [found[i] for i in asset_ids]


@router.post('/collect')
def collect(
    body: dict,
    request: Request,
    user=Depends(require_write),
    db: Session = Depends(get_db),
):
    """触发一次主机巡检（逐主机 SSH 采集 + 规则判定）。"""
    asset_ids = body.get('asset_ids') or []
    assets = _validate_asset_ids(db, asset_ids)

    # 规则为空时写入内置默认规则，保证巡检有判定依据（幂等）
    _ensure_default_rules(db)

    record = InspectionRecord(
        asset_ids=','.join(map(str, [a.id for a in assets])),
        status='running',
        total_hosts=len(assets),
        exec_user=user.username,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    for a in assets:
        db.add(HostInspection(
            record_id=record.id, asset_id=a.id, host=a.ip_address, overall_status='running',
        ))
    db.commit()

    job = group(
        signature('tasks.inspection_tasks.inspect_host',
                  args=(record.id, a.id),
                  kwargs={'record_id': record.id, 'asset_id': a.id})
        for a in assets
    )()
    _audit(request, db, user.username, 'inspection_collect', 200,
           f'触发巡检 {len(assets)} 台主机（record_id={record.id}）')
    return {'record_id': record.id, 'total_hosts': len(assets), 'group_id': job.id}


@router.post('/collect/sync')
def collect_sync(
    body: dict,
    request: Request,
    user=Depends(require_write),
    db: Session = Depends(get_db),
):
    """同步巡检（uvicorn 进程内执行）：逐主机 SSH 采集 + 规则判定 + 指标记录。

    与 /collect 的区别：不经过 Celery worker，任务与 Prometheus 指标在 API
    进程内完成，保证 /metrics 上 easyops_inspection_* 有真实观测值。
    """
    import json as _json
    import time

    from common.crypto import decrypt_value
    from common.redact import redact
    from services.host_inspection import collect_host_facts
    from services.metrics import record_inspection

    asset_ids = body.get('asset_ids') or []
    assets = _validate_asset_ids(db, asset_ids)
    _ensure_default_rules(db)

    record = InspectionRecord(
        asset_ids=','.join(map(str, [a.id for a in assets])),
        status='running',
        total_hosts=len(assets),
        exec_user=user.username,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    for a in assets:
        db.add(HostInspection(
            record_id=record.id, asset_id=a.id, host=a.ip_address, overall_status='running',
        ))
    db.commit()

    rules = [
        {**{'id': r.id, 'name': r.name, 'metric': r.metric, 'operator': r.operator,
            'threshold': r.threshold, 'severity': r.severity, 'enabled': r.enabled == 1}}
        for r in db.query(InspectionRule).filter(InspectionRule.enabled == 1).all()
    ]

    results = []
    for a in assets:
        started = time.monotonic()
        row = (
            db.query(HostInspection)
            .filter(HostInspection.record_id == record.id, HostInspection.asset_id == a.id)
            .first()
        )
        try:
            password = None
            private_key = None
            try:
                if a.ssh_pwd:
                    password = decrypt_value(a.ssh_pwd)
                if a.ssh_key:
                    private_key = decrypt_value(a.ssh_key)
            except Exception as exc:  # noqa: BLE001
                row.overall_status = 'unknown'
                row.unavailable_reason = f'凭据解密失败: {redact(str(exc))}'
                results.append({'asset_id': a.id, 'overall_status': 'unknown',
                                'error': row.unavailable_reason})
                record_inspection(time.monotonic() - started, 'unknown')
                db.commit()
                continue

            facts = collect_host_facts(
                a, password=password, private_key=private_key,
                host_key_fingerprint=a.host_key_fingerprint,
            )
            assessment = inspection_rules.evaluate(facts.to_dict(), rules)
            row.facts = _json.dumps(facts.to_dict(), ensure_ascii=False)
            row.overall_status = assessment.overall
            row.source = facts.source
            row.timeout_ms = facts.timeout_ms
            row.observed_at = datetime.fromisoformat(facts.observed_at) if facts.observed_at else None
            row.unavailable_reason = facts.unavailable_reason
            row.rule_results = inspection_rules.serialize_results(assessment)
            record_inspection(time.monotonic() - started, row.overall_status)
            results.append({'asset_id': a.id, 'overall_status': row.overall_status})
            db.commit()
        except Exception as exc:  # noqa: BLE001
            row.overall_status = 'unknown'
            row.unavailable_reason = f'采集失败: {redact(str(exc))}'
            record_inspection(time.monotonic() - started, 'unknown')
            results.append({'asset_id': a.id, 'overall_status': 'unknown',
                            'error': row.unavailable_reason})
            db.commit()

    # 聚合记录状态（复用 inspection_tasks._recompute_record）
    from tasks.inspection_tasks import _recompute_record
    _recompute_record(db, record.id)

    # 填充主机健康分布 gauge（Grafana「巡检健康分布」面板的指标来源）
    from collections import Counter as _Counter
    from services.metrics import observe_health
    _dist = _Counter(r['overall_status'] for r in results)
    observe_health(
        healthy=_dist.get('healthy', 0),
        warning=_dist.get('warning', 0),
        critical=_dist.get('critical', 0),
        unknown=_dist.get('unknown', 0),
    )

    _audit(request, db, user.username, 'inspection_collect_sync', 200,
           f'同步巡检 {len(assets)} 台主机（record_id={record.id}）')
    return {'record_id': record.id, 'total_hosts': len(assets), 'results': results}


@router.get('/records', response_model=list[InspectionRecordOut])
def records(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(InspectionRecord).order_by(InspectionRecord.id.desc()).limit(100).all()


@router.get('/records/{record_id}', response_model=InspectionRecordOut)
def record_detail(record_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    record = db.query(InspectionRecord).filter(InspectionRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail='巡检记录不存在')
    return record


@router.get('/records/{record_id}/hosts', response_model=list[HostInspectionOut])
def record_hosts(record_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(HostInspection).filter(HostInspection.record_id == record_id).all()


@router.get('/assets/{asset_id}/latest', response_model=HostInspectionOut | None)
def asset_latest(asset_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    """某资产最近一次巡检结果。"""
    return (
        db.query(HostInspection)
        .filter(HostInspection.asset_id == asset_id)
        .order_by(HostInspection.id.desc())
        .first()
    )


@router.get('/rules', response_model=list[InspectionRuleOut])
def list_rules(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(InspectionRule).order_by(InspectionRule.id.asc()).all()


@router.post('/rules', response_model=InspectionRuleOut)
def create_rule(
    payload: InspectionRuleIn,
    request: Request,
    user=Depends(require_write),
    db: Session = Depends(get_db),
):
    if payload.metric not in {'disk_used_pct', 'inode_used_pct', 'memory_used_pct',
                              'swap_used_pct', 'load_5', 'service_stopped', 'port_not_listening'}:
        raise HTTPException(status_code=400, detail=f'未知指标: {payload.metric}')
    if payload.operator not in {'gt', 'lt', 'eq', 'ne', 'contains', 'not_contains'}:
        raise HTTPException(status_code=400, detail=f'未知操作符: {payload.operator}')
    if payload.severity not in {'warning', 'critical'}:
        raise HTTPException(status_code=400, detail='severity 只能为 warning 或 critical')
    existing = db.query(InspectionRule).filter(InspectionRule.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=409, detail='规则名已存在')
    rule = InspectionRule(**payload.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    _audit(request, db, user.username, 'inspection_rule_create', 200, f'创建巡检规则 {rule.name}')
    return rule


@router.put('/rules/{rule_id}', response_model=InspectionRuleOut)
def update_rule(
    rule_id: int,
    payload: InspectionRuleIn,
    request: Request,
    user=Depends(require_write),
    db: Session = Depends(get_db),
):
    rule = db.query(InspectionRule).filter(InspectionRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail='规则不存在')
    for k, v in payload.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    db.refresh(rule)
    _audit(request, db, user.username, 'inspection_rule_update', 200, f'更新巡检规则 {rule.name}')
    return rule


@router.delete('/rules/{rule_id}')
def delete_rule(rule_id: int, request: Request, user=Depends(require_write), db: Session = Depends(get_db)):
    rule = db.query(InspectionRule).filter(InspectionRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail='规则不存在')
    name = rule.name
    db.delete(rule)
    db.commit()
    _audit(request, db, user.username, 'inspection_rule_delete', 200, f'删除巡检规则 {name}')
    return {'deleted': rule_id, 'name': name}