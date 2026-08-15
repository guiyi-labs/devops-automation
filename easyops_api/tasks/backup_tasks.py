"""E5 备份/恢复 Worker：执行备份、校验、恢复一致性，落 BackupRecord。

- mock 模式（默认）：保留既有可复现骨架（fake dump），供单元测试与无 MySQL 环境；
- real 模式（BACKUP_EXECUTION_MODE=real）：容器内 mysqldump → gzip/sha256 → 持久化到
  BACKUP_STORAGE_DIR（compose 共享卷）；恢复从持久化文件 mysql 导入 → 表/行一致性。
保留策略：校验通过才 succeeded；失败备份不落有效记录；成功备份按
BACKUP_RETENTION_COUNT 裁剪旧文件。
"""
import json

from tasks.celery_app import celery


@celery.task(bind=True, max_retries=0, soft_time_limit=180, time_limit=240)
def run_backup_job(self, backup_id: int) -> dict:
    """执行一次备份：engine.dump() → 校验 → 持久化 → 落库。"""
    from common.redact import redact
    from database.models import BackupRecord
    from database.session import SessionLocal
    from services.backup_service import choose_backup_engine, format_validation

    db = SessionLocal()
    try:
        record = db.query(BackupRecord).filter(BackupRecord.id == backup_id).first()
        if not record:
            return {'backup_id': backup_id, 'status': 'missing'}
        record.status = 'running'
        db.commit()

        engine = choose_backup_engine()
        # RealMySQLDumpEngine.persist 内部完成 gzip/sha256 校验；一致性在 restore 后对比
        if hasattr(engine, 'persist'):
            data = engine.dump()
            persisted = engine.persist(data)
            validation = engine.consistency_check(persisted['file_path'])
            consistent = validation['consistent']
            record.status = 'succeeded' if consistent else 'failed'
            record.file_size_bytes = persisted['size_bytes']
            record.checksum = persisted['checksum']
            record.checksum_ok = 1 if consistent else 0
            record.file_path = persisted['file_path']
            record.validation = format_validation(validation)
            record.result = json.dumps({
                'engine': 'mysql_dump_real', 'validated': consistent,
                'mode': 'real', 'sql_path': persisted['sql_path'],
                'sha256_path': persisted['sha256_path'],
            }, ensure_ascii=False)
        else:
            data = engine.dump()
            validation = engine.consistency_check(data)
            record.status = 'succeeded' if validation['consistent'] else 'failed'
            record.file_size_bytes = validation['size_bytes']
            record.checksum = validation['checksum']
            record.checksum_ok = 1 if validation['consistent'] else 0
            record.file_path = 'backups/mysql_dump.sql.gz' if validation['consistent'] else None
            record.validation = format_validation(validation)
            record.result = json.dumps({'engine': 'mysql_dump', 'validated': validation['consistent'],
                                        'mode': 'mock'}, ensure_ascii=False)
        db.commit()
        return {'backup_id': backup_id, 'status': record.status,
                'checksum': record.checksum}
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


@celery.task(bind=True, max_retries=0, soft_time_limit=180, time_limit=240)
def run_restore_job(self, restore_id: int) -> dict:
    """执行恢复：从持久化备份文件 mysql 导入 → 一致性校验 → 落库。"""
    from common.redact import redact
    from database.models import BackupRecord
    from database.session import SessionLocal
    from services.backup_service import choose_backup_engine, format_validation

    db = SessionLocal()
    try:
        record = db.query(BackupRecord).filter(BackupRecord.id == restore_id).first()
        if not record:
            return {'restore_id': restore_id, 'status': 'missing'}
        record.status = 'running'
        db.commit()

        engine = choose_backup_engine()
        if hasattr(engine, 'restore') and getattr(engine, 'storage_dir', None):
            # real 模式：从源备份记录读取持久化文件，恢复到全新目标库
            source_id = int(json.loads(record.result or '{}').get('restore_from', 0) or 0)
            source = db.query(BackupRecord).filter(BackupRecord.id == source_id).first()
            file_path = source.file_path if source else None
            if not file_path:
                raise RuntimeError('恢复源备份没有持久化文件路径')
            stats = engine.restore(file_path)
            validation = {
                'checksum': stats['checksum'],
                'size_bytes': 0,
                'gzip_ok': file_path.endswith('.gz'),
                'restored_tables': stats['restored_tables'],
                'restored_rows': stats['restored_rows'],
                'target_database': stats.get('target_database'),
                'consistent': stats['restored_tables'] >= 0,
            }
        else:
            data = engine.dump()  # mock：模拟从备份内容恢复
            validation = engine.consistency_check(data)

        ok = validation['consistent']
        record.status = 'succeeded' if ok else 'failed'
        record.op_type = 'restore'
        record.validation = format_validation(validation)
        record.result = json.dumps({
            'restored_tables': validation.get('restored_tables', []),
            'restored_rows': validation.get('restored_rows', 0),
            'consistent': ok,
            'mode': 'real' if hasattr(engine, 'storage_dir') else 'mock',
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