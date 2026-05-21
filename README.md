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

## Linux 运行环境要求

推荐在 Linux 服务器上通过 Docker Compose 运行 EasyOps。详细部署、初始化、日常运维、备份恢复与故障排查请查看：

- [Linux 部署与运维手册](docs/deployment.md)

最低环境：

- 操作系统：CentOS 7/8、Rocky Linux 8/9、Ubuntu 20.04+、Debian 11+、银河麒麟、统信 UOS
- CPU：2 核以上，生产建议 4 核以上
- 内存：4GB 以上，生产建议 8GB 以上
- 磁盘：20GB 以上，生产建议 100GB+ 并单独挂载数据目录
- 软件：Docker 20.10+、Docker Compose v2、Git、curl
- 网络：放通 8080、8000、9090、3000 等访问端口，平台到被管服务器需可访问 SSH 端口

国内服务器建议先配置 Docker 国内镜像源，例如在 `/etc/docker/daemon.json` 中配置 `registry-mirrors`，再执行 `docker compose up -d --build`。详细配置见 [Linux 部署与运维手册](docs/deployment.md#43-配置-docker-国内镜像源)。

项目中的基础镜像已默认替换为 DaoCloud 国内代理地址：

- `docker.m.daocloud.io/library/mysql:5.7`
- `docker.m.daocloud.io/library/redis:6`
- `docker.m.daocloud.io/library/python:3.10-slim`
- `docker.m.daocloud.io/library/node:20-alpine`
- `docker.m.daocloud.io/library/nginx:1.25-alpine`
- `docker.m.daocloud.io/prom/prometheus:latest`
- `docker.m.daocloud.io/grafana/grafana:latest`

访问：
- Web：http://localhost:8080
- API Swagger：http://localhost:8000/docs
- Prometheus：http://localhost:9090
- Grafana：http://localhost:3000

默认管理员初始化：登录页点击“初始化管理员”，账号 `admin/admin123`。
