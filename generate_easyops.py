from pathlib import Path

root = Path('.')

def w(path: str, content: str):
    p = root / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content.strip() + "\n", encoding='utf-8')

w('README.md', r'''
# EasyOps 轻量企业级 DevOps 自动化运维平台

EasyOps 是一个面向中小企业运维团队的私有化 DevOps 自动化运维平台，覆盖服务器资产管理、批量命令执行、容器管理、CI/CD 发布、监控告警、定时任务与数据备份。

## 技术栈
- 后端：Python 3.10+、FastAPI、SQLAlchemy、MySQL、Redis、Celery
- 前端：Vue3、Vite、Element Plus、Axios
- 运维：Paramiko、Docker SDK、Kubernetes Python Client
- 监控：Prometheus、Grafana、Alertmanager（规划/可扩展）

## 快速启动
```bash
docker compose up -d --build
```

访问：
- Web：http://localhost:8080
- API Swagger：http://localhost:8000/docs
- Prometheus：http://localhost:9090
- Grafana：http://localhost:3000

默认管理员初始化：登录页点击“初始化管理员”，账号 `admin/admin123`。
''')

w('docker-compose.yml', r'''
version: '3.8'
services:
  mysql:
    image: docker.m.daocloud.io/library/mysql:5.7
    environment:
      MYSQL_ROOT_PASSWORD: root123456
      MYSQL_DATABASE: easyops
    command: --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
    ports: ["3306:3306"]
    volumes: [mysql_data:/var/lib/mysql]
    restart: always
  redis:
    image: docker.m.daocloud.io/library/redis:6
    ports: ["6379:6379"]
    volumes: [redis_data:/data]
    restart: always
  api:
    build: ./easyops_api
    environment:
      MYSQL_HOST: mysql
      REDIS_HOST: redis
    ports: ["8000:8000"]
    depends_on: [mysql, redis]
    restart: always
  celery:
    build: ./easyops_api
    command: celery -A tasks.celery_app.celery worker -l INFO
    environment:
      MYSQL_HOST: mysql
      REDIS_HOST: redis
    depends_on: [mysql, redis]
    restart: always
  web:
    build: ./easyops_web
    ports: ["8080:80"]
    depends_on: [api]
    restart: always
  prometheus:
    image: docker.m.daocloud.io/prom/prometheus:latest
    volumes: [./prometheus.yml:/etc/prometheus/prometheus.yml]
    ports: ["9090:9090"]
  grafana:
    image: docker.m.daocloud.io/grafana/grafana:latest
    ports: ["3000:3000"]
    volumes: [grafana_data:/var/lib/grafana]
volumes:
  mysql_data:
  redis_data:
  grafana_data:
''')

w('prometheus.yml', r'''
global:
  scrape_interval: 15s
scrape_configs:
  - job_name: easyops-api
    metrics_path: /metrics
    static_configs:
      - targets: ['api:8000']
''')

w('.gitlab-ci.yml', r'''
stages: [build, deploy]
build-api:
  stage: build
  image: docker:latest
  services: [docker:dind]
  script:
    - docker build -t registry.example.com/easyops-api:${CI_COMMIT_SHA} ./easyops_api
deploy-k8s:
  stage: deploy
  image: alpine:latest
  script:
    - apk add --no-cache openssh-client
    - ssh root@deploy-server "kubectl apply -f /opt/easyops/k8s/"
  only: [main]
''')

for d in ['easyops_api/api/v1','easyops_api/common','easyops_api/database','easyops_api/schemas','easyops_api/services','easyops_api/tasks']:
    w(f'{d}/__init__.py', '')

w('easyops_api/requirements.txt', r'''
fastapi==0.111.0
uvicorn[standard]==0.30.1
SQLAlchemy==2.0.30
PyMySQL==1.1.1
pydantic-settings==2.3.4
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
bcrypt==4.0.1
python-multipart==0.0.9
celery==5.4.0
redis==5.0.4
paramiko==3.4.0
docker==7.1.0
kubernetes==29.0.0
prometheus-fastapi-instrumentator==7.0.0
requests==2.32.3
email-validator==2.1.1
''')

w('easyops_api/Dockerfile', r'''
FROM docker.m.daocloud.io/library/python:3.10-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
''')

w('easyops_api/config.py', r'''
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    MYSQL_HOST: str = os.getenv('MYSQL_HOST', 'localhost')
    MYSQL_PORT: int = int(os.getenv('MYSQL_PORT', '3306'))
    MYSQL_USER: str = os.getenv('MYSQL_USER', 'root')
    MYSQL_PASSWORD: str = os.getenv('MYSQL_PASSWORD', 'root123456')
    MYSQL_DB: str = os.getenv('MYSQL_DB', 'easyops')
    REDIS_HOST: str = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT: int = int(os.getenv('REDIS_PORT', '6379'))
    SECRET_KEY: str = os.getenv('SECRET_KEY', 'easyops-secret-key-2026-devops-project')
    ALGORITHM: str = 'HS256'
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120
    CELERY_BROKER_URL: str = os.getenv('CELERY_BROKER_URL', f'redis://{REDIS_HOST}:{REDIS_PORT}/0')
    CELERY_RESULT_BACKEND: str = os.getenv('CELERY_RESULT_BACKEND', f'redis://{REDIS_HOST}:{REDIS_PORT}/0')

settings = Settings()
''')

w('easyops_api/database/session.py', r'''
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from config import settings

SQLALCHEMY_DATABASE_URL = f"mysql+pymysql://{settings.MYSQL_USER}:{settings.MYSQL_PASSWORD}@{settings.MYSQL_HOST}:{settings.MYSQL_PORT}/{settings.MYSQL_DB}?charset=utf8mb4"
engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
''')

w('easyops_api/database/models.py', r'''
from sqlalchemy import Column, DateTime, Integer, String, Text, SmallInteger, func
from database.session import Base

class TimestampMixin:
    create_time = Column(DateTime, nullable=False, server_default=func.now())
    update_time = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

class SysRole(Base):
    __tablename__ = 'sys_role'
    id = Column(Integer, primary_key=True, index=True)
    role_name = Column(String(50), nullable=False)
    role_code = Column(String(50), nullable=False, unique=True)
    description = Column(String(255))
    create_time = Column(DateTime, nullable=False, server_default=func.now())

class SysUser(Base, TimestampMixin):
    __tablename__ = 'sys_user'
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), nullable=False, unique=True, index=True)
    password = Column(String(128), nullable=False)
    nickname = Column(String(50), nullable=False)
    email = Column(String(100))
    phone = Column(String(20))
    role_id = Column(Integer, nullable=False, default=1)
    status = Column(SmallInteger, nullable=False, default=1)

class ServerAsset(Base, TimestampMixin):
    __tablename__ = 'server_asset'
    id = Column(Integer, primary_key=True, index=True)
    asset_name = Column(String(100), nullable=False)
    ip_address = Column(String(50), nullable=False, index=True)
    ssh_port = Column(Integer, nullable=False, default=22)
    ssh_user = Column(String(50), nullable=False)
    ssh_pwd = Column(String(255))
    ssh_key = Column(Text)
    os_type = Column(String(50))
    env_type = Column(String(20), nullable=False, default='dev')
    business_group = Column(String(100))
    online_status = Column(SmallInteger, nullable=False, default=0)
    cpu = Column(String(50)); mem = Column(String(50)); disk = Column(String(50))

class ExecRecord(Base):
    __tablename__ = 'exec_record'
    id = Column(Integer, primary_key=True, index=True)
    asset_ids = Column(String(255), nullable=False)
    command = Column(Text, nullable=False)
    exec_user = Column(String(50), nullable=False)
    exec_status = Column(SmallInteger, nullable=False, default=0)
    exec_result = Column(Text)
    create_time = Column(DateTime, nullable=False, server_default=func.now())

class DeployProject(Base):
    __tablename__ = 'deploy_project'
    id = Column(Integer, primary_key=True, index=True)
    project_name = Column(String(100), nullable=False)
    git_url = Column(String(255), nullable=False)
    git_branch = Column(String(50), nullable=False, default='main')
    build_script = Column(Text); deploy_script = Column(Text)
    env_type = Column(String(20), nullable=False)
    status = Column(SmallInteger, nullable=False, default=1)
    create_time = Column(DateTime, nullable=False, server_default=func.now())

class CronTask(Base):
    __tablename__ = 'cron_task'
    id = Column(Integer, primary_key=True, index=True)
    task_name = Column(String(100), nullable=False)
    cron_expr = Column(String(50), nullable=False)
    task_type = Column(String(50), nullable=False)
    task_content = Column(Text, nullable=False)
    status = Column(SmallInteger, nullable=False, default=1)
    create_time = Column(DateTime, nullable=False, server_default=func.now())

class AlertRule(Base):
    __tablename__ = 'alert_rule'
    id = Column(Integer, primary_key=True, index=True)
    rule_name = Column(String(100), nullable=False)
    metric = Column(String(100), nullable=False)
    threshold = Column(String(50), nullable=False)
    level = Column(String(20), nullable=False)
    webhook = Column(String(255), nullable=False)
    status = Column(SmallInteger, nullable=False, default=1)
''')

w('easyops_api/common/security.py', r'''
from datetime import datetime, timedelta
from jose import jwt
from passlib.context import CryptContext
from config import settings
pwd_context = CryptContext(schemes=['bcrypt'], deprecated='auto')
def hash_password(password: str) -> str: return pwd_context.hash(password)
def verify_password(plain: str, hashed: str) -> bool: return pwd_context.verify(plain, hashed)
def create_access_token(data: dict, expires_minutes: int | None = None) -> str:
    payload = data.copy(); payload['exp'] = datetime.utcnow() + timedelta(minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
''')

w('easyops_api/dependencies.py', r'''
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from config import settings
from database.session import get_db
from database.models import SysUser
oauth2_scheme = OAuth2PasswordBearer(tokenUrl='/api/v1/user/login')
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> SysUser:
    exc = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='认证失败')
    try:
        username = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]).get('sub')
    except JWTError:
        raise exc
    user = db.query(SysUser).filter(SysUser.username == username).first()
    if not user: raise exc
    return user
''')

w('easyops_api/schemas/all.py', r'''
from pydantic import BaseModel, EmailStr
class LoginRequest(BaseModel): username: str; password: str
class UserCreate(BaseModel): username: str; password: str; nickname: str; email: EmailStr | None = None; phone: str | None = None; role_id: int = 1
class UserOut(BaseModel):
    id: int; username: str; nickname: str; email: str | None = None; phone: str | None = None; role_id: int; status: int
    class Config: from_attributes = True
class AssetCreate(BaseModel):
    asset_name: str; ip_address: str; ssh_port: int = 22; ssh_user: str; ssh_pwd: str | None = None; ssh_key: str | None = None; os_type: str | None = None; env_type: str = 'dev'; business_group: str | None = None
class AssetUpdate(AssetCreate): online_status: int = 0; cpu: str | None = None; mem: str | None = None; disk: str | None = None
class AssetOut(AssetUpdate):
    id: int
    class Config: from_attributes = True
class BatchExecRequest(BaseModel): asset_ids: list[int]; command: str
class ExecRecordOut(BaseModel):
    id: int; asset_ids: str; command: str; exec_user: str; exec_status: int; exec_result: str | None = None
    class Config: from_attributes = True
class DeployProjectCreate(BaseModel): project_name: str; git_url: str; git_branch: str = 'main'; build_script: str | None = None; deploy_script: str | None = None; env_type: str = 'dev'; status: int = 1
class DeployProjectOut(DeployProjectCreate):
    id: int
    class Config: from_attributes = True
class AlertRuleCreate(BaseModel): rule_name: str; metric: str; threshold: str; level: str = '一般'; webhook: str; status: int = 1
class AlertRuleOut(AlertRuleCreate):
    id: int
    class Config: from_attributes = True
class CronTaskCreate(BaseModel): task_name: str; cron_expr: str; task_type: str; task_content: str; status: int = 1
class CronTaskOut(CronTaskCreate):
    id: int
    class Config: from_attributes = True
''')

w('easyops_api/tasks/celery_app.py', r'''
from celery import Celery
from config import settings
celery = Celery('easyops', broker=settings.CELERY_BROKER_URL, backend=settings.CELERY_RESULT_BACKEND)
celery.conf.update(task_serializer='json', accept_content=['json'], result_serializer='json', timezone='Asia/Shanghai', enable_utc=False)
celery.autodiscover_tasks(['tasks.exec_tasks', 'tasks.monitor_tasks', 'tasks.backup_tasks'])
''')

w('easyops_api/tasks/exec_tasks.py', r'''
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
''')
w('easyops_api/tasks/monitor_tasks.py', "from tasks.celery_app import celery\n@celery.task\ndef collect_metric_snapshot(): return {'status':'ok'}")
w('easyops_api/tasks/backup_tasks.py', "from tasks.celery_app import celery\n@celery.task\ndef run_backup_job(target: str): return {'target': target, 'status':'success'}")

w('easyops_api/api/v1/user.py', r'''
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database.session import get_db
from database.models import SysUser, SysRole
from schemas.all import LoginRequest, UserCreate, UserOut
from common.security import create_access_token, hash_password, verify_password
router = APIRouter()
@router.post('/login')
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(SysUser).filter(SysUser.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password): raise HTTPException(status_code=401, detail='用户名或密码错误')
    return {'access_token': create_access_token({'sub': user.username}), 'token_type': 'bearer', 'user': UserOut.model_validate(user)}
@router.post('/', response_model=UserOut)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    user = SysUser(**payload.model_dump(exclude={'password'}), password=hash_password(payload.password)); db.add(user); db.commit(); db.refresh(user); return user
@router.get('/', response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)): return db.query(SysUser).order_by(SysUser.id.desc()).all()
@router.post('/init-admin')
def init_admin(db: Session = Depends(get_db)):
    if not db.query(SysRole).filter(SysRole.role_code == 'admin').first(): db.add(SysRole(role_name='管理员', role_code='admin', description='系统管理员'))
    if not db.query(SysUser).filter(SysUser.username == 'admin').first(): db.add(SysUser(username='admin', password=hash_password('admin123'), nickname='系统管理员', role_id=1, status=1))
    db.commit(); return {'username':'admin','password':'admin123'}
''')

w('easyops_api/api/v1/asset.py', r'''
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database.session import get_db
from database.models import ServerAsset
from schemas.all import AssetCreate, AssetUpdate, AssetOut
router = APIRouter()
@router.get('/', response_model=list[AssetOut])
def list_assets(db: Session = Depends(get_db)): return db.query(ServerAsset).order_by(ServerAsset.id.desc()).all()
@router.post('/', response_model=AssetOut)
def create_asset(payload: AssetCreate, db: Session = Depends(get_db)):
    item = ServerAsset(**payload.model_dump()); db.add(item); db.commit(); db.refresh(item); return item
@router.put('/{asset_id}', response_model=AssetOut)
def update_asset(asset_id: int, payload: AssetUpdate, db: Session = Depends(get_db)):
    item = db.get(ServerAsset, asset_id)
    if not item: raise HTTPException(status_code=404, detail='资产不存在')
    for k,v in payload.model_dump().items(): setattr(item,k,v)
    db.commit(); db.refresh(item); return item
@router.delete('/{asset_id}')
def delete_asset(asset_id: int, db: Session = Depends(get_db)):
    item = db.get(ServerAsset, asset_id)
    if not item: raise HTTPException(status_code=404, detail='资产不存在')
    db.delete(item); db.commit(); return {'ok': True}
''')

w('easyops_api/api/v1/exec_task.py', r'''
import json
from celery import group
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database.session import get_db
from database.models import ExecRecord, ServerAsset, SysUser
from dependencies import get_current_user
from schemas.all import BatchExecRequest, ExecRecordOut
from tasks.exec_tasks import batch_exec_command
router = APIRouter()
@router.post('/batch')
def batch_exec(payload: BatchExecRequest, db: Session = Depends(get_db), user: SysUser = Depends(get_current_user)):
    assets = db.query(ServerAsset).filter(ServerAsset.id.in_(payload.asset_ids)).all()
    record = ExecRecord(asset_ids=','.join(map(str,payload.asset_ids)), command=payload.command, exec_user=user.username, exec_status=0)
    db.add(record); db.commit(); db.refresh(record)
    job = group(batch_exec_command.s(a.ip_address, a.ssh_port, a.ssh_user, a.ssh_pwd or '', payload.command) for a in assets)()
    record.exec_result = json.dumps({'record_id': record.id, 'celery_group_id': job.id}, ensure_ascii=False); db.commit()
    return {'record_id': record.id, 'group_id': job.id, 'hosts': [a.ip_address for a in assets]}
@router.get('/records', response_model=list[ExecRecordOut])
def records(db: Session = Depends(get_db)): return db.query(ExecRecord).order_by(ExecRecord.id.desc()).limit(100).all()
''')

w('easyops_api/api/v1/docker_k8s.py', r'''
from fastapi import APIRouter
router = APIRouter()
@router.get('/docker/containers')
def docker_containers():
    try:
        import docker; c = docker.from_env()
        return [{'id': x.short_id, 'name': x.name, 'status': x.status} for x in c.containers.list(all=True)]
    except Exception as exc: return [{'error': str(exc)}]
@router.get('/k8s/pods')
def k8s_pods(namespace: str = 'default'):
    try:
        from kubernetes import client, config; config.load_incluster_config(); pods = client.CoreV1Api().list_namespaced_pod(namespace)
        return [{'name': p.metadata.name, 'phase': p.status.phase, 'namespace': namespace} for p in pods.items]
    except Exception as exc: return [{'error': str(exc)}]
''')

w('easyops_api/api/v1/deploy.py', r'''
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database.session import get_db
from database.models import DeployProject
from schemas.all import DeployProjectCreate, DeployProjectOut
router = APIRouter()
@router.get('/projects', response_model=list[DeployProjectOut])
def list_projects(db: Session = Depends(get_db)): return db.query(DeployProject).order_by(DeployProject.id.desc()).all()
@router.post('/projects', response_model=DeployProjectOut)
def create_project(payload: DeployProjectCreate, db: Session = Depends(get_db)):
    item = DeployProject(**payload.model_dump()); db.add(item); db.commit(); db.refresh(item); return item
@router.post('/projects/{project_id}/run')
def run_deploy(project_id: int): return {'project_id': project_id, 'status': 'submitted'}
''')

w('easyops_api/api/v1/alert.py', r'''
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database.session import get_db
from database.models import AlertRule
from schemas.all import AlertRuleCreate, AlertRuleOut
router = APIRouter()
@router.get('/rules', response_model=list[AlertRuleOut])
def list_rules(db: Session = Depends(get_db)): return db.query(AlertRule).order_by(AlertRule.id.desc()).all()
@router.post('/rules', response_model=AlertRuleOut)
def create_rule(payload: AlertRuleCreate, db: Session = Depends(get_db)):
    item = AlertRule(**payload.model_dump()); db.add(item); db.commit(); db.refresh(item); return item
''')

w('easyops_api/api/v1/cron_task.py', r'''
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database.session import get_db
from database.models import CronTask
from schemas.all import CronTaskCreate, CronTaskOut
router = APIRouter()
@router.get('/tasks', response_model=list[CronTaskOut])
def list_tasks(db: Session = Depends(get_db)): return db.query(CronTask).order_by(CronTask.id.desc()).all()
@router.post('/tasks', response_model=CronTaskOut)
def create_task(payload: CronTaskCreate, db: Session = Depends(get_db)):
    item = CronTask(**payload.model_dump()); db.add(item); db.commit(); db.refresh(item); return item
''')

w('easyops_api/main.py', r'''
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
''')

w('easyops_web/package.json', '{"scripts":{"dev":"vite --host 0.0.0.0","build":"vite build","preview":"vite preview"},"dependencies":{"@vitejs/plugin-vue":"latest","vite":"latest","vue":"latest","vue-router":"latest","element-plus":"latest","axios":"latest"},"devDependencies":{}}')
w('easyops_web/Dockerfile', r'''
FROM docker.m.daocloud.io/library/node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm config set registry https://registry.npmmirror.com && npm install
COPY . .
RUN chmod -R +x node_modules/.bin && npm run build
FROM docker.m.daocloud.io/library/nginx:1.25-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
''')
w('easyops_web/.dockerignore', r'''
node_modules
dist
.vite
npm-debug.log*
yarn-debug.log*
yarn-error.log*
.DS_Store
''')
w('easyops_web/nginx.conf', "server { listen 80; root /usr/share/nginx/html; index index.html; location / { try_files $uri $uri/ /index.html; } location /api/ { proxy_pass http://api:8000/api/; } }")
w('easyops_web/index.html', '<div id="app"></div><script type="module" src="/src/main.js"></script>')
w('easyops_web/vite.config.mjs', "import { defineConfig } from 'vite'; import vue from '@vitejs/plugin-vue'; export default defineConfig({plugins:[vue()],server:{proxy:{'/api':'http://localhost:8000'}}})")
w('easyops_web/src/main.js', "import {createApp} from 'vue';import ElementPlus from 'element-plus';import 'element-plus/dist/index.css';import App from './App.vue';import router from './router';createApp(App).use(router).use(ElementPlus).mount('#app')")
w('easyops_web/src/App.vue', '<template><router-view /></template>')
w('easyops_web/src/api/http.js', "import axios from 'axios';const http=axios.create({baseURL:'/api/v1'});http.interceptors.request.use(c=>{const t=localStorage.getItem('token');if(t)c.headers.Authorization=`Bearer ${t}`;return c});export default http")
w('easyops_web/src/api/user.js', "import http from './http';export const loginApi=d=>http.post('/user/login',d);export const initAdminApi=()=>http.post('/user/init-admin')")
w('easyops_web/src/api/asset.js', "import http from './http';export const getAssetList=()=>http.get('/asset/');export const createAsset=d=>http.post('/asset/',d)")
w('easyops_web/src/api/exec.js', "import http from './http';export const getAssetList=()=>http.get('/asset/');export const batchExecApi=d=>http.post('/exec/batch',d)")
w('easyops_web/src/api/deploy.js', "import http from './http';export const listProjects=()=>http.get('/deploy/projects');export const createProject=d=>http.post('/deploy/projects',d);export const runDeploy=id=>http.post(`/deploy/projects/${id}/run`)")
w('easyops_web/src/api/container.js', "import http from './http';export const listContainers=()=>http.get('/container/docker/containers');export const listPods=()=>http.get('/container/k8s/pods')")
w('easyops_web/src/api/alert.js', "import http from './http';export const listRules=()=>http.get('/alert/rules');export const createRule=d=>http.post('/alert/rules',d)")
w('easyops_web/src/api/cron.js', "import http from './http';export const listCronTasks=()=>http.get('/cron/tasks');export const createCronTask=d=>http.post('/cron/tasks',d)")
w('easyops_web/src/router/index.js', r'''
import {createRouter,createWebHistory} from 'vue-router';import Layout from '../views/Layout.vue';
const routes=[{path:'/login',component:()=>import('../views/Login.vue')},{path:'/',component:Layout,children:[{path:'',component:()=>import('../views/Dashboard.vue')},{path:'asset',component:()=>import('../views/asset/AssetList.vue')},{path:'exec',component:()=>import('../views/exec/BatchExec.vue')},{path:'docker',component:()=>import('../views/docker/DockerManage.vue')},{path:'deploy',component:()=>import('../views/deploy/DeployProject.vue')},{path:'alert',component:()=>import('../views/alert/AlertRule.vue')},{path:'cron',component:()=>import('../views/cron/CronTask.vue')}]}];
const router=createRouter({history:createWebHistory(),routes});router.beforeEach(to=>{if(to.path!='/login'&&!localStorage.getItem('token'))return '/login'});export default router
''')
w('easyops_web/src/views/Layout.vue', '<template><el-container style="height:100vh"><el-aside width="220px"><el-menu router><el-menu-item index="/">仪表盘</el-menu-item><el-menu-item index="/asset">资产管理</el-menu-item><el-menu-item index="/exec">批量执行</el-menu-item><el-menu-item index="/docker">容器管理</el-menu-item><el-menu-item index="/deploy">CI/CD部署</el-menu-item><el-menu-item index="/alert">监控告警</el-menu-item><el-menu-item index="/cron">定时任务</el-menu-item></el-menu></el-aside><el-container><el-header><b>EasyOps 自动化运维平台</b></el-header><el-main><router-view /></el-main></el-container></el-container></template>')
w('easyops_web/src/views/Login.vue', '<template><div style="width:380px;margin:15vh auto"><el-card header="EasyOps 登录"><el-input v-model="form.username"/><el-input v-model="form.password" type="password" style="margin-top:8px"/><el-button type="primary" style="width:100%;margin-top:8px" @click="login">登录</el-button><el-button style="width:100%;margin:8px 0 0" @click="init">初始化管理员</el-button></el-card></div></template><script setup>import {reactive} from "vue";import {loginApi,initAdminApi} from "../api/user";const form=reactive({username:"admin",password:"admin123"});const login=async()=>{const r=await loginApi(form);localStorage.setItem("token",r.data.access_token);location.href="/"};const init=async()=>{await initAdminApi();alert("已初始化：admin/admin123")}</script>')
w('easyops_web/src/views/Dashboard.vue', '<template><el-card header="平台总览">EasyOps：资产管理、批量执行、容器管理、CI/CD、监控告警、定时任务。</el-card></template>')
w('easyops_web/src/views/asset/AssetList.vue', '<template><el-card header="服务器资产"><el-button @click="load">刷新</el-button><el-table :data="list"><el-table-column prop="asset_name" label="名称"/><el-table-column prop="ip_address" label="IP"/><el-table-column prop="env_type" label="环境"/></el-table></el-card></template><script setup>import{ref,onMounted}from"vue";import{getAssetList}from"../../api/asset";const list=ref([]);const load=async()=>{list.value=(await getAssetList()).data};onMounted(load)</script>')
w('easyops_web/src/views/exec/BatchExec.vue', '<template><el-card header="批量命令执行"><el-select v-model="assetIds" multiple style="width:100%"><el-option v-for="a in assets" :key="a.id" :label="a.ip_address" :value="a.id"/></el-select><el-input v-model="command" type="textarea" style="margin-top:12px"/><el-button type="primary" @click="run" style="margin-top:12px">执行</el-button><pre>{{result}}</pre></el-card></template><script setup>import{ref,onMounted}from"vue";import{getAssetList,batchExecApi}from"../../api/exec";const assets=ref([]),assetIds=ref([]),command=ref("uptime"),result=ref("");onMounted(async()=>assets.value=(await getAssetList()).data);const run=async()=>result.value=JSON.stringify((await batchExecApi({asset_ids:assetIds.value,command:command.value})).data,null,2)</script>')
w('easyops_web/src/views/docker/DockerManage.vue', '<template><el-card header="容器管理"><el-button @click="load">刷新 Docker</el-button><el-table :data="list"><el-table-column prop="name" label="名称"/><el-table-column prop="status" label="状态"/><el-table-column prop="error" label="错误"/></el-table></el-card></template><script setup>import{ref,onMounted}from"vue";import{listContainers}from"../../api/container";const list=ref([]);const load=async()=>list.value=(await listContainers()).data;onMounted(load)</script>')
w('easyops_web/src/views/deploy/DeployProject.vue', '<template><el-card header="CI/CD 部署"><el-button @click="load">刷新</el-button><el-table :data="list"><el-table-column prop="project_name" label="项目"/><el-table-column prop="git_url" label="仓库"/></el-table></el-card></template><script setup>import{ref,onMounted}from"vue";import{listProjects}from"../../api/deploy";const list=ref([]);const load=async()=>list.value=(await listProjects()).data;onMounted(load)</script>')
w('easyops_web/src/views/alert/AlertRule.vue', '<template><el-card header="监控告警"><el-button @click="load">刷新</el-button><el-table :data="list"><el-table-column prop="rule_name" label="规则"/><el-table-column prop="metric" label="指标"/></el-table></el-card></template><script setup>import{ref,onMounted}from"vue";import{listRules}from"../../api/alert";const list=ref([]);const load=async()=>list.value=(await listRules()).data;onMounted(load)</script>')
w('easyops_web/src/views/cron/CronTask.vue', '<template><el-card header="定时任务"><el-button @click="load">刷新</el-button><el-table :data="list"><el-table-column prop="task_name" label="任务"/><el-table-column prop="cron_expr" label="Cron"/></el-table></el-card></template><script setup>import{ref,onMounted}from"vue";import{listCronTasks}from"../../api/cron";const list=ref([]);const load=async()=>list.value=(await listCronTasks()).data;onMounted(load)</script>')

w('k8s/easyops-api.yaml', r'''
apiVersion: apps/v1
kind: Deployment
metadata: {name: easyops-api}
spec:
  replicas: 2
  selector: {matchLabels: {app: easyops-api}}
  template:
    metadata: {labels: {app: easyops-api}}
    spec:
      containers:
        - name: api
          image: easyops-api:latest
          ports: [{containerPort: 8000}]
---
apiVersion: v1
kind: Service
metadata: {name: easyops-api-svc}
spec:
  selector: {app: easyops-api}
  ports: [{port: 80, targetPort: 8000}]
''')
deployment_doc = root / 'docs/deployment.md'
deployment_doc.parent.mkdir(parents=True, exist_ok=True)
if not deployment_doc.exists():
    deployment_doc.write_text(
        '# EasyOps 部署手册\n\n'
        '执行 `docker compose up -d --build` 启动全套环境。\n\n'
        '本项目默认使用 DaoCloud 国内代理镜像、清华 PyPI 镜像源与 npmmirror，详细生产部署步骤请参考仓库中的 `docs/deployment.md` 完整版。\n',
        encoding='utf-8'
    )

print('EasyOps project generated')
