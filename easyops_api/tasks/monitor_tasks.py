from tasks.celery_app import celery
@celery.task
def collect_metric_snapshot(): return {'status':'ok'}
