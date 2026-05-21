# EasyOps Rocky Linux 测试服务器在线修改方案

本文档用于指导在 **Rocky Linux 测试服务器** 上，对正在运行的 EasyOps 环境进行在线修改，重点修复前端 Docker 镜像构建阶段出现的：

```text
sh: vite: Permission denied
```

## 1. 修改目标

- 修复 `easyops_web/Dockerfile` 中前端依赖二进制权限问题。
- 新增 `easyops_web/.dockerignore`，防止宿主机 `node_modules`、`dist`、`.vite` 被复制进镜像构建上下文。
- 在测试服务器上只重建并重启 `web` 服务，尽量不影响 `mysql`、`redis`、`api`、`celery`、`prometheus`、`grafana`。
- 将本次修复同步到源码仓库与 `generate_easyops.py`，避免后续重新生成项目时丢失修复。

## 2. 适用环境

- Rocky Linux 8 / 9
- Docker Engine 20.10+
- Docker Compose v2，即支持 `docker compose`
- EasyOps 使用项目根目录下的 `docker-compose.yml` 运行

检查命令：

```bash
cat /etc/rocky-release
docker version
docker compose version
```

## 3. 本次源码修改内容

### 3.1 `easyops_web/Dockerfile`

当前应为：

```Dockerfile
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
```

关键点：

- `COPY package*.json ./`：兼容未来出现 `package-lock.json` 的场景。
- `chmod -R +x node_modules/.bin`：确保 Vite 等 npm bin 文件在 Alpine 容器内可执行。

### 3.2 `easyops_web/.dockerignore`

当前应为：

```dockerignore
node_modules
dist
.vite
npm-debug.log*
yarn-debug.log*
yarn-error.log*
.DS_Store
```

关键点：避免宿主机的 `node_modules` 被 `COPY . .` 带入镜像。

### 3.3 `generate_easyops.py`

生成脚本已经同步以上两项修改，后续重新执行生成脚本不会覆盖回旧版本。

## 4. Rocky 测试服务器推荐在线执行步骤

进入服务器上的 EasyOps 项目根目录：

```bash
cd /你的/easyops/项目目录
```

如果服务器代码来自 Git，建议先保存现场：

```bash
git status
git diff > /tmp/easyops_before_web_fix_$(date +%F_%H%M%S).patch
```

执行仓库内脚本：

```bash
bash scripts/rocky_apply_web_build_fix.sh
```

该脚本会自动完成：

1. 检查 `docker` 与 `docker compose` 是否可用。
2. 写入 `easyops_web/.dockerignore`。
3. 修改 `easyops_web/Dockerfile`。
4. 删除宿主机 `easyops_web/node_modules`、`easyops_web/dist`、`easyops_web/.vite`。
5. 执行 `docker compose build --no-cache web`。
6. 执行 `docker compose up -d web`。
7. 输出 `web` 服务状态与最近日志。

## 5. 手工执行方案

如果不想执行脚本，也可以手工执行：

```bash
cd /你的/easyops/项目目录

cat > easyops_web/.dockerignore <<'EOF'
node_modules
dist
.vite
npm-debug.log*
yarn-debug.log*
yarn-error.log*
.DS_Store
EOF

sed -i 's/COPY package\.json \\.\//COPY package*.json .\//g' easyops_web/Dockerfile
sed -i 's/RUN npm run build/RUN chmod -R +x node_modules\/\.bin \&\& npm run build/g' easyops_web/Dockerfile

rm -rf easyops_web/node_modules easyops_web/dist easyops_web/.vite
docker compose build --no-cache web
docker compose up -d web
docker compose ps web
docker compose logs --tail=80 web
```

## 6. 验证方式

### 6.1 检查容器状态

```bash
docker compose ps
docker compose logs --tail=100 web
```

期望：

- `web` 状态为 `Up`。
- 日志中没有 `vite: Permission denied`。

### 6.2 检查前端访问

在服务器本机执行：

```bash
curl -I http://127.0.0.1:8080
```

期望返回 `HTTP/1.1 200 OK` 或 Nginx 正常响应。

浏览器访问：

```text
http://测试服务器IP:8080
```

### 6.3 检查 API 反向代理

```bash
curl http://127.0.0.1:8000/docs
```

如果前端页面可打开但接口失败，再检查：

```bash
docker compose ps api
docker compose logs --tail=100 api
docker compose exec web nginx -T | grep -A 5 'location /api/'
```

## 7. 回滚方案

如果本次修改导致前端服务异常，可按以下方式回滚。

### 7.1 Git 回滚

如果服务器代码由 Git 管理：

```bash
git checkout -- easyops_web/Dockerfile easyops_web/.dockerignore
docker compose build --no-cache web
docker compose up -d web
```

### 7.2 使用补丁回滚

如果执行前已保存 patch：

```bash
git apply -R /tmp/easyops_before_web_fix_*.patch
docker compose build --no-cache web
docker compose up -d web
```

## 8. 注意事项

- 本次方案只重建 `web` 服务，不会主动重启数据库、Redis、API 或 Celery。
- `--no-cache` 会让前端镜像完整重建，首次耗时取决于 Rocky 服务器访问 npm 镜像源的速度。
- 如果 Rocky 服务器无法访问 `registry.npmmirror.com`，需要改为企业 npm 私服或提前准备 npm 缓存。
- 如果无法访问 `docker.m.daocloud.io`，需要把 Node/Nginx 基础镜像同步到企业私有镜像仓库，并修改 `easyops_web/Dockerfile`。