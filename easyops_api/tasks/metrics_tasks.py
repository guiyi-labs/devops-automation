"""E4 可观测辅助任务：采集 Celery 队列深度写入 Prometheus gauge。

queue_depth 任务由任何 worker 周期调用（当前无 beat；可在部署用
`celery worker -B` 或由 API/巡检触发）。手动触发示例：
    from tasks.metrics_tasks import queue_depth_metric
    queue_depth_metric.delay()
"""
from tasks.celery_app import celery


@celery.task(name='tasks.metrics_tasks.queue_depth_metric', max_retries=0)
def queue_depth_metric() -> dict:
    """读取 celery 默认队列长度并写入 easyops_queue_depth gauge。"""
    import redis as redis_lib

    from config import settings
    from services.metrics import observe_queue

    try:
        client = redis_lib.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=3)
        length = client.llen('celery')
        observe_queue(int(length or 0), queue='celery')
        return {'queue': 'celery', 'depth': int(length or 0)}
    except Exception as exc:  # noqa: BLE001
        observe_queue(-1, queue='celery')
        return {'queue': 'celery', 'depth': -1, 'error': str(exc)}