# EasyOps Kubernetes 部署（附加部署选项）

EasyOps 的**默认部署路径是 Docker Compose**（见 [README](../README.md#快速启动)）。本文档说明
如何把它作为 K8s 工作负载部署——让「系统运维平台」本身可以跑在 Kubernetes 上。

## 为什么现在支持 K8s

- **面向云原生运维方向**：K8s 已事实成为现代应用运行时标准。EasyOps 支持 K8s 部署，说明
  平台自身具备云原生可部署性（镜像、探针、配置注入、持久化、健康检查），而不仅是单机 Compose。
- **可复制、可声明**：所有组件以 manifest 描述（kustomize 组合），`kubectl apply -k` 一键部署，
  与集群状态可对账。
- **不改变产品定位**：EasyOps 仍管理「Linux 主机」（SSH 资产），K8s 只是 EasyOps **自身**的运行
  载体；K8s 集群与工作负载管理能力由 `kubernetes-cluster-bootstrap` 和 `aiops-platform` 承载。

## 镜像化检查结论

容器镜像**无需改动即可运行于 K8s**，前提是满足以下命名与配置假设（已在 manifest 中处理）：

| 假设 | Compose 现状 | K8s 处理 |
|------|--------------|----------|
| API 反向代理主机名 | web nginx `proxy_pass http://api:8000/` | Service 命名 `api`，DNS 一致 |
| Prometheus 抓取目标 | `targets: ['api:8000']` | Service `api` 提供 DNS |
| Grafana datasource | `url: http://prometheus:9090` | Service 命名 `prometheus` |
| 配置注入 | `os.getenv`（`config.py`/`session.py`） | ConfigMap + Secret envFrom，零代码改动 |
| 数据卷 | `mysql_data`/`redis_data`/`backup_data`/`grafana_data` | PVC（hostPath 单节点可直接用） |
| 数据库迁移 | api/celery 启动命令 `alembic upgrade head` | 容器命令保留 + 可选一次性 Job |
| 健康检查 | Compose healthcheck | liveness/readinessProbe（`/health/live`） |

遗留需注意的假设：

1. **网络出站（真实部署/巡检）**：API/Celery 的 SSH 目标地址默认为宿主机
   `host.docker.internal`（本机 Lima 实验）。K8s Pod 默认无此 DNS，因此 `DEPLOY_EXECUTION_MODE`
   在 ConfigMap 中默认 `mock`；真实部署请按你的环境配置 `hostAliases`/NodeIP 指向可达的 SSH
   目标，并保持 `SSH_ALLOW_UNVERIFIED_HOST_KEY=false`（严格指纹校验）。
2. **MySQL 镜像版本**：Compose 默认 `mysql:5.7`（Apple Silicon 用覆盖为 8.0）；manifest 直接用
   `mysql:8.0`（多架构且已验证）。
3. **备份卷共享**：`backups` PVC 为 `ReadWriteOnce`——单节点（kind/单 worker 节点）
   api+celery 可同挂；多节点生产请改用 `ReadWriteMany` 存储类或每副本独立 PVC。

## 部署步骤

### 1. 构建并推送镜像（或 kind 本地加载）

```bash
docker compose build api web
# 推送到你可用 registry，然后替换 manifest 中 image 字段；
# 或 kind 本地验证直接加载：
kind load docker-image devops-automation-api:latest devops-automation-web:latest
```

### 2. 创建 Secret（绝不提交真实值）

```bash
kubectl create namespace easyops 2>/dev/null || true
kubectl create secret generic easyops-secrets -n easyops \
  --from-literal=MYSQL_PASSWORD='<强密码>' \
  --from-literal=SECRET_KEY='<随机 32+ 字符串>' \
  --from-literal=CREDENTIAL_ENCRYPTION_KEY='<随机 32+ 字符串>' \
  --from-literal=INITIAL_ADMIN_PASSWORD='<管理员初始密码>'
```

结构模板见 `k8s/secrets.example.yaml`（占位值，勿直接使用）。

### 3. 应用清单

```bash
kubectl apply -k k8s/
```

### 4. 验证

```bash
# 迁移（可选，API/Celery 已自带 alembic upgrade head）
kubectl -n easyops wait --for=condition=complete job/easyops-migrate --timeout=120s

# 等待就绪
kubectl -n easyops rollout status deployment/easyops-api --timeout=180s
kubectl -n easyops rollout status deployment/easyops-celery --timeout=180s
kubectl -n easyops rollout status deployment/easyops-web --timeout=180s

# 健康
kubectl -n easyops get pods -o wide
kubectl -n easyops get svc

# API 健康探针（端口转发或 NodeIP）
kubectl -n easyops port-forward svc/api 8000:8000 &
curl -s http://127.0.0.1:8000/health/live

# Web（NodePort 30080，kind 用 kubectl port-forward -n easyops svc/web 80:80）
open http://localhost:30080
```

### 5. 初始化管理员（可选，若 Secret 用自动 bootstrap）

`POST /api/v1/user/init-admin` 一次调用初始化 admin（见 API 文档）。

## ConfigMap 注入说明（DB 依赖）

EasyOps 的数据库依赖**全部通过环境变量注入**（`config.py` 的 `os.getenv`、`session.py` 的
`DATABASE_URL` 优先）。因此 K8s 下**无需改代码**，两种方式：

- **默认**：ConfigMap `easyops-config` 提供 `MYSQL_HOST=mysql`、`MYSQL_PORT=3306`、
  `MYSQL_DB=easyops`；Secret 提供 `MYSQL_PASSWORD`。`session.py` 据此拼
  `mysql+pymysql://root:***@mysql:3306/easyops?charset=utf8mb4`。
- **整串覆盖**：若改用外部托管的 MySQL（如云 RDS），在 ConfigMap 增加
  `DATABASE_URL: "mysql+pymysql://user:pass@rds-host:3306/db?charset=utf8mb4"` 即可，
  `session.py` 会优先使用。Cron/任务同样消费同一 ConfigMap。

## 与 Compose 的取舍

| 维度 | Docker Compose（默认） | Kubernetes（附加） |
|------|------------------------|---------------------|
| 上手 | 一条 `docker compose up -d`，最简 | 需要集群 + kubectl/kustomize |
| 目标环境 | 单机演示/中小型 | 集群、声明式、可水平扩展 |
| 副本 | api/web 可 `--scale`，但无编排 | Deployment replicas（api=2, web=2） |
| 健康检查 | Compose healthcheck | Kubernetes 探针（滚动/重启） |
| 配置 | `.env` + compose env | ConfigMap + Secret（envFrom） |
| 持久化 | named volumes | PVC（单节点 hostPath 或 CSI） |
| 服务发现 | compose 服务名 DNS | K8s Service 同名 DNS（api/mysql/redis/prometheus） |
| 监控 | compose 内 Prometheus/Grafana | 同镜像栈，NodePort/Ingress 暴露 |
| 备份恢复 | `backup_data` 卷 + real 模式 | `backups` PVC + real 模式（容器内 mysqldump 可达集群 MySQL） |
| 生产注意 | 单点、需手动处理 HA | 需自行补充 Ingress、资源配额、NetworkPolicy、滚动策略 |

**结论**：Compose 是日常默认；K8s 是展示云原生可部署性的附加选项，二者共享同一镜像与
配置模型，业务逻辑零改动。

## Helm 部署（专业级打包分发）

除 Kustomize 外，EasyOps 提供 [Helm Chart](../charts/easyops/)。二者共享同一语义层
（固定 Service 名 `api`/`mysql`/`redis`/`prometheus`、探针、PVC、镜像），可并行使用；
Kustomize 仍为默认便利路径。

### 安装

```bash
# 1. 构建镜像并加载/推送（同 Kustomize 步骤 1）
docker compose build api web
kind load docker-image devops-automation-api:latest devops-automation-web:latest

# 2. 预建 Secret（凭据不入 Git；Chart 默认 secret.create=false）
kubectl create ns easyops 2>/dev/null || true
kubectl -n easyops create secret generic easyops-secrets \
  --from-literal=MYSQL_PASSWORD='<强密码>' \
  --from-literal=SECRET_KEY='<随机 32+ 字符串>' \
  --from-literal=CREDENTIAL_ENCRYPTION_KEY='<随机 32+ 字符串>' \
  --from-literal=INITIAL_ADMIN_PASSWORD='<管理员初始密码>'

# 3. 安装（可加 --set 覆盖 values；示例值见 charts/easyops/values.yaml）
helm install easyops ./charts/easyops --namespace easyops
```

本地演示若想一条命令生成演示凭据，可用 `--set secret.create=true`（值写进 Secret 对象，
不入 Chart 文件仓库——仍建议仅本地）。

### 覆盖配置示例（values override）

```yaml
# values-prod.yaml：生产覆盖示例
image:
  tag: 0.1.0
  pullPolicy: Always
replicaCount:
  api: 3
  web: 2
  celery: 2
config:
  appEnv: production
  deployExecutionMode: mock   # 未配置 K8s→SSH 出站前保持 mock
service:
  web: { type: LoadBalancer }
  grafana: { type: ClusterIP }
persistence:
  mysql: { size: 50Gi, storageClass: ssd }
resources:
  api: { requests: {cpu: 100m, memory: 256Mi}, limits: {memory: 512Mi} }
```

```bash
helm upgrade easyops ./charts/easyops -f values-prod.yaml --namespace easyops
```

### 与 Kustomize 的取舍

| 维度 | Kustomize（默认便利路径） | Helm（专业级打包） |
|------|---------------------------|---------------------|
| 使用 | `kubectl apply -k k8s/`，零额外依赖 | 需 `helm` CLI；`helm install` |
| 可配置 | 改 yaml / overlay 补丁 | values 覆盖 + `--set`，不改模板 |
| 环境差异 | overlay 目录 | values 文件（dev/prod 覆盖） |
| 校验 | kubeconform（strict） | `helm lint` + `helm template` + kubeconform 渲染产物 |
| 分发 | git 目录 | `helm package` 出 tgz（可发布到 Chart 仓库） |

### Chart 校验（本地）

```bash
helm lint charts/easyops           # 语法/规范
helm template easyops charts/easyops > /tmp/helm-rendered.yaml   # 渲染检查
kubeconform -strict -summary /tmp/helm-rendered.yaml             # 渲染产物 schema 校验
```

## 验证边界（如实说明）

- **已做（静态）**：`kubectl kustomize k8s/` 渲染 23 资源；`kubeconform -strict` 全部 Valid；
  CI 的 kubeconform 步骤会持续校验 `k8s/`。
- **已做（真机，若本仓库维护者环境有 kind）**：kind 集群 `kubectl apply -k`
  部署 → 迁移 Job 完成 → api `/health/live` 200 → web 200 → mysql/redis 就绪。
- **未覆盖**：真实 SSH 部署/巡检从 Pod 出发到外部主机（依赖你的网络可达性，默认 mock）；
  多节点 RWX 备份卷；Ingress TLS；资源配额/NetworkPolicy（生产增强）。