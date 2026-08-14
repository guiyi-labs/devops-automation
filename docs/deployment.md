# EasyOps Linux 部署与运维手册

本文档说明如何在 Linux 环境中部署、运行和运维 EasyOps 轻量企业级 DevOps 自动化运维平台。

## 1. 部署方式选择

EasyOps 推荐两种部署方式：

| 场景 | 推荐方式 | 说明 |
| --- | --- | --- |
| 单机测试 / 中小团队私有化部署 | Docker Compose | 部署最简单，适合 1 台服务器运行全套组件 |
| 生产高可用 / 云原生环境 | Kubernetes YAML | 适合已有 K8s 集群，可扩展 API、Worker、监控组件 |

当前项目已提供：

- `docker-compose.yml`：单机一键部署 MySQL、Redis、API、Celery、Web、Prometheus、Grafana
- `easyops_api/Dockerfile`：后端镜像构建
- `easyops_web/Dockerfile`：前端 Nginx 镜像构建
- `prometheus.yml`：Prometheus 采集配置
- `k8s/easyops-api.yaml`：K8s API Deployment/Service 示例
- `docs/component-connections.md`：各组件连接信息总表，包含地址、端口、账号、环境变量、依赖关系与排查命令
- `docs/uninstall-restore.md`：删除、卸载、还原、测试环境重置与归档同步命令
- `docs/archive-index.md`：当前文档、脚本与关键配置的归档索引

> 国内环境说明：本项目已将 Compose 与 Dockerfile 中的基础镜像默认替换为 DaoCloud 国内代理地址，减少 Docker Hub 拉取失败的问题。

## 2. Linux 环境要求

### 2.1 操作系统

支持以下 Linux / 国产化系统：

- CentOS 7 / 8
- Rocky Linux 8 / 9
- AlmaLinux 8 / 9
- Ubuntu 20.04+
- Debian 11+
- 银河麒麟 / 统信 UOS
- x86_64 / ARM64 均可，前提是 Docker 镜像源支持对应架构

### 2.2 硬件配置

| 环境 | CPU | 内存 | 磁盘 | 说明 |
| --- | --- | --- | --- | --- |
| 开发 / 演示 | 2 核 | 4GB | 20GB | 可运行基础功能 |
| 小型生产 | 4 核 | 8GB | 100GB | 推荐配置 |
| 中型生产 | 8 核+ | 16GB+ | 200GB+ | 可承载更多任务与日志 |

建议：

- MySQL、Redis、Grafana 数据目录放到独立磁盘或独立分区。
- 生产环境建议定期备份 `/var/lib/docker/volumes` 或改为宿主机显式挂载目录。

### 2.3 基础软件

必须安装：

- Docker 20.10+
- Docker Compose v2，即支持 `docker compose` 命令
- Git
- curl / wget

可选安装：

- openssh-clients：用于从平台服务器测试到被管服务器 SSH 连通性
- make：用于后续封装运维命令
- kubectl：如果要部署或管理 K8s

检查命令：

```bash
docker version
docker compose version
git --version
curl --version
```

## 3. 服务器网络与端口要求

完整组件连接关系、默认账号、环境变量和连通性排查命令请参考：`docs/component-connections.md`。

### 3.1 平台对外端口

默认 Compose 暴露端口（E1 起 MySQL / Redis 不映射宿主机端口；叠加
`docker-compose.ports.yml` 才暴露）：

| 端口 | 服务 | 说明 |
| --- | --- | --- |
| 8080 | easyops_web | 前端管理后台 |
| 8000 | easyops_api | FastAPI / Swagger |
| 3306 | mysql | 仅叠加 `docker-compose.ports.yml` 时暴露，生产不建议公网开放 |
| 6379 | redis | 仅叠加 `docker-compose.ports.yml` 时暴露，生产不建议公网开放 |
| 9090 | prometheus | Prometheus |
| 3000 | grafana | Grafana |

生产建议：

- 只对办公网或 VPN 开放 `8080`、`3000`。
- `3306`、`6379` 默认不映射宿主端口；确需对外时再叠加 `docker-compose.ports.yml`。
- API `8000` 建议只由前端 Nginx 或内网访问。
- 可在前面加一层企业 Nginx / SLB / HTTPS 网关。

### 3.2 平台到被管服务器端口

EasyOps 批量命令执行依赖 SSH，因此平台服务器需要能够访问被管服务器：

| 方向 | 端口 | 说明 |
| --- | --- | --- |
| EasyOps API/Celery -> 被管 Linux 主机 | 22 或自定义 SSH 端口 | 批量命令、巡检、备份 |
| EasyOps -> Docker Host | Docker API 端口，可选 | 如果使用远程 Docker API |
| EasyOps -> K8s APIServer | 6443 或集群暴露端口 | 如果使用 Kubernetes 管理 |

测试 SSH 连通性：

```bash
ssh root@被管服务器IP
```

> **SSH host key 要求（E1）**：EasyOps 默认拒绝连接未登记主机密钥指纹的服务器。
> 录入资产时应填写 `host_key_fingerprint`（主机密钥 SHA256/base64 指纹，形如
> `SHA256:...` 去掉前缀后的 base64 串），可通过
> `ssh-keyscan -t ecdsa 服务器IP 2>/dev/null | ssh-keygen -lf -` 计算。
> 仅本地开发演示且明确知晓风险时，可设置 `SSH_ALLOW_UNVERIFIED_HOST_KEY=true`。

### 3.3 服务连接关系

Docker Compose 启动后，各服务位于同一个默认 Docker 网络中，容器之间使用服务名互相访问：

| 调用方 | 被调用方 | 连接地址 | 用途 |
| --- | --- | --- | --- |
| 浏览器 | Web 前端 | `http://服务器IP:8080` | 访问 Vue 管理后台 |
| Web Nginx | API 后端 | `http://api:8000/api/` | 前端 `/api/` 请求反向代理到 FastAPI |
| 浏览器/调试工具 | API 后端 | `http://服务器IP:8000/docs` | Swagger API 调试 |
| API 后端 | MySQL | `mysql:3306` | 业务数据存储 |
| API 后端 | Redis | `redis:6379` | 缓存、Token、任务状态 |
| Celery Worker | Redis | `redis:6379` | Celery Broker / Result Backend |
| Celery Worker | MySQL | `mysql:3306` | 任务记录、资产信息读取 |
| Prometheus | API 后端 | `api:8000` | 指标采集，需后续暴露 metrics 接口 |
| Grafana | Prometheus | `http://prometheus:9090` | 配置 Prometheus 数据源 |

关键配置文件对应关系：

- 后端数据库/Redis 配置：`easyops_api/config.py`
- Compose 环境变量：`docker-compose.yml` 中 `api.environment` 与 `celery.environment`
- 前端生产代理：`easyops_web/nginx.conf`，默认将 `/api/` 转发到 `http://api:8000/api/`
- 前端开发代理：`easyops_web/vite.config.mjs`，本地开发时代理到 `http://localhost:8000`
- Prometheus 采集配置：`prometheus.yml`

## 4. 安装 Docker 与 Compose

### 4.1 Ubuntu / Debian

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg git
curl -fsSL https://get.docker.com | sudo bash
sudo systemctl enable --now docker
docker version
docker compose version
```

### 4.2 CentOS / Rocky / AlmaLinux

```bash
sudo yum install -y yum-utils git curl
curl -fsSL https://get.docker.com | sudo bash
sudo systemctl enable --now docker
docker version
docker compose version
```

如果当前用户不是 root，可加入 docker 组：

```bash
sudo usermod -aG docker $USER
newgrp docker
```

## 4.3 配置 Docker 国内镜像源

如果服务器在国内环境，直接拉取 Docker Hub 镜像可能较慢或失败，建议配置 Docker Registry Mirror。

### 4.3.1 创建 Docker daemon 配置

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json <<'EOF'
{
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://docker.m.daocloud.io",
    "https://dockerproxy.com",
    "https://mirror.baidubce.com"
  ],
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",
    "max-file": "3"
  }
}
EOF
```

说明：

- `registry-mirrors`：Docker Hub 国内加速地址，可根据企业网络情况保留可用项。
- `log-driver` / `log-opts`：限制容器日志大小，避免长期运行后撑满磁盘。

如果你的公司或云厂商提供了专属镜像加速地址，建议优先使用公司/云厂商地址，例如：

```json
{
  "registry-mirrors": [
    "https://你的专属加速地址.mirror.aliyuncs.com"
  ]
}
```

常见云厂商镜像加速：

- 阿里云：容器镜像服务 ACR 控制台获取专属加速地址
- 腾讯云：容器镜像服务 TCR / CODING 制品库
- 华为云：SWR 容器镜像服务
- DaoCloud：公开镜像代理

### 4.3.2 重启 Docker

```bash
sudo systemctl daemon-reload
sudo systemctl restart docker
sudo systemctl status docker --no-pager
```

### 4.3.3 验证镜像源是否生效

```bash
docker info | grep -A 10 "Registry Mirrors"
```

测试拉取镜像：

```bash
docker pull docker.m.daocloud.io/library/nginx:1.25-alpine
docker pull docker.m.daocloud.io/library/mysql:5.7
docker pull docker.m.daocloud.io/library/redis:6
```

如果能正常拉取，说明镜像加速配置已生效。

### 4.3.4 Docker Compose 中的镜像说明

当前 `docker-compose.yml` 已默认使用 DaoCloud 国内代理镜像：

```yaml
docker.m.daocloud.io/library/mysql:5.7
docker.m.daocloud.io/library/redis:6
docker.m.daocloud.io/prom/prometheus:latest
docker.m.daocloud.io/grafana/grafana:latest
```

这些镜像地址已经写入项目配置，不依赖 Docker 默认镜像名解析。即使 Docker Hub 访问不稳定，也可以直接通过 DaoCloud 代理拉取。

如果你的网络无法访问 DaoCloud 代理，建议将镜像同步到企业私有仓库，然后修改 `docker-compose.yml`，例如：

```yaml
services:
  mysql:
    image: registry.example.com/base/mysql:5.7
  redis:
    image: registry.example.com/base/redis:6
  prometheus:
    image: registry.example.com/base/prometheus:latest
  grafana:
    image: registry.example.com/base/grafana:latest
```

同步示例：

```bash
docker pull docker.m.daocloud.io/library/mysql:5.7
docker tag docker.m.daocloud.io/library/mysql:5.7 registry.example.com/base/mysql:5.7
docker push registry.example.com/base/mysql:5.7
```

## 4.4 国产化 / 内网环境补充建议

在信创、政企内网或离线环境中，建议：

1. 在有公网的机器上提前拉取所有基础镜像。
2. 使用 `docker save` 导出镜像包。
3. 拷贝到内网服务器后使用 `docker load` 导入。
4. 再执行 `docker compose up -d --build`。

导出镜像：

```bash
docker pull docker.m.daocloud.io/library/mysql:5.7
docker pull docker.m.daocloud.io/library/redis:6
docker pull docker.m.daocloud.io/prom/prometheus:latest
docker pull docker.m.daocloud.io/grafana/grafana:latest
docker pull docker.m.daocloud.io/library/python:3.10-slim
docker pull docker.m.daocloud.io/library/node:20-alpine
docker pull docker.m.daocloud.io/library/nginx:1.25-alpine

docker save -o easyops-base-images.tar \
  docker.m.daocloud.io/library/mysql:5.7 \
  docker.m.daocloud.io/library/redis:6 \
  docker.m.daocloud.io/prom/prometheus:latest \
  docker.m.daocloud.io/grafana/grafana:latest \
  docker.m.daocloud.io/library/python:3.10-slim \
  docker.m.daocloud.io/library/node:20-alpine \
  docker.m.daocloud.io/library/nginx:1.25-alpine
```

导入镜像：

```bash
docker load -i easyops-base-images.tar
```

## 4.5 本项目已替换的国内镜像清单

项目已经将 Docker Compose 与 Dockerfile 中所有直接依赖 Docker Hub 的基础镜像改为 DaoCloud 国内代理地址：

| 用途 | 原镜像 | 当前国内镜像 |
| --- | --- | --- |
| MySQL | `mysql:5.7` | `docker.m.daocloud.io/library/mysql:5.7` |
| Redis | `redis:6` | `docker.m.daocloud.io/library/redis:6` |
| 后端 Python 基础镜像 | `python:3.10-slim` | `docker.m.daocloud.io/library/python:3.10-slim` |
| 前端 Node 构建镜像 | `node:20-alpine` | `docker.m.daocloud.io/library/node:20-alpine` |
| 前端 Nginx 运行镜像 | `nginx:1.25-alpine` | `docker.m.daocloud.io/library/nginx:1.25-alpine` |
| Prometheus | `prom/prometheus` | `docker.m.daocloud.io/prom/prometheus:latest` |
| Grafana | `grafana/grafana` | `docker.m.daocloud.io/grafana/grafana:latest` |

同时构建阶段也使用国内依赖源：

- Python 依赖：清华 PyPI 镜像 `https://pypi.tuna.tsinghua.edu.cn/simple`
- Node 依赖：npmmirror `https://registry.npmmirror.com`

你可以提前验证所有镜像是否可拉取：

```bash
docker pull docker.m.daocloud.io/library/mysql:5.7
docker pull docker.m.daocloud.io/library/redis:6
docker pull docker.m.daocloud.io/library/python:3.10-slim
docker pull docker.m.daocloud.io/library/node:20-alpine
docker pull docker.m.daocloud.io/library/nginx:1.25-alpine
docker pull docker.m.daocloud.io/prom/prometheus:latest
docker pull docker.m.daocloud.io/grafana/grafana:latest
```

如果某个代理源临时不可用，可将 `docker.m.daocloud.io` 替换为企业内部镜像仓库或其他可用代理仓库，例如：

```yaml
image: registry.example.com/library/mysql:5.7
```

## 5. 获取项目代码

```bash
git clone <你的仓库地址> easyops
cd easyops
```

如果是直接上传压缩包：

```bash
unzip easyops.zip -d easyops
cd easyops
```

确认关键文件存在：

```bash
ls
# docker-compose.yml  easyops_api  easyops_web  prometheus.yml  docs  k8s
```

## 6. 配置环境变量

从 E1 起，敏感配置全部通过环境变量注入（Compose 自动读取项目根目录 `.env`）。
首先复制示例并按需修改：

```bash
cp .env.example .env
```

**必填 / 高危项（`APP_ENV=production` 时应用会拒绝使用默认值启动）：**

| 变量 | 说明 | 生成建议 |
| --- | --- | --- |
| `APP_ENV` | `development` / `production` | 真实环境必须 `production` |
| `SECRET_KEY` | JWT 签名密钥 | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `CREDENTIAL_ENCRYPTION_KEY` | SSH 账密/私钥加密主密钥，丢失后已加密数据无法还原 | 同上 |
| `MYSQL_PASSWORD` | 数据库密码 | 强随机；与 Compose 的 `MYSQL_ROOT_PASSWORD` 一致 |
| `INITIAL_ADMIN_PASSWORD` | `init-admin` 一次性初始密码 | 强随机 |
| `CORS_ORIGINS` | 允许的来源，逗号分隔 | `http://你的前端域名` |
| `SSH_ALLOW_UNVERIFIED_HOST_KEY` | 是否允许连接未登记指纹的主机 | 生产保持 `false` |

> 密文版本前缀：SSH 凭据加密为 `v1:<token>`。更换 `CREDENTIAL_ENCRYPTION_KEY`
> 会使所有已加密凭据无法解密，请妥善备份该值。

### 6.1 当前默认连接配置

当前项目默认配置如下：

| 配置项 | 默认值 | 来源 | 说明 |
| --- | --- | --- | --- |
| MySQL Host | `mysql` | `docker-compose.yml` | Compose 内部服务名 |
| MySQL Port | `3306` | `easyops_api/config.py` | 容器内访问端口 |
| MySQL User | `root` | `easyops_api/config.py` | 默认 root 用户 |
| MySQL Password | `root123456` | `docker-compose.yml` / `config.py` | 生产必须修改 |
| MySQL DB | `easyops` | `docker-compose.yml` / `config.py` | 业务库 |
| Redis Host | `redis` | `docker-compose.yml` | Compose 内部服务名 |
| Redis Port | `6379` | `easyops_api/config.py` | Broker / 缓存 |
| Celery Broker | `redis://redis:6379/0` | `config.py` 自动生成 | 异步任务队列 |
| Celery Backend | `redis://redis:6379/0` | `config.py` 自动生成 | 任务结果存储 |
| Web -> API | `/api/` -> `http://api:8000/api/` | `easyops_web/nginx.conf` | 前端生产反向代理 |

### 6.2 前后端访问路径说明

生产部署时，浏览器访问前端：

```text
浏览器 -> http://服务器IP:8080 -> web(Nginx) -> /api/ -> api:8000
```

因此前端页面中请求 `/api/v1/...` 即可，不需要在浏览器侧直接访问 `api:8000`。`api` 是 Docker 内部服务名，只能在容器网络中解析。

本地开发时，`easyops_web/vite.config.mjs` 会把 `/api` 代理到：

```text
http://localhost:8000
```

所以开发模式需要先启动后端 API，再启动前端 Vite。

## 7. 一键启动

在项目根目录执行：

```bash
docker compose up -d --build
```

建议首次启动按以下步骤执行，便于排查镜像、构建和连接问题：

```bash
# 1. 进入项目目录
cd easyops

# 2. 可选：提前拉取国内代理镜像
docker compose pull mysql redis prometheus grafana

# 3. 构建后端和前端镜像
docker compose build api celery web

# 4. 启动基础服务
docker compose up -d mysql redis

# 5. 等待 MySQL 初始化 20-60 秒后启动应用服务
docker compose up -d api celery web prometheus grafana
```

查看容器状态：

```bash
docker compose ps
```

查看日志：

```bash
docker compose logs -f api
docker compose logs -f celery
docker compose logs -f web
docker compose logs -f mysql
```

检查服务是否启动成功：

```bash
curl http://127.0.0.1:8080
curl http://127.0.0.1:8000/docs
curl http://127.0.0.1:9090/-/healthy
```

## 8. 访问系统

默认访问地址：

- Web 管理后台：http://服务器IP:8080
- API Swagger：http://服务器IP:8000/docs
- Prometheus：http://服务器IP:9090
- Grafana：http://服务器IP:3000

默认内部连接信息：

- Web 容器名/服务名：`web`
- API 容器名/服务名：`api`
- MySQL 容器名/服务名：`mysql`
- Redis 容器名/服务名：`redis`
- Prometheus 容器名/服务名：`prometheus`
- Grafana 容器名/服务名：`grafana`

Grafana 首次登录通常为：

- 用户名：`admin`
- 密码：`admin`

登录后建议立即修改 Grafana 管理员密码，并添加 Prometheus 数据源：

```text
http://prometheus:9090
```

首次进入登录页后，点击“初始化管理员”：

- 用户名：`admin`
- 密码：`admin123`

生产环境初始化后请立刻修改管理员密码。

## 9. 日常运维命令

如需删除、卸载、完全重置测试环境或从备份还原，请优先参考：`docs/uninstall-restore.md`。

### 9.1 启动 / 停止 / 重启

```bash
docker compose up -d
docker compose stop
docker compose restart
```

### 9.2 更新代码并重新发布

```bash
git pull
docker compose up -d --build
```

### 9.3 查看资源占用

```bash
docker stats
df -h
free -h
```

### 9.4 进入容器排查

```bash
docker compose exec api bash
docker compose exec mysql mysql -uroot -proot123456 easyops
docker compose exec redis redis-cli
```

## 10. 数据备份与恢复

完整的备份、还原、卸载和测试环境重置流程请参考：`docs/uninstall-restore.md`。

### 10.1 MySQL 备份

```bash
mkdir -p backup
docker compose exec mysql sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" easyops' > backup/easyops_$(date +%F_%H%M%S).sql
```

如果容器内环境变量不可用，可使用当前 compose 中的默认密码：

```bash
docker compose exec mysql sh -c 'mysqldump -uroot -proot123456 easyops' > backup/easyops_$(date +%F_%H%M%S).sql
```

### 10.2 MySQL 恢复

```bash
cat backup/easyops_xxx.sql | docker compose exec -T mysql mysql -uroot -proot123456 easyops
```

### 10.3 Volume 备份

查看数据卷：

```bash
docker volume ls | grep easyops
```

生产建议将 MySQL、Redis、Grafana 改成宿主机目录挂载，例如：

```yaml
volumes:
  - /data/easyops/mysql:/var/lib/mysql
  - /data/easyops/redis:/data
  - /data/easyops/grafana:/var/lib/grafana
```

这样可直接通过企业备份系统备份 `/data/easyops`。

## 11. 被管服务器接入要求

要让 EasyOps 管理 Linux 服务器，需要满足：

1. 被管服务器开启 SSH 服务。
2. 平台服务器能访问被管服务器 SSH 端口。
3. 提供可执行运维命令的账号，例如 `root` 或具备 sudo 权限的普通账号。
4. 如果使用密钥登录，需要将私钥录入资产信息或后续扩展密钥托管。
5. 被管机建议安装基础命令：`bash`、`df`、`free`、`top`、`systemctl`、`tar`、`rsync`。

连通性测试：

```bash
ssh -p 22 root@被管服务器IP "hostname && uptime"
```

## 12. 安全加固建议

生产环境必须关注以下事项：

- 修改默认管理员密码。
- 修改 MySQL、Redis、JWT Secret 等默认密钥。
- 不要将 MySQL、Redis 暴露到公网。
- 使用 HTTPS 反向代理访问前端。
- 平台入口仅允许办公网、VPN 或堡垒机访问。
- 批量命令执行建议增加审批、命令黑名单、操作审计。
- 资产密码/私钥建议后续接入 Vault 或 KMS，不建议长期明文保存。
- 定期备份 MySQL 数据。
- 国内镜像代理属于第三方服务，生产环境建议将基础镜像同步到企业私有镜像仓库，并固定镜像版本或 digest。
- 不建议在公网开放 `3306`、`6379`，如必须开放需限制来源 IP 并设置强密码。
- `docker-compose.yml` 中的默认密码仅用于演示，生产环境必须改为 `.env` 或 Secret 管理。
- 构建镜像时会访问 PyPI/npm 国内源，离线环境需要提前准备 Python wheels 与 npm 缓存或私有制品库。

## 13. 常见问题

### 13.1 docker compose 命令不存在

说明 Docker Compose v2 未安装，检查：

```bash
docker compose version
```

如果只有 `docker-compose`，可临时使用：

```bash
docker-compose up -d --build
```

### 13.2 前端打不开

检查：

```bash
docker compose ps web
docker compose logs web
curl http://127.0.0.1:8080
```

同时确认云服务器安全组 / Linux 防火墙放通 `8080`。

### 13.3 API 无法连接数据库

检查 MySQL 是否健康：

```bash
docker compose ps mysql
docker compose logs mysql
docker compose logs api
```

首次启动 MySQL 初始化较慢，可等待几十秒后重启 API：

```bash
docker compose restart api celery
```

### 13.4 批量命令执行失败

检查：

- 资产 IP、SSH 端口、用户名、密码是否正确
- EasyOps 服务器是否能访问被管机 SSH 端口
- 被管机防火墙或安全组是否阻断
- Celery 是否正常运行

```bash
docker compose logs celery
ssh -p 22 user@被管服务器IP
```

### 13.5 前端镜像构建时报 vite Permission denied

如果构建 `web` 镜像时出现类似错误：

```text
sh: vite: Permission denied
```

通常是宿主机已有的 `easyops_web/node_modules` 被复制进 Docker 构建上下文，导致容器内二进制权限异常。当前项目已提供 `easyops_web/.dockerignore` 排除 `node_modules`、`dist` 和 `.vite`，并在 Dockerfile 中修复 `node_modules/.bin` 执行权限。

如仍遇到该问题，可清理宿主机前端依赖目录后重新构建：

```bash
rm -rf easyops_web/node_modules easyops_web/dist easyops_web/.vite
docker compose build --no-cache web
docker compose up -d web
```

Rocky Linux 测试服务器正在运行环境的在线修改步骤，可参考：`docs/rocky-live-fix.md`。仓库同时提供了可直接执行的脚本：

```bash
bash scripts/rocky_apply_web_build_fix.sh
```

### 13.6 如何删除、卸载或重置测试环境

如果只是临时停止服务：

```bash
docker compose stop
```

如果删除容器但保留 MySQL/Redis/Grafana 数据：

```bash
docker compose down
```

如果是测试环境，需要完全重置数据卷：

```bash
docker compose down -v
rm -rf easyops_web/node_modules easyops_web/dist easyops_web/.vite
docker compose up -d --build
```

完整删除、卸载、还原、测试环境命令和同步归档流程请参考：`docs/uninstall-restore.md`。

## 14. Kubernetes 部署说明

如果使用 K8s：

1. 先构建并推送镜像：

```bash
docker build -t registry.example.com/easyops-api:latest ./easyops_api
docker push registry.example.com/easyops-api:latest
```

2. 修改 `k8s/easyops-api.yaml` 中镜像地址与 ConfigMap。

3. 应用 YAML：

```bash
kubectl apply -f k8s/easyops-api.yaml
```

生产 K8s 环境还需要额外部署或对接：

- MySQL / Redis
- Web 前端 Deployment + Service + Ingress
- Celery Worker Deployment
- Secret / ConfigMap
- PVC 持久化存储
- Ingress HTTPS 证书









