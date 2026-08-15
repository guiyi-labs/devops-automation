from celery import Celery
from config import settings
celery = Celery('easyops', broker=settings.CELERY_BROKER_URL, backend=settings.CELERY_RESULT_BACKEND)
celery.conf.update(task_serializer='json', accept_content=['json'], result_serializer='json', timezone='Asia/Shanghai', enable_utc=False)
celery.autodiscover_tasks(['tasks.exec_tasks', 'tasks.inspection_tasks', 'tasks.metrics_tasks', 'tasks.deploy_tasks', 'tasks.backup_tasks', 'tasks.monitor_tasks'])
