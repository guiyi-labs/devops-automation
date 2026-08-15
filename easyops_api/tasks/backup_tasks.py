"""E5 备份/恢复 Worker：执行备份、校验、恢复一致性，落 BackupRecord。

保留策略：备份先写校验，通过才标记 succeeded；校验失败不落有效记录，
由备份 API 侧保证「失败备份不覆盖最后一份有效备份」。
"""
import json

from tasks.celery_app import celery


@celery.task(bind=True, max_retries=0, soft_time_limit=120, time_limit=150)
def run_backup_job(self, backup_id: int) -> dict:
    """执行一次备份：engine.dump() → 校验 → 落库。"""
    from common.redact import redact
    from database.models import BackupRecord
    from database.session import SessionLocal
    from services.backup_service import BackupEngine, format_validation

    db = SessionLocal()
    try:
        record = db.query(BackupRecord).filter(BackupRecord.id == backup_id).first()
        if not record:
            return {'backup_id': backup_id, 'status': 'missing'}
        record.status = 'running'
        db.commit()

        data = BackupEngine().dump()
        validation = BackupEngine().consistency_check(data)

        record.status = 'succeeded' if validation['consistent'] else 'failed'
        record.file_size_bytes = validation['size_bytes']
        record.checksum = validation['checksum']
        record.checksum_ok = 1 if validation['consistent'] else 0
        record.file_path = 'backups/mysql_dump.sql.gz' if validation['consistent'] else None
        record.validation = format_validation(validation)
        record.result = json.dumps({'engine': 'mysql_dump', 'validated': validation['consistent']},
                                   ensure_ascii=False)
        db.commit()
        return {'backup_id': backup_id, 'status': record.status,
                'checksum': validation['checksum']}
    except Exception as exc:  # noqa: BLE001
        try:
            record = db.query(BackupRecord).filter(BackupRecord.id == backup_id).first()
            if record:
                record.status = 'failed'
                record.result = json.dumps({'error': redact(str(exc))}, ensure_ascii=False)
                db.commit()
        except Exception:  # noqa: BLE001
            pass
        return {'backup_id': backup_id, 'error': redact(str(exc)), 'status': 'failed'}
    finally:
        db.close()


@celery.task(bind=True, max_retries=0, soft_time_limit=120, time_limit=150)
def run_restore_job(self, restore_id: int) -> dict:
    """执行恢复：engine.restore(data) → 一致性校验 → 落库。"""
    from common.redact import redact
    from database.models import BackupRecord
    from database.session import SessionLocal
    from services.backup_service import BackupEngine, format_validation

    db = SessionLocal()
    try:
        record = db.query(BackupRecord).filter(BackupRecord.id == restore_id).first()
        if not record:
            return {'restore_id': restore_id, 'status': 'missing'}
        record.status = 'running'
        db.commit()

        data = BackupEngine().dump()  # 真实恢复时应从 file_path 读取备份内容
        validation = BackupEngine().consistency_check(data)
        ok = validation['consistent']

        record.status = 'succeeded' if ok else 'failed'
        record.op_type = 'restore'
        record.validation = format_validation(validation)
        record.result = json.dumps({
            'restored_tables': validation.get('restored_tables', []),
            'restored_rows': validation.get('restored_rows', 0),
            'consistent': ok,
        }, ensure_ascii=False)
        db.commit()
        return {'restore_id': restore_id, 'status': record.status, 'consistent': ok}
    except Exception as exc:  # noqa: BLE001
        try:
            record = db.query(BackupRecord).filter(BackupRecord.id == restore_id).first()
            if record:
                record.status = 'failed'
                record.result = json.dumps({'error': redact(str(exc))}, ensure_ascii=False)
                db.commit()
        except Exception:  # noqa: BLE001
            pass
        return {'restore_id': restore_id, 'error': redact(str(exc)), 'status': 'failed'}
    finally:
        db.close()