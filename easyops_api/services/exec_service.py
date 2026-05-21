from celery import group
from database.models import ServerAsset
from tasks.exec_tasks import batch_exec_command

def submit_batch_command(assets: list[ServerAsset], command: str):
    return group(
        batch_exec_command.s(a.ip_address, a.ssh_port, a.ssh_user, a.ssh_pwd or '', command)
        for a in assets
    )()
