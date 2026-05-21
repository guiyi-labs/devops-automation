# EasyOps 删除、卸载、还原与测试环境重置命令

本文档用于规范 EasyOps 在 Docker Compose / Rocky Linux 测试环境中的删除、卸载、数据还原、测试环境重置与归档同步流程。

> ⚠️ 风险提示：本文包含删除容器、删除数据卷、删除项目目录等高危命令。执行前必须确认当前环境是测试环境还是生产环境，并提前备份数据库与项目配置。

## 1. 操作分级说明

| 级别 | 操作 | 是否删除业务数据 | 适用场景 |
| --- | --- | --- | --- |
| L1 | 停止服务 | 否 | 临时停机、维护窗口 |
| L2 | 重启 / 重建服务 | 否 | 发布新版本、修复镜像 |
| L3 | 删除容器与网络 | 否，默认保留 volume | 清理运行实例，保留数据 |
| L4 | 删除容器、网络、数据卷 | 是 | 测试环境完全重置 |
| L5 | 删除项目目录和镜像 | 是，若未备份则不可恢复 | 下线环境、释放磁盘 |
| L6 | 从备份还原 | 覆盖当前数据 | 回滚或迁移恢复 |

## 2. 执行前确认

进入 EasyOps 项目根目录：

```bash
cd /你的/easyops/项目目录
```

确认当前目录：

```bash
pwd
ls
```

期望至少看到：

```text
docker-compose.yml  easyops_api  easyops_web  docs
```

确认当前运行服务：

```bash
docker compose ps
```

确认数据卷：

```bash
docker volume ls | grep easyops
```

确认磁盘占用：

```bash
du -sh .
docker system df
```

## 3. 操作前备份命令

### 3.1 备份 MySQL 数据

```bash
mkdir -p backup
docker compose exec mysql sh -c 'mysqldump -uroot -proot123456 easyops' > backup/easyops_$(date +%F_%H%M%S).sql
```

校验备份文件：

```bash
ls -lh backup/*.sql
tail -n 5 backup/easyops_*.sql
```

### 3.2 备份当前 Compose 配置和环境文件

```bash
mkdir -p backup/config_$(date +%F_%H%M%S)
cp -a docker-compose.yml prometheus.yml backup/config_$(date +%F_%H%M%S)/ 2>/dev/null || true
cp -a .env backup/config_$(date +%F_%H%M%S)/ 2>/dev/null || true
cp -a easyops_web/nginx.conf backup/config_$(date +%F_%H%M%S)/ 2>/dev/null || true
```

### 3.3 备份源码修改差异

如果项目由 Git 管理：

```bash
git status
git diff > backup/easyops_worktree_$(date +%F_%H%M%S).patch
```

## 4. L1：仅停止服务，不删除任何数据

适用于临时维护。

```bash
docker compose stop
docker compose ps
```

恢复启动：

```bash
docker compose up -d
docker compose ps
```

## 5. L2：重启或重建服务，不删除数据

### 5.1 重启全部服务

```bash
docker compose restart
docker compose ps
```

### 5.2 只重启 Web

```bash
docker compose restart web
docker compose logs --tail=80 web
```

### 5.3 只重启 API 和 Celery

```bash
docker compose restart api celery
docker compose logs --tail=80 api
docker compose logs --tail=80 celery
```

### 5.4 重新构建并启动，不删除数据库数据

```bash
docker compose up -d --build
docker compose ps
```

### 5.5 Rocky 测试服务器前端修复后重建 Web

```bash
bash scripts/rocky_apply_web_build_fix.sh
```

## 6. L3：删除容器与网络，保留数据卷

适用于清理容器运行状态，但保留 MySQL、Redis、Grafana 数据。

```bash
docker compose down
docker compose ps
docker volume ls | grep easyops
```

重新启动：

```bash
docker compose up -d --build
```

说明：

- `docker compose down` 默认不会删除 named volume。
- MySQL 数据卷 `mysql_data` 会保留。
- Redis 数据卷 `redis_data` 会保留。
- Grafana 数据卷 `grafana_data` 会保留。

## 7. L4：测试环境完全重置，删除数据卷

> ⚠️ 该操作会删除 MySQL、Redis、Grafana 的 Docker Volume，业务数据会丢失。仅建议在测试环境执行。

### 7.1 推荐测试环境重置流程

```bash
cd /你的/easyops/项目目录

# 1. 可选：先备份
mkdir -p backup
docker compose exec mysql sh -c 'mysqldump -uroot -proot123456 easyops' > backup/easyops_before_reset_$(date +%F_%H%M%S).sql || true

# 2. 停止并删除容器、网络、数据卷
docker compose down -v

# 3. 清理前端宿主机构建产物
rm -rf easyops_web/node_modules easyops_web/dist easyops_web/.vite

# 4. 重新构建并启动
docker compose up -d --build

# 5. 查看状态
docker compose ps
docker compose logs --tail=100 api
```

### 7.2 一行测试环境重置命令

确认是测试环境后，可以执行：

```bash
docker compose down -v && rm -rf easyops_web/node_modules easyops_web/dist easyops_web/.vite && docker compose up -d --build
```

## 8. L5：完全卸载 EasyOps 项目

> ⚠️ 该操作会删除容器、数据卷、构建镜像和项目目录。执行前请务必备份。

### 8.1 停止并删除 Compose 资源

```bash
cd /你的/easyops/项目目录
docker compose down -v --remove-orphans
```

### 8.2 删除 EasyOps 相关镜像

查看镜像：

```bash
docker images | grep -i easyops
```

删除镜像示例：

```bash
docker images | grep -i easyops | awk '{print $3}' | xargs -r docker rmi -f
```

如果镜像名不是 easyops，可通过 compose 项目名查看：

```bash
docker images | grep -E 'easyops|vs_devops'
```

### 8.3 删除悬空镜像和构建缓存

```bash
docker image prune -f
docker builder prune -f
```

如需清理所有未使用资源：

```bash
docker system prune -f
```

> 不建议在生产服务器随意执行 `docker system prune -a`，它可能删除其他项目尚未运行但需要保留的镜像。

### 8.4 删除项目目录

```bash
cd /你的/项目上级目录
rm -rf easyops
```

## 9. 从备份还原 MySQL 数据

### 9.1 启动基础服务

```bash
docker compose up -d mysql redis
docker compose ps
```

等待 MySQL 初始化完成：

```bash
docker compose logs -f mysql
```

看到 `ready for connections` 后继续。

### 9.2 导入 SQL 备份

```bash
cat backup/easyops_你的备份文件.sql | docker compose exec -T mysql mysql -uroot -proot123456 easyops
```

### 9.3 启动应用服务

```bash
docker compose up -d api celery web prometheus grafana
docker compose ps
```

### 9.4 验证还原结果

```bash
docker compose exec mysql mysql -uroot -proot123456 easyops -e "show tables;"
curl http://127.0.0.1:8000/docs
curl -I http://127.0.0.1:8080
```

## 10. 测试环境常用命令

### 10.1 测试环境首次部署

```bash
cd /你的/easyops/项目目录
docker compose pull mysql redis prometheus grafana
docker compose up -d --build
docker compose ps
```

### 10.2 测试环境更新代码后发布

```bash
git pull
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 api
docker compose logs --tail=100 web
```

### 10.3 测试环境快速重置所有数据

```bash
docker compose down -v
rm -rf easyops_web/node_modules easyops_web/dist easyops_web/.vite
docker compose up -d --build
```

### 10.4 测试环境只重建前端

```bash
rm -rf easyops_web/node_modules easyops_web/dist easyops_web/.vite
docker compose build --no-cache web
docker compose up -d web
docker compose logs --tail=80 web
```

### 10.5 测试环境只重建后端

```bash
docker compose build --no-cache api celery
docker compose up -d api celery
docker compose logs --tail=100 api
docker compose logs --tail=100 celery
```

### 10.6 测试环境查看访问入口

```bash
curl -I http://127.0.0.1:8080
curl http://127.0.0.1:8000/docs
curl http://127.0.0.1:9090/-/healthy
```

## 11. Rocky Linux 测试服务器卸载命令

### 11.1 保留数据的卸载

```bash
cd /你的/easyops/项目目录
docker compose down
```

### 11.2 删除数据的测试环境卸载

```bash
cd /你的/easyops/项目目录
docker compose down -v --remove-orphans
rm -rf easyops_web/node_modules easyops_web/dist easyops_web/.vite
```

### 11.3 完全删除项目

```bash
cd /你的/项目上级目录
rm -rf easyops
```

## 12. 同步归档流程

每次完成修复、部署、卸载、还原文档更新后，建议同步归档当前版本。

### 12.1 查看修改内容

```bash
git status
git diff -- docs/ docker-compose.yml easyops_api easyops_web scripts
```

### 12.2 创建归档目录

```bash
mkdir -p archive/$(date +%F_%H%M%S)
```

### 12.3 归档关键文档和配置

```bash
ARCHIVE_DIR=archive/$(date +%F_%H%M%S)
mkdir -p "$ARCHIVE_DIR"

cp -a docs "$ARCHIVE_DIR/"
cp -a docker-compose.yml prometheus.yml "$ARCHIVE_DIR/" 2>/dev/null || true
cp -a scripts "$ARCHIVE_DIR/" 2>/dev/null || true
cp -a easyops_web/Dockerfile easyops_web/.dockerignore easyops_web/nginx.conf "$ARCHIVE_DIR/" 2>/dev/null || true
cp -a easyops_api/Dockerfile easyops_api/requirements.txt "$ARCHIVE_DIR/" 2>/dev/null || true

git status > "$ARCHIVE_DIR/git-status.txt" 2>/dev/null || true
git diff > "$ARCHIVE_DIR/worktree.diff" 2>/dev/null || true
```

### 12.4 打包归档

```bash
tar -czf easyops_archive_$(date +%F_%H%M%S).tar.gz archive
```

### 12.5 Git 提交归档变更

```bash
git add docs scripts easyops_web/Dockerfile easyops_web/.dockerignore generate_easyops.py
git commit -m "docs: add uninstall restore and component connection guides"
```

如需推送远端：

```bash
git push
```

## 13. 推荐验收清单

- [ ] 已确认当前环境是测试环境还是生产环境
- [ ] 删除或重置前已备份 MySQL
- [ ] 已备份 `.env`、`docker-compose.yml`、`nginx.conf` 等关键配置
- [ ] 测试环境可执行 `docker compose down -v` 完全重置
- [ ] 生产环境只允许执行 `docker compose stop/down` 等保留数据命令
- [ ] 还原后可访问 `http://服务器IP:8080`
- [ ] 还原后可访问 `http://服务器IP:8000/docs`
- [ ] 归档目录已生成或 Git 已提交