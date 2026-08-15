"""E4 主机巡检 Worker：逐主机采集事实 → 应用规则 → 落库并聚合记录。

只接收 record_id + asset_id，SSH 凭据由 Worker 从数据库读取并在内存中解密，
绝不进入 Celery 消息/Redis。
"""
import json
from datetime import datetime

from tasks.celery_app import celery
from services.host_inspection import HostFacts, COLLECT_HARD_TIMEOUT, COLLECT_SOFT_TIMEOUT, collect_host_facts
from services import inspection_rules


@celery.task(
    bind=True,
    max_retries=0,
    soft_time_limit=COLLECT_SOFT_TIMEOUT + 5,
    time_limit=COLLECT_HARD_TIMEOUT + 5,
)
def inspect_host(self, record_id: int, asset_id: int) -> dict:
    """采集一台主机的巡检事实，评估规则并写回 host_inspection，聚合 inspection_record。"""
    import time

    from common.crypto import decrypt_value
    from common.redact import redact
    from database.models import HostInspection, InspectionRecord, InspectionRule, ServerAsset
    from database.session import SessionLocal
    from services.metrics import record_inspection

    started = time.monotonic()
    db = SessionLocal()
    row = None
    try:
        record = db.query(InspectionRecord).filter(InspectionRecord.id == record_id).first()
        if not record:
            return {'host': 'unknown', 'error': f'巡检任务 {record_id} 不存在', 'status': 2}
        asset = db.query(ServerAsset).filter(ServerAsset.id == asset_id).first()
        if not asset:
            return {'host': 'unknown', 'error': f'资产 {asset_id} 不存在', 'status': 2}

        row = (
            db.query(HostInspection)
            .filter(HostInspection.record_id == record_id, HostInspection.asset_id == asset_id)
            .first()
        )
        if not row:
            row = HostInspection(record_id=record_id, asset_id=asset_id, host=asset.ip_address,
                                 overall_status='running')
            db.add(row)
        else:
            row.overall_status = 'running'
        db.commit()
        db.refresh(row)

        password = None
        private_key = None
        try:
            if asset.ssh_pwd:
                password = decrypt_value(asset.ssh_pwd)
            if asset.ssh_key:
                private_key = decrypt_value(asset.ssh_key)
        except Exception as exc:  # noqa: BLE001
            row.overall_status = 'unknown'
            row.unavailable_reason = f'凭据解密失败: {redact(str(exc))}'
            db.commit()
            return {'host': row.host, 'error': row.unavailable_reason, 'status': 2}

        facts: HostFacts = collect_host_facts(
            asset, password=password, private_key=private_key,
            host_key_fingerprint=asset.host_key_fingerprint,
        )
        rules = [
            {**{'id': r.id, 'name': r.name, 'metric': r.metric, 'operator': r.operator,
                'threshold': r.threshold, 'severity': r.severity, 'enabled': r.enabled == 1}}
            for r in db.query(InspectionRule).filter(InspectionRule.enabled == 1).all()
        ]
        assessment = inspection_rules.evaluate(facts.to_dict(), rules)

        row.facts = json.dumps(facts.to_dict(), ensure_ascii=False)
        row.overall_status = assessment.overall
        row.source = facts.source
        row.timeout_ms = facts.timeout_ms
        row.observed_at = datetime.fromisoformat(facts.observed_at) if facts.observed_at else None
        row.unavailable_reason = facts.unavailable_reason
        row.rule_results = inspection_rules.serialize_results(assessment)
        db.commit()
        return {'host': row.host, 'overall_status': assessment.overall,
                'unavailable': bool(facts.unavailable_reason), 'status': 1}
    finally:
        record_inspection(time.monotonic() - started, getattr(row, 'overall_status', 'unknown') if row else 'missing')
        _recompute_record(db, record_id)
        db.close()


def _recompute_record(db, record_id: int) -> None:
    """根据 host_inspection 聚合 inspection_record 状态与计数。"""
    from database.models import HostInspection, InspectionRecord

    record = db.query(InspectionRecord).filter(InspectionRecord.id == record_id).first()
    if not record:
        return
    rows = db.query(HostInspection).filter(HostInspection.record_id == record_id).all()
    record.total_hosts = len(rows)
    record.succeeded = sum(1 for r in rows if r.overall_status != 'unknown')
    record.failed = sum(1 for r in rows if r.overall_status == 'unknown')
    record.unknown = sum(1 for r in rows if r.overall_status == 'unknown')
    if all(r.overall_status != 'running' for r in rows) and rows:
        record.status = 'done'
    db.commit()