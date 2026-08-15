# EasyOps 文档与变更归档索引

本文档用于记录当前项目文档、脚本和部署配置的归档入口，方便在测试服务器、交付包或 Git 仓库中同步维护。

## 1. 当前核心文档

| 文档 | 用途 |
| --- | --- |
| `docs/deployment.md` | Linux / Rocky / Docker Compose 部署与运维手册 |
| `docs/component-connections.md` | 各组件连接信息总表，包含地址、端口、账号、环境变量、排查命令 |
| `docs/rocky-live-fix.md` | Rocky Linux 测试服务器在线修改方案 |
| `docs/uninstall-restore.md` | 删除、卸载、还原、测试环境重置与归档同步命令 |

## 2. 当前核心脚本

| 脚本 | 用途 |
| --- | --- |
| `scripts/rocky_apply_web_build_fix.sh` | Rocky 测试服务器前端 Docker 构建权限修复脚本 |

## 2.5 阶段变更归档

| 变更文档 | 阶段 |
| --- | --- |
| `docs/changes/2026-08-14-e2-test-health.md` | E2 测试与运行基线 |
| `docs/changes/2026-08-14-e3-controlled-batch-exec.md` | E3 受控批量运维 |
| `docs/changes/2026-08-15-e4-host-inspection.md` | E4 主机巡检与监控 |

## 3. 当前关键配置

| 文件 | 用途 |
| --- | --- |
| `docker-compose.yml` | Compose 一键部署入口 |
| `prometheus.yml` | Prometheus 指标采集配置 |
| `prometheus-alerts.yml` | Prometheus 告警规则（API 不可用/队列积压/失败率/巡检） |
| `grafana/` | Grafana provisioning（datasource + dashboard JSON） |
| `easyops_web/Dockerfile` | 前端镜像构建配置 |
| `easyops_web/.dockerignore` | 前端 Docker 构建上下文排除规则 |
| `easyops_web/nginx.conf` | 前端 Nginx 反向代理配置 |
| `easyops_api/Dockerfile` | 后端镜像构建配置 |
| `generate_easyops.py` | 项目生成脚本，需同步模板修复 |

## 4. 归档建议

每次完成以下任一操作后，都建议执行一次归档：

- 修改部署文档
- 修改 Dockerfile / Compose / Nginx 配置
- 修改 Rocky 测试服务器在线修复方案
- 新增卸载、还原、重置命令
- 测试环境完成一次可复现部署

推荐归档命令见：

```bash
docs/uninstall-restore.md
```

对应章节：

```text
12. 同步归档流程
```

## 5. 当前交付检查清单

- [x] 部署手册已存在：`docs/deployment.md`
- [x] 组件连接信息已存在：`docs/component-connections.md`
- [x] Rocky 在线修复方案已存在：`docs/rocky-live-fix.md`
- [x] 删除/卸载/还原方案已存在：`docs/uninstall-restore.md`
- [x] 归档索引已存在：`docs/archive-index.md`
- [x] Rocky 修复脚本已存在：`scripts/rocky_apply_web_build_fix.sh`