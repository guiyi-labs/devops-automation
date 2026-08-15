"""E3 受控批量执行 Worker：逐主机执行并落库状态/输出。

只接收 record_id + asset_id，SSH 凭据由 Worker 从数据库读取并在内存中解密，
绝不进入 Celery 消息/Redis。
"""
from tasks.celery_app import celery


@celery.task(
    bind=True,
    max_retries=0,
    soft_time_limit=75,   # 单主机软超时（秒）
    time_limit=90,        # 单主机硬超时（秒），超时任务被终止并记为 timed_out
)
def exec_host_result(self, record_id: int, asset_id: int) -> dict:
    """执行一台主机的受控任务，结果写回 exec_host_result 并聚合到 exec_record。"""
    import time

    from common.crypto import decrypt_value
    from common.redact import redact
    from database.models import ExecHostResult, ExecRecord, ServerAsset
    from database.session import SessionLocal
    from services.metrics import record_exec
    from services.ssh_service import (
        AuthError, ConnectionTimeoutError, HostKeyError, RemoteCommandError,
        UnknownHostKeyError, UnreachableError, connect_and_run,
    )

    started = time.monotonic()
    db = SessionLocal()
    host_row = None
    try:
        record = db.query(ExecRecord).filter(ExecRecord.id == record_id).first()
        if not record:
            return {'host': 'unknown', 'error': f'任务 {record_id} 不存在', 'status': 2}
        asset = db.query(ServerAsset).filter(ServerAsset.id == asset_id).first()
        if not asset:
            return {'host': 'unknown', 'error': f'资产 {asset_id} 不存在', 'status': 2}

        host_row = (
            db.query(ExecHostResult)
            .filter(ExecHostResult.record_id == record_id, ExecHostResult.asset_id == asset_id)
            .first()
        )
        if not host_row:
            host_row = ExecHostResult(
                record_id=record_id, asset_id=asset_id, host=asset.ip_address,
                status='running',
            )
            db.add(host_row)
        else:
            host_row.status = 'running'
        db.commit()
        db.refresh(host_row)

        password = None
        private_key = None
        try:
            if asset.ssh_pwd:
                password = decrypt_value(asset.ssh_pwd)
            if asset.ssh_key:
                private_key = decrypt_value(asset.ssh_key)
        except Exception as exc:
            host_row.status = 'failed'
            host_row.error_type = 'decrypt_error'
            host_row.error = f'凭据解密失败: {redact(str(exc))}'
            db.commit()
            return {'host': host_row.host, 'error': host_row.error, 'status': 2}

        try:
            result = connect_and_run(
                host=asset.ip_address,
                port=asset.ssh_port,
                user=asset.ssh_user,
                password=password,
                private_key=private_key,
                cmd=record.command,
                host_key_fingerprint=asset.host_key_fingerprint,
            )
            host_row.status = 'succeeded'
            host_row.exit_code = result.get('exit_code')
            host_row.stdout = result.get('stdout') or ''
            host_row.stderr = result.get('stderr') or ''
            db.commit()
            return {'host': host_row.host, 'status': 1, 'stdout': host_row.stdout}
        except (UnknownHostKeyError, HostKeyError, AuthError, ConnectionTimeoutError,
                UnreachableError, RemoteCommandError) as exc:
            host_row.status = 'failed'
            host_row.error_type = exc.error_type
            host_row.error = redact(str(exc))
            db.commit()
            return {'host': host_row.host, 'error': host_row.error,
                    'error_type': exc.error_type, 'status': 2}
        except Exception as exc:
            host_row.status = 'failed'
            host_row.error_type = 'unknown'
            host_row.error = redact(str(exc))
            db.commit()
            return {'host': host_row.host, 'error': host_row.error, 'status': 2}
    finally:
        # 指标：无论成败都记录耗时与状态
        record_exec(time.monotonic() - started, getattr(host_row, 'status', 'queued') if host_row else 'missing')
        _recompute_record(db, record_id)
        db.close()


def _recompute_record(db, record_id: int) -> None:
    """根据 exec_host_result 聚合 exec_record 状态与计数。"""
    from database.models import ExecHostResult, ExecRecord

    record = db.query(ExecRecord).filter(ExecRecord.id == record_id).first()
    if not record:
        return
    rows = db.query(ExecHostResult).filter(ExecHostResult.record_id == record_id).all()
    record.total_hosts = len(rows)
    record.succeeded = sum(1 for r in rows if r.status == 'succeeded')
    record.failed = sum(1 for r in rows if r.status == 'failed')
    record.timed_out = sum(1 for r in rows if r.status == 'timed_out')
    record.running = sum(1 for r in rows if r.status in ('queued', 'running'))
    if record.running == 0 and record.total_hosts > 0:
        if record.failed == 0 and record.timed_out == 0:
            record.status = 'done'
        elif record.succeeded > 0:
            record.status = 'partial'
        else:
            record.status = 'done'
    db.commit()


# 兼容别名：旧版直接任务名 batch_exec_command 已废弃，E3 改用 exec_host_result
batch_exec_command = exec_host_result