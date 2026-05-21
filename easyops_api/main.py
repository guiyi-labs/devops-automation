from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from api.v1 import user, asset, exec_task, docker_k8s, deploy, alert, cron_task
from database.session import engine, Base
from database import models  # noqa
Base.metadata.create_all(bind=engine)
app = FastAPI(title='EasyOps DevOps API', version='1.0.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
app.include_router(user.router, prefix='/api/v1/user', tags=['用户管理'])
app.include_router(asset.router, prefix='/api/v1/asset', tags=['资产管理'])
app.include_router(exec_task.router, prefix='/api/v1/exec', tags=['批量执行'])
app.include_router(docker_k8s.router, prefix='/api/v1/container', tags=['容器管理'])
app.include_router(deploy.router, prefix='/api/v1/deploy', tags=['CI/CD部署'])
app.include_router(alert.router, prefix='/api/v1/alert', tags=['监控告警'])
app.include_router(cron_task.router, prefix='/api/v1/cron', tags=['定时任务'])
Instrumentator().instrument(app).expose(app)
@app.get('/')
def root(): return {'msg': 'EasyOps DevOps API Running'}
