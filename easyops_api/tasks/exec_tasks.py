from tasks.celery_app import celery


@celery.task(bind=True, max_retries=0)
def batch_exec_command(self, asset_id: int, cmd: str):
    """按资产 ID 从数据库读取并解密凭据后执行命令。

    密码 / 私钥绝不作为 Celery 任务参数传递，避免明文进入 Redis 消息。
    """
    from common.crypto import decrypt_value
    from common.redact import redact
    from database.models import ServerAsset
    from database.session import SessionLocal
    from services.ssh_service import AuthError, ConnectionTimeoutError, HostKeyError, RemoteCommandError, UnknownHostKeyError, UnreachableError, connect_and_run

    db = SessionLocal()
    try:
        asset = db.query(ServerAsset).filter(ServerAsset.id == asset_id).first()
        if not asset:
            return {'host': 'unknown', 'error': f'资产 {asset_id} 不存在', 'status': 2}

        password = None
        private_key = None
        try:
            if asset.ssh_pwd:
                password = decrypt_value(asset.ssh_pwd)
            if asset.ssh_key:
                private_key = decrypt_value(asset.ssh_key)
        except Exception as exc:
            return {'host': asset.ip_address, 'error': f'凭据解密失败: {redact(str(exc))}', 'status': 2}

        try:
            return connect_and_run(
                host=asset.ip_address,
                port=asset.ssh_port,
                user=asset.ssh_user,
                password=password,
                private_key=private_key,
                cmd=cmd,
                host_key_fingerprint=asset.host_key_fingerprint,
            )
        except (UnknownHostKeyError, HostKeyError, AuthError, ConnectionTimeoutError,
                UnreachableError, RemoteCommandError) as exc:
            return {'host': asset.ip_address, 'error': redact(str(exc)), 'error_type': exc.error_type, 'status': 2}
        except Exception as exc:
            return {'host': asset.ip_address, 'error': redact(str(exc)), 'error_type': 'unknown', 'status': 2}
    finally:
        db.close()