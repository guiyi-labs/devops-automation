from celery import group

from tasks.exec_tasks import batch_exec_command


def submit_batch_command(asset_ids: list[int], command: str):
    """提交批量命令：只传资产 ID，凭据由 Worker 从数据库读取。"""
    return group(batch_exec_command.s(asset_id, command) for asset_id in asset_ids)()