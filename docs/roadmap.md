# EasyOps 路线图

> 目标：把当前「运维平台功能骨架」建设成能证明 Linux 系统运维、自动化任务、安全控制、
> 监控告警和恢复能力的作品项目。重点是可运行、可验证、可解释，不追求功能数量。
> 本文件同步自项目方案；每阶段完成时勾选并附证据链接。

## 阶段总览

| 阶段 | 主题 | 状态 |
|---|---|---|
| E0 | 基线与开发规范 | ✅ 已完成（本文档 + CHANGELOG + 分支约定已建立） |
| E1 | 安全与配置基线（P0） | ✅ 已完成（PR #1） |
| E2 | 测试与运行基线（P0） | ✅ 已完成（PR #2） |
| E3 | 受控批量运维（P0） | ✅ 已完成（本分支 PR） |
| E4 | Linux 主机巡检与监控（P1） | ✅ 已完成（本分支 PR，真实 VM 演练待 E6 前补） |
| E5 | 部署、备份与恢复（P1） | ✅ 已完成（本分支 PR，真实演练待 E6 前补） |
| E6 | 交付与展示（P1） | ⏳ 待开始 |

## E1 安全与配置基线（目标 2–4 天）

### 配置与 Secret

- [x] 增加 `.env.example`，只提供字段名和开发示例，不保存真实凭据
- [x] `SECRET_KEY`、MySQL 密码、管理员初始化密码改为环境变量
- [x] 非开发环境缺少关键 Secret 时启动失败（`config.validate_settings`）
- [x] CORS 改为明确 allowlist，禁止 `*` 与凭据模式组合
- [x] MySQL、Redis 默认只在 Compose 内部网络开放，宿主机端口通过可选
      `docker-compose.ports.yml` 覆盖文件启用

### 身份与权限

- [x] 全部业务路由统一要求登录（未登录 401）
- [x] 最小角色：`admin`（系统管理员）、`operator`、`viewer`
- [x] 写操作要求 admin/operator，用户管理仅 admin
- [x] `init-admin` 一次性 bootstrap，重复调用 409
- [x] 禁用用户不能继续使用旧 Token
- [x] 登录失败、权限拒绝和敏感操作写入 `audit_log`

### SSH 凭据与主机信任

- [x] SSH 密码 / 私钥加密后存储，API 只返回 `has_password` / `has_private_key`
- [x] 加密密钥从环境变量注入，密文带 `v1:` 版本前缀
- [x] 默认拒绝未知 host key，资产支持显式保存指纹并按指纹严格校验
- [x] 日志和异常统一脱敏主机密码、私钥、Token、数据库 URL

### 验收门禁

- [x] 未登录访问所有业务接口返回 401（pytest 覆盖）
- [x] viewer 写操作返回 403（pytest 覆盖）
- [x] API 响应、日志和任务参数扫描不到明文凭据（pytest 覆盖）
- [x] 非开发环境使用默认 Secret 时启动失败（pytest 覆盖）
- [x] 未登记 host key 的 SSH 目标被拒绝（pytest 覆盖）

## E2 测试与运行基线（已完成）

- [x] 后端 pytest 覆盖登录、bootstrap、角色权限、资产 CRUD、批量任务、告警、Cron、
      部署（`tests/`，共 65 项通过）
- [x] 批量执行边界：空资产 / 超 50 台 / 资产缺失 400、重复请求各自成记录、
      单主机失败隔离（`tests/test_exec.py`）
- [x] 错误响应：404 / 400 / 409 / 422 全覆盖（`tests/test_crud.py`）
- [x] 核心安全模块覆盖率 >= 80%（实测 91%：`common` / `config` / `dependencies` /
      `services.ssh_service`）
- [x] 全局覆盖率初始门禁 >= 50%（实测 88%）
- [x] Alembic 替代启动时 `create_all`（`alembic/0001_initial_schema`，Compose 启动前
      执行 `alembic upgrade head`）
- [x] CI：Ruff、pytest、coverage（全局 + 安全模块）、`pip-audit` 依赖审计、
      Alembic SQLite 迁移校验、kubeconform K8s 清单校验、README/docs 链接检查全绿
- [x] 依赖审计修复：fastapi/starlette/instrumentator/python-multipart/requests/
      python-jose→PyJWT/paramiko/pytest 升级，`pip-audit` 与 `npm audit` 均 0 漏洞

实施细节见 `docs/changes/2026-08-14-e2-test-health.md`。

## E3 受控批量运维（已完成）

> 目标：把「接受任意命令的单输入批量执行」改造成「固定操作目录 + preview 确认 + 幂等 +
> 有界并发 + 逐主机状态 + 审计」的受控链路。实施细节见
> `docs/changes/2026-08-14-e3-controlled-batch-exec.md`。

- [x] 固定操作目录（磁盘/内存/服务状态/重启/日志/端口），参数白名单 +
      `shlex.quote` 双重防注入（`services/operations.py`）
- [x] `break_glass` 任意命令默认关闭，仅 admin 可启用（启用需理由，写审计）
- [x] preview 返回确认令牌，写操作必须持令牌提交；幂等键去重
- [x] 单任务资产上限 50、Worker 并发上限 8、单主机硬超时 90s（软 75s）
- [x] 逐主机状态 queued/running/succeeded/failed/timed_out，失败隔离 + 失败重试
- [x] 前端 4 步向导：选资产 → 选操作/参数 → 预览确认 → 逐主机结果轮询
- [x] Alembic `0002` 迁移（SQLite batch 重建 + MySQL ALTER），含往返测试
- [x] 全量 pytest 77 项通过；覆盖率全局 85% / 安全模块 91%；pip-audit、npm audit 0 漏洞

## E4 主机巡检与监控（已完成）

> 目标：为主机健康提供可解释的事实与规则判定，补齐 Prometheus/Grafana 可观测与告警。
> 实施细节见 `docs/changes/2026-08-15-e4-host-inspection.md`。
> 说明：本阶段验收为 mock/单测 + 静态/构建证据；真实 ≥2 台 Linux VM 复现正常/异常、
> Prometheus 真实指标与 Grafana 截图，按环境实验规范在 E6 交付前补做并归档。

- [x] 主机事实采集（SSH 只读多探测）：OS/内核/uptime/主机名、CPU/load、
      内存/swap、磁盘容量+inode+高占用目录、端口监听/关键进程/systemd 服务，
      结果带 `observed_at`/来源/超时/不可用原因（`services/host_inspection.py`）
- [x] 巡检规则引擎：磁盘/inode 高水位、load 持续过高、swap 异常、关键服务停止、
      端口未监听；结果 healthy/warning/critical/unknown，缺数据固定 unknown
      （`services/inspection_rules.py`）
- [x] 巡检 API + Celery Worker + Alembic `0003` 迁移（`inspection_record` /
      `host_inspection` / `inspection_rule`），规则 CRUD 与默认种子
- [x] API/Worker 自定义指标：请求量/延迟/队列/成功率/失败率/执行时长
      （`services/metrics.py` + `tasks/metrics_tasks.py`）
- [x] Grafana dashboard（`grafana/easyops-overview.json`，provisioning 自动注册）+
      Prometheus 告警规则（`prometheus-alerts.yml`：API 不可用/队列积压/
      失败率/DB 连接/critical 主机）
- [x] 前端 `HostInspection.vue`：巡检采集（记录列表/逐主机详情，采集时间必显）+
      规则管理
- [x] 全量 pytest 100 项通过（新增 23）；覆盖率全局 86% / 安全模块 91%；
      Ruff、pip-audit、npm audit、compose config、前端生产构建全绿

## E5 部署、备份与恢复（已完成）

> 目标：把占位「部署/备份」改造成受控、可回滚、可恢复且带证据的链路。实施细节见
> `docs/changes/2026-08-15-e5-deploy-backup.md`。
> 说明：本阶段验收为 mock/单测 + 静态/构建证据；真实「部署→健康验证→回滚」与
> 「备份→删除测试数据→全新恢复→一致性检查」演练在本地 docker compose 环境可行，
> 归 E6 交付前补做并归档。

- [x] 受控部署计划：预览计划（pull/build/up/healthcheck 固定步骤）+ 步骤白名单
      （非法步骤立即中止）+ 回滚到最近有效发布（`services/deploy_service.py` +
      `deploy_templates/compose-web/`）
- [x] 不执行项目仓库任意脚本：构建/部署仅走模板目录固定步骤
      （`DeployProject.build_script/deploy_script` 仅保留为记录字段）
- [x] 发布记录（`DeployRelease`）：release_type/status/image/version/image_digest/
      执行人/结果 JSON；Alembic `0004` 迁移
- [x] MySQL 逻辑备份与校验：engine.dump → gzip/sha256/一致性检查 → checksum_ok
      （`services/backup_service.py` + `BackupRecord`）
- [x] 恢复：仅从校验通过的备份恢复 → 表级一致性校验（validation JSON）
- [x] 保留策略：失败备份不覆盖最后一份有效备份
- [x] 前端：`DeployProject.vue` 受控计划（预览/发布/回滚/发布记录）+
      `BackupRestore.vue`（备份/恢复/校验详情，路由 `/backup`）
- [x] 全量 pytest 121 项通过（新增 21）；覆盖率全局 86% / 安全模块 91% / E5 模块 83%；
      Ruff、pip-audit、npm audit、compose config、前端生产构建全绿

## E6 交付与展示（待开始）

- [ ] 真实 Linux 全新部署 + 演示脚本 + README 截图
- [ ] 发布 v0.1.0（Release Notes、兼容范围、已知限制、升级/回滚）

## 非目标

- 不负责 Kubernetes 集群创建 / 多集群管理（归 `kubernetes-cluster-bootstrap` /
  `aiops-platform`）；EasyOps 的 K8s 清单只用于部署自身。
- 不做浏览器 WebShell 或默认开放任意命令。
- 不做完整 Jenkins / GitLab / Argo CD 替代品。

## Git 约定

- 分支：`feat/*`、`fix/*`；每阶段通过 PR 合入 `main`。
- 提交只包含当前任务文件；tag / Release / 生产部署需单独确认。
- 变更记录：改动写入 `CHANGELOG.md` 的 `Unreleased`，实施细节写入
  `docs/changes/YYYY-MM-DD-<slug>.md`。