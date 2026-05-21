import paramiko
from tasks.celery_app import celery
@celery.task(bind=True)
def batch_exec_command(self, host: str, port: int, user: str, pwd: str, cmd: str):
    try:
        ssh = paramiko.SSHClient(); ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, port=port, username=user, password=pwd, timeout=10)
        _, stdout, stderr = ssh.exec_command(cmd)
        out = stdout.read().decode('utf-8', errors='ignore'); err = stderr.read().decode('utf-8', errors='ignore')
        ssh.close(); return {'host': host, 'stdout': out, 'stderr': err, 'status': 1 if not err else 2}
    except Exception as exc:
        return {'host': host, 'error': str(exc), 'status': 2}
