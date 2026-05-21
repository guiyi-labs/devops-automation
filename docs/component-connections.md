# EasyOps 各组件连接信息总表

本文档集中记录 EasyOps 在 Docker Compose / Rocky Linux 测试环境中的所有核心组件连接信息，包括访问地址、容器内地址、端口、环境变量、默认账号、依赖关系与常用排查命令。

> 说明：当前项目默认以 `docker-compose.yml` 单机部署为主。容器之间通过 Docker Compose 默认网络互相访问，服务名即 DNS 名称，例如 `api`、`mysql`、`redis`。

## 1. 总体连接拓扑

```text
浏览器
  │
  ├── http://服务器IP:8080
  │        │
  │        ▼
  │   web / Nginx / Vue3
  │        │ /api/*
  │        ▼
  │   api:8000 / FastAPI
  │        ├── mysql:3306 / 业务数据
  │        ├── redis:6379 / 缓存、Token、任务队列
  │        ├── Docker Engine / 容器管理，可选
  │        ├── K8s APIServer / 集群管理，可选
  │        └── 被管服务器 SSH:22 / 批量命令、巡检、备份
  │
  ├── http://服务器IP:8000/docs / Swagger 调试
  ├── http://服务器IP:9090 / Prometheus
  └── http://服务器IP:3000 / Grafana

celery worker
  ├── redis:6379 / Broker 与结果后端
  ├── mysql:3306 / 读取资产与写任务记录
  └── 被管服务器 SSH:22 / 实际执行批量运维任务

prometheus
  └── api:8000/metrics / FastAPI 指标采集

grafana
  └── prometheus:9090 / 指标数据源
```

## 2. 对外访问地址

| 组件 | 默认访问地址 | 默认端口 | 用途 | 是否建议公网开放 |
| --- | --- | ---: | --- | --- |
| Web 前端 | `http://服务器IP:8080` | 8080 | EasyOps 管理后台 | 不建议公网开放，建议 VPN / 办公网 |
| API Swagger | `http://服务器IP:8000/docs` | 8000 | FastAPI 接口文档与调试 | 不建议公网开放 |
| API Metrics | `http://服务器IP:8000/metrics` | 8000 | Prometheus 指标 | 不建议公网开放 |
| Prometheus | `http://服务器IP:9090` | 9090 | 指标查询 | 不建议公网开放 |
| Grafana | `http://服务器IP:3000` | 3000 | 监控大盘 | 可内网开放，生产需改密码 |
| MySQL | `服务器IP:3306` | 3306 | 业务数据库 | 禁止公网开放 |
| Redis | `服务器IP:6379` | 6379 | 缓存 / 队列 | 禁止公网开放 |

生产建议只开放：

- `8080` 或统一 HTTPS 网关端口，例如 `443`
- 必要时开放 `3000` 给内网运维人员

不建议直接开放：

- `3306`
- `6379`
- `8000`
- `9090`

## 3. Docker Compose 服务连接总表

| Compose 服务名 | 容器内监听端口 | 宿主机映射 | 其他组件访问地址 | 说明 |
| --- | ---: | --- | --- | --- |
| `web` | 80 | `8080:80` | 浏览器访问 `http://服务器IP:8080` | Vue3 构建产物由 Nginx 提供 |
| `api` | 8000 | `8000:8000` | 容器内访问 `http://api:8000` | FastAPI 后端服务 |
| `celery` | 无 HTTP 端口 | 无 | 通过 Redis 接收任务 | 异步任务 Worker |
| `mysql` | 3306 | `3306:3306` | `mysql:3306` | 业务主数据库 |
| `redis` | 6379 | `6379:6379` | `redis:6379` | 缓存、Celery Broker、结果后端 |
| `prometheus` | 9090 | `9090:9090` | `http://prometheus:9090` | 指标采集与查询 |
| `grafana` | 3000 | `3000:3000` | `http://grafana:3000` | 监控可视化 |

## 4. 前端 Web 连接信息

### 4.1 浏览器到 Web

| 项目 | 值 |
| --- | --- |
| 访问地址 | `http://服务器IP:8080` |
| Compose 服务 | `web` |
| 容器端口 | `80` |
| 宿主机端口 | `8080` |
| 镜像构建目录 | `easyops_web` |
| Dockerfile | `easyops_web/Dockerfile` |
| Nginx 配置 | `easyops_web/nginx.conf` |

### 4.2 Web 到 API

前端生产环境通过 Nginx 反向代理访问 API。

| 调用方 | 被调用方 | 访问路径 | 实际代理目标 |
| --- | --- | --- | --- |
| 浏览器 / Vue | Web Nginx | `/api/v1/...` | `http://api:8000/api/v1/...` |

当前 `easyops_web/nginx.conf`：

```nginx
location /api/ {
  proxy_pass http://api:8000/api/;
}
```

前端 Axios 默认配置：

```javascript
baseURL: '/api/v1'
```

因此浏览器侧请求示例：

```text
http://服务器IP:8080/api/v1/user/login
```

容器内实际转发到：

```text
http://api:8000/api/v1/user/login
```

### 4.3 前端本地开发连接

本地 Vite 开发环境通过 `easyops_web/vite.config.js` 代理：

```text
/api -> http://localhost:8000
```

开发启动顺序：

```bash
# 先启动后端
cd easyops_api
uvicorn main:app --host 0.0.0.0 --port 8000

# 再启动前端
cd easyops_web
npm install
npm run dev
```

## 5. API 后端连接信息

| 项目 | 值 |
| --- | --- |
| Compose 服务 | `api` |
| 容器端口 | `8000` |
| 宿主机端口 | `8000` |
| 容器内访问地址 | `http://api:8000` |
| 宿主机访问地址 | `http://服务器IP:8000` |
| Swagger | `http://服务器IP:8000/docs` |
| OpenAPI JSON | `http://服务器IP:8000/openapi.json` |
| Metrics | `http://服务器IP:8000/metrics` |
| 启动命令 | `uvicorn main:app --host 0.0.0.0 --port 8000` |
| 配置文件 | `easyops_api/config.py` |

API 依赖的外部组件：

| 依赖 | 地址 | 用途 |
| --- | --- | --- |
| MySQL | `mysql:3306` | 用户、资产、任务记录、部署项目、告警规则等业务数据 |
| Redis | `redis:6379` | 缓存、Token、Celery Broker / Backend |
| Docker Engine | 本机 `/var/run/docker.sock` 或远程 Docker API | 容器管理，可选 |
| K8s APIServer | 集群内配置或 kubeconfig | K8s 管理，可选 |
| 被管服务器 | `资产IP:SSH端口` | 批量执行、巡检、备份 |

## 6. MySQL 连接信息

| 项目 | 默认值 |
| --- | --- |
| Compose 服务 | `mysql` |
| 容器端口 | `3306` |
| 宿主机端口 | `3306` |
| 容器内连接地址 | `mysql:3306` |
| 默认数据库 | `easyops` |
| 默认用户 | `root` |
| 默认密码 | `root123456` |
| 数据卷 | `mysql_data:/var/lib/mysql` |
| 字符集 | `utf8mb4` |

后端 SQLAlchemy 默认连接串格式：

```text
mysql+pymysql://root:root123456@mysql:3306/easyops?charset=utf8mb4
```

相关环境变量：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MYSQL_HOST` | `mysql` | MySQL 服务名 |
| `MYSQL_PORT` | `3306` | MySQL 端口 |
| `MYSQL_USER` | `root` | 数据库用户 |
| `MYSQL_PASSWORD` | `root123456` | 数据库密码 |
| `MYSQL_DB` | `easyops` | 数据库名 |

容器内连接测试：

```bash
docker compose exec mysql mysql -uroot -proot123456 easyops
```

API 容器到 MySQL 连通性排查：

```bash
docker compose logs api
docker compose ps mysql
docker compose exec mysql mysqladmin ping -uroot -proot123456
```

## 7. Redis 连接信息

| 项目 | 默认值 |
| --- | --- |
| Compose 服务 | `redis` |
| 容器端口 | `6379` |
| 宿主机端口 | `6379` |
| 容器内连接地址 | `redis:6379` |
| 默认密码 | 未设置 |
| 数据卷 | `redis_data:/data` |

相关环境变量：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `REDIS_HOST` | `redis` | Redis 服务名 |
| `REDIS_PORT` | `6379` | Redis 端口 |
| `CELERY_BROKER_URL` | `redis://redis:6379/0` | Celery Broker |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/0` | Celery 任务结果后端 |

连接测试：

```bash
docker compose exec redis redis-cli ping
```

期望输出：

```text
PONG
```

## 8. Celery Worker 连接信息

| 项目 | 默认值 |
| --- | --- |
| Compose 服务 | `celery` |
| HTTP 端口 | 无 |
| 启动命令 | `celery -A tasks.celery_app.celery worker -l INFO` |
| Broker | `redis://redis:6379/0` |
| Result Backend | `redis://redis:6379/0` |
| 任务模块 | `tasks.exec_tasks`、`tasks.monitor_tasks`、`tasks.backup_tasks` |

Celery 依赖关系：

| 依赖 | 地址 | 用途 |
| --- | --- | --- |
| Redis | `redis:6379` | 接收任务、保存任务状态 |
| MySQL | `mysql:3306` | 读取资产信息、写入执行记录 |
| 被管服务器 SSH | `资产IP:资产SSH端口` | 远程执行命令 |

查看 Worker 日志：

```bash
docker compose logs -f celery
```

重启 Worker：

```bash
docker compose restart celery
```

## 9. Prometheus 连接信息

| 项目 | 默认值 |
| --- | --- |
| Compose 服务 | `prometheus` |
| 容器端口 | `9090` |
| 宿主机端口 | `9090` |
| 宿主机访问 | `http://服务器IP:9090` |
| 配置文件 | `prometheus.yml` |

当前采集目标：

| job_name | metrics_path | targets | 说明 |
| --- | --- | --- | --- |
| `easyops-api` | `/metrics` | `api:8000` | 采集 FastAPI 指标 |

Prometheus 配置示例：

```yaml
scrape_configs:
  - job_name: easyops-api
    metrics_path: /metrics
    static_configs:
      - targets: ['api:8000']
```

健康检查：

```bash
curl http://127.0.0.1:9090/-/healthy
```

检查采集目标：

```text
http://服务器IP:9090/targets
```

## 10. Grafana 连接信息

| 项目 | 默认值 |
| --- | --- |
| Compose 服务 | `grafana` |
| 容器端口 | `3000` |
| 宿主机端口 | `3000` |
| 访问地址 | `http://服务器IP:3000` |
| 默认账号 | `admin` |
| 默认密码 | `admin` |
| 数据卷 | `grafana_data:/var/lib/grafana` |

Grafana 添加 Prometheus 数据源：

| 配置项 | 值 |
| --- | --- |
| Type | `Prometheus` |
| URL | `http://prometheus:9090` |
| Access | Server / Backend |

注意：Grafana 容器内访问 Prometheus 必须使用：

```text
http://prometheus:9090
```

不要使用：

```text
http://localhost:9090
```

因为 `localhost` 在 Grafana 容器内指向 Grafana 自己。

## 11. Docker 管理连接信息

当前后端容器管理接口位于：

```text
GET /api/v1/container/docker/containers
```

浏览器经 Web 访问：

```text
http://服务器IP:8080/api/v1/container/docker/containers
```

直接访问 API：

```text
http://服务器IP:8000/api/v1/container/docker/containers
```

如需 API 容器管理宿主机 Docker，通常需要在 `docker-compose.yml` 中给 `api` 挂载 Docker Socket：

```yaml
services:
  api:
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
```

安全提醒：

- 挂载 Docker Socket 等同于给 API 容器较高宿主机控制权限。
- 生产环境建议增加权限控制、审计与操作审批。

## 12. Kubernetes 管理连接信息

当前 K8s 示例接口：

```text
GET /api/v1/container/k8s/pods?namespace=default
```

K8s 连接方式取决于部署位置：

| 部署方式 | 连接方式 | 说明 |
| --- | --- | --- |
| API 部署在 K8s 集群内 | `config.load_incluster_config()` | 使用 ServiceAccount 访问 APIServer |
| API 部署在普通 Docker 环境 | `kubeconfig` | 需要挂载 kubeconfig 到容器内 |

如果在 Docker Compose 中访问外部 K8s，可挂载 kubeconfig：

```yaml
services:
  api:
    volumes:
      - ~/.kube/config:/root/.kube/config:ro
```

并在代码中使用：

```python
config.load_kube_config()
```

## 13. 被管服务器 SSH 连接信息

资产表中的 SSH 字段：

| 字段 | 说明 | 示例 |
| --- | --- | --- |
| `ip_address` | 被管服务器 IP | `192.168.1.10` |
| `ssh_port` | SSH 端口 | `22` |
| `ssh_user` | SSH 用户 | `root` |
| `ssh_pwd` | SSH 密码 | `******` |
| `ssh_key` | SSH 私钥 | PEM 私钥文本，可扩展使用 |

连接方向：

```text
celery / api -> 被管服务器IP:SSH端口
```

手工连通性测试：

```bash
ssh -p 22 root@被管服务器IP "hostname && uptime"
```

在容器内测试网络连通性：

```bash
docker compose exec api bash
python - <<'PY'
import socket
host = '被管服务器IP'
port = 22
s = socket.create_connection((host, port), timeout=5)
print('SSH reachable:', s.getpeername())
s.close()
PY
```

## 14. CI/CD 连接信息

项目提供 `.gitlab-ci.yml` 示例。

| 阶段 | 连接对象 | 说明 |
| --- | --- | --- |
| build | Docker daemon / dind | 构建镜像 |
| push | 镜像仓库 | 推送 `easyops-api:${CI_COMMIT_SHA}` |
| deploy | 部署服务器 SSH | 远程执行 `kubectl apply` |

示例部署连接：

```yaml
ssh root@deploy-server "kubectl apply -f /opt/easyops/k8s/"
```

生产建议：

- 使用 GitLab CI Variables 保存 SSH 私钥、镜像仓库密码。
- 不要在 `.gitlab-ci.yml` 中写明文密钥。
- 部署服务器应限制来源 IP，仅允许 CI Runner 访问。

## 15. 默认账号与密码汇总

| 组件 | 账号 | 密码 | 说明 |
| --- | --- | --- | --- |
| EasyOps 管理员 | `admin` | `admin123` | 登录页点击“初始化管理员”后创建 |
| MySQL | `root` | `root123456` | 仅演示默认值，生产必须修改 |
| Redis | 无 | 无 | 默认未启用密码，生产建议开启 |
| Grafana | `admin` | `admin` | 首次登录后必须修改 |

## 16. 环境变量汇总

| 环境变量 | 默认值 | 使用组件 | 说明 |
| --- | --- | --- | --- |
| `MYSQL_HOST` | `mysql` | api / celery | MySQL 服务地址 |
| `MYSQL_PORT` | `3306` | api / celery | MySQL 端口 |
| `MYSQL_USER` | `root` | api / celery | MySQL 用户 |
| `MYSQL_PASSWORD` | `root123456` | api / celery | MySQL 密码 |
| `MYSQL_DB` | `easyops` | api / celery | MySQL 数据库 |
| `REDIS_HOST` | `redis` | api / celery | Redis 服务地址 |
| `REDIS_PORT` | `6379` | api / celery | Redis 端口 |
| `SECRET_KEY` | `easyops-secret-key-2026-devops-project` | api | JWT 签名密钥 |
| `CELERY_BROKER_URL` | `redis://redis:6379/0` | celery / api | Celery Broker |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/0` | celery / api | Celery Backend |

## 17. 常用连通性排查命令

### 17.1 查看所有服务状态

```bash
docker compose ps
```

### 17.2 查看关键日志

```bash
docker compose logs --tail=100 api
docker compose logs --tail=100 web
docker compose logs --tail=100 celery
docker compose logs --tail=100 mysql
docker compose logs --tail=100 redis
docker compose logs --tail=100 prometheus
docker compose logs --tail=100 grafana
```

### 17.3 Web 到 API 代理排查

```bash
curl -I http://127.0.0.1:8080
curl http://127.0.0.1:8000/docs
docker compose exec web nginx -T | grep -A 8 'location /api/'
```

### 17.4 API 到 MySQL 排查

```bash
docker compose ps mysql
docker compose exec mysql mysqladmin ping -uroot -proot123456
docker compose logs --tail=100 api
```

### 17.5 API / Celery 到 Redis 排查

```bash
docker compose ps redis
docker compose exec redis redis-cli ping
docker compose logs --tail=100 celery
```

### 17.6 Prometheus 到 API 指标排查

```bash
curl http://127.0.0.1:8000/metrics
curl http://127.0.0.1:9090/-/healthy
```

浏览器访问：

```text
http://服务器IP:9090/targets
```

### 17.7 Grafana 到 Prometheus 排查

在 Grafana 容器内测试：

```bash
docker compose exec grafana wget -qO- http://prometheus:9090/-/healthy
```

## 18. 生产环境连接安全建议

1. 使用 `.env` 或 Secret 管理所有密码与密钥。
2. 不要公网开放 MySQL、Redis、Prometheus。
3. Grafana 首次登录后立即修改 `admin` 密码。
4. Web 前面建议加 HTTPS 反向代理。
5. API 的 `/docs` 在生产环境建议关闭或限制访问来源。
6. 批量命令执行接口必须增加权限控制、操作审计与高危命令拦截。
7. Docker Socket 和 kubeconfig 属于高危权限，生产环境必须严格限制。