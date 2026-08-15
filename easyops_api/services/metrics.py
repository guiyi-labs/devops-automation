"""E4 自定义 Prometheus 指标：请求、队列、任务、巡检与主机健康。

依赖 prometheus-client（由 prometheus-fastapi-instrumentator 传递安装）。
指标注册为模块级单例，避免重复注册；Worker 与 API 各自导入即可使用。
"""
import logging

from prometheus_client import Counter, Gauge, Histogram

logger = logging.getLogger(__name__)

# 批量执行任务（E3 已接入；此处统一注册，由 worker 更新）
exec_tasks_total = Counter(
    'easyops_exec_tasks_total', '批量执行主机任务总数', ['status'],
)
exec_task_duration = Histogram(
    'easyops_exec_task_duration_seconds', '批量执行单主机耗时（秒）',
    buckets=(1, 2, 5, 10, 30, 60, 90),
)

# 巡检（E4）
inspection_hosts_total = Counter(
    'easyops_inspection_hosts_total', '巡检主机总数', ['status'],
)
inspection_duration = Histogram(
    'easyops_inspection_duration_seconds', '单主机巡检耗时（秒）',
    buckets=(1, 2, 5, 10, 30, 60),
)

# Celery 队列积压（gauge，由 worker 周期任务采集）
queue_depth = Gauge(
    'easyops_queue_depth', 'Celery 队列待处理任务数', ['queue'],
)

# 最近一次巡检的主机健康分布
host_health = Gauge(
    'easyops_host_health', '最近一次巡检各状态主机数', ['status'],
)


def record_exec(duration_seconds: float, status: str) -> None:
    exec_tasks_total.labels(status=status).inc()
    exec_task_duration.observe(duration_seconds)


def record_inspection(duration_seconds: float, overall_status: str) -> None:
    inspection_hosts_total.labels(status=overall_status).inc()
    inspection_duration.observe(duration_seconds)


def observe_queue(queue_count: int, queue: str = 'celery') -> None:
    queue_depth.labels(queue=queue).set(queue_count)


def observe_health(healthy: int, warning: int, critical: int, unknown: int) -> None:
    host_health.labels(status='healthy').set(healthy)
    host_health.labels(status='warning').set(warning)
    host_health.labels(status='critical').set(critical)
    host_health.labels(status='unknown').set(unknown)