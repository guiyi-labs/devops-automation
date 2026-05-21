from tasks.celery_app import celery
@celery.task
def run_backup_job(target: str): return {'target': target, 'status':'success'}
