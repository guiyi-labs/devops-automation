import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text

from api.v1 import alert, asset, cron_task, deploy, docker_k8s, exec_task, inspection, user
from common.redact import LogRedactFilter, redact
from config import settings
from database import models  # noqa
from database.session import SessionLocal

# 应用日志统一脱敏：密码/私钥/Token/连接串不进入日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
)
for handler in logging.getLogger().handlers:
    handler.addFilter(LogRedactFilter())


app = FastAPI(title='EasyOps DevOps API', version='1.1.0')

# CORS：显式 allowlist，禁止 allow_origins=['*'] 与 allow_credentials=True 组合
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=['GET', 'POST', 'PUT', 'DELETE'],
    allow_headers=['Authorization', 'Content-Type'],
)

app.include_router(user.router, prefix='/api/v1/user', tags=['用户管理'])
app.include_router(asset.router, prefix='/api/v1/asset', tags=['资产管理'])
app.include_router(exec_task.router, prefix='/api/v1/exec', tags=['批量执行'])
app.include_router(docker_k8s.router, prefix='/api/v1/container', tags=['容器管理'])
app.include_router(deploy.router, prefix='/api/v1/deploy', tags=['CI/CD部署'])
app.include_router(alert.router, prefix='/api/v1/alert', tags=['监控告警'])
app.include_router(cron_task.router, prefix='/api/v1/cron', tags=['定时任务'])
app.include_router(inspection.router, prefix='/api/v1/inspection', tags=['主机巡检'])

Instrumentator().instrument(app).expose(app)


@app.get('/')
def root():
    return {'msg': 'EasyOps DevOps API Running'}


@app.get('/health/live')
def health_live():
    return {'status': 'alive'}


@app.get('/health/ready')
def health_ready():
    """Readiness：检查 MySQL 与 Redis；被管主机的故障不影响平台自身就绪状态。"""
    db = SessionLocal()
    try:
        db.execute(text('SELECT 1'))
    except Exception as exc:
        return JSONResponse(status_code=503, content={'status': 'not_ready', 'component': 'mysql', 'error': redact(str(exc))})
    finally:
        db.close()
    try:
        import redis
        client = redis.from_url(settings.CELERY_BROKER_URL, socket_connect_timeout=3)
        client.ping()
    except Exception as exc:
        return JSONResponse(status_code=503, content={'status': 'not_ready', 'component': 'redis', 'error': redact(str(exc))})
    return {'status': 'ready'}