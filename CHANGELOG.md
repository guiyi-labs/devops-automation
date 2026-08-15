# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循
[Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added

- 部署、备份与恢复（E5）：
  - 受控部署计划（`services/deploy_service.py` + `deploy_templates/compose-web/`）：
    预览计划（pull/build/up/healthcheck 固定步骤）、步骤白名单（非法步骤立即中止）、
    回滚到「早于当前发布」的最近有效发布；只执行模板目录固定动作，不执行项目仓库任意脚本。
  - 部署 API（`api/v1/deploy.py`）：`POST /projects/{id}/preview`、
    `POST /releases`（派发 Celery）、`GET /projects/{id}/releases`、`GET /releases/{id}`、
    `POST /releases/{id}/rollback`、`GET /templates`；E2 占位 `POST .../run` 移除。
  - 部署 Worker（`tasks/deploy_tasks.py`）：`run_deploy_release` /
    `run_rollback_release`，发布记录保存 image/version/image_digest/执行人/结果。
  - MySQL 逻辑备份恢复（`services/backup_service.py` + `tasks/backup_tasks.py`）：
    engine.dump → gzip/sha256/一致性校验；恢复仅允许校验通过的备份、带表级一致性
    validation；失败备份不覆盖最后一份有效备份（checksum_ok 才记有效）。
  - 备份 API（`api/v1/backup.py`）：`POST /create`、`POST /restore`、
    `GET /records[/{id}]`、`GET /policy`。
  - Alembic 迁移 `0004_add_deploy_backup`：`deploy_release` / `backup_record` 两表，
    SQLite 与 MySQL 均原生建表；迁移往返测试覆盖 0003→0004→downgrade。
  - 前端：`DeployProject.vue` 受控计划（预览/发布/回滚/发布记录）+
    `BackupRestore.vue`（路由 `/backup`，备份/恢复/校验详情）；`api/deploy.js` 扩展。
  - 测试：E5 新增 21 项（部署预览/发布/回滚/白名单/Worker、备份校验/恢复/保留/权限、
    迁移 0004），pytest 全量 100 → 121。
  - E5-P2 真实部署与恢复验收（`feat/e5-phase2-real-acceptance`）：
  - 受控部署执行真实化（`services/deploy_service.py` +
    `tasks/deploy_tasks.py`）：`RemoteComposeRunner` 真实 SSH 远程部署
    （host-key 校验、密钥认证、compose 文档仅由固定模板 + base64 生成，不执行项目
    任意 build_script/deploy_script）；`DeployProject.target_asset_id` 绑定目标资产
    （迁移 0006 + MySQL/SQLite 双路），`DEPLOY_EXECUTION_MODE` 控制 mock/real。
  - 备份/恢复真实化（`services/backup_service.py` + `tasks/backup_tasks.py`）：
    `RealMySQLDumpEngine` 容器内 `mysqldump --single-transaction --routines
    --triggers` → `.sql` + `.sql.gz` + `.sha256` 三件套持久化到共享卷
    `BACKUP_STORAGE_DIR`，gzip/SHA-256/一致性校验，`BACKUP_RETENTION_COUNT`
    保留策略；恢复改为**全新目标库**（DROP+CREATE easyops_restore）杜绝与运行中
    表 metadata lock 死锁；`--skip-ssl` 兼容 MySQL 8 自签名证书；api/celery 双容器
    共享 backup_data 卷；损坏/篡改备份校验层拒绝且不覆盖最后有效备份。
  - 同步巡检端点（`api/v1/inspection.py` `POST /collect/sync`）：uvicorn 进程内
    真实 SSH 巡检并记录 Prometheus 指标（`easyops_inspection_hosts_total` /
    `inspection_duration` / `easyops_host_health`），绕过 worker 进程指标不被
    scrape 局限。
  - 真实验收（两台 Ubuntu 24.04 Lima VM）：部署→healthcheck→失败发布→回滚到
    最后有效 release、MySQL 备份→gzip/SHA-256/一致性→删除测试数据→全新恢复→
    表/行/字段一致性 → 损坏备份保护；Prometheus 真实指标 / Grafana 面板配置。
  - 测试：E5-P2 新增 14 项（deploy runner 接线/迁移 0006/backup real/恢复全新库/
    参数化 SSH），pytest 全量 121 → 135。
  - 主机巡检与监控（E4）：
  - SSH 只读事实采集（`services/host_inspection.py`）：一次会话多探测（OS/内核/
    uptime/CPU/load/内存/swap/磁盘+inode/监听端口/运行服务），逐探测容错，
    `HostFacts` 固定携带 `observed_at/source/timeout_ms/unavailable_reason`；
    复用以主机密钥校验与错误分类的 `ssh_service`。
  - 规则引擎（`services/inspection_rules.py`）：`metric+operator+threshold+severity`
    判定 healthy/warning/critical/unknown，缺数据固定 unknown 不误判健康；
    内置 8 条默认规则（磁盘/inode/内存/swap/load/服务/端口），空表自动种子。
  - 巡检 API（`api/v1/inspection.py`）：`POST /collect` + 记录/逐主机查询 +
    资产最近一次巡检 + 规则 CRUD，全写操作审计。
  - Worker（`tasks/inspection_tasks.py`）：`inspect_host` 采集→评估→落库→聚合
    记录计数；已加入 `celery_app.autodiscover_tasks`。
  - Alembic 迁移 `0003_add_host_inspection`：`inspection_record` /
    `host_inspection` / `inspection_rule` 三表，SQLite 与 MySQL 均原生 ALTER 路径。
  - 自定义 Prometheus 指标（`services/metrics.py`）：执行/巡检计数与耗时、
    队列深度、最近巡检健康分布（`tasks/metrics_tasks.py` 采样队列）。
  - 告警规则（`prometheus-alerts.yml`）：API 不可用 / 队列积压 / 任务失败率 /
    critical 主机 / 巡检失败速率。
  - Grafana（`grafana/`）：provisioning 自动注册 datasource + `easyops-overview`
    dashboard（请求速率/P95 延迟/队列深度/任务成败/延迟分位/执行耗时/成功率/
    巡检健康分布），匿名只读、默认首页。
  - 前端 `HostInspection.vue`（路由 `/inspect`）：巡检采集（多选资产 → 记录列表 →
    逐主机详情，采集时间戳必显、unknown 显示原因）+ 规则管理 tab。
  - 测试：E4 新增 23 项（解析函数/规则引擎/collect API/Worker/mock SSH 采集），
    pytest 全量 77 → 100；迁移测试扩展 0003 往返与 head 对齐。
  - 受控批量运维（E3）：固定操作目录（磁盘/内存/服务状态/重启/日志/端口）与参数白名单
  + `shlex.quote` 双重防注入（`services/operations.py`）；preview 确认令牌；幂等键去重；
  单任务资产上限 50、Worker 并发上限 8、单主机硬超时 90s；逐主机执行状态
  （queued/running/succeeded/failed/timed_out）落库与失败重试；break-glass 任意命令
  默认关闭、仅 admin 启用（需理由并写审计）。
- Alembic 迁移 `0002_extend_exec_record_and_host_result`：`exec_record` 扩展 E3 字段并
  移除旧 `exec_status`，新增 `exec_host_result` 表；SQLite batch 重建（保留旧数据）、
  MySQL 原生 ALTER；`alembic/env.py` 优先读取实时 `DATABASE_URL`。
- 前端 4 步受控执行向导（`easyops_web/src/views/exec/BatchExec.vue`）：选资产 →
  选操作/参数（或 break-glass）→ 预览确认（令牌+幂等键）→ 逐主机结果轮询与重试。
- 迁移往返测试（`tests/test_migrations.py`）：0001→0002→downgrade→re-upgrade 与
  head 数据模型对齐。
- pytest 全量从 65 增至 77 项，覆盖率全局 85.49%（≥50%）、安全模块 91.09%（≥80%）。

### Changed

- E2 单文本框「任意命令」批量入口改为受控目录：写操作必须 preview 确认，
  任意命令仅在 break-glass 开启且管理员身份下可用。

- Alembic 迁移（E2）：`alembic/` 初始迁移 `0001_initial_schema`，替代启动时
  `Base.metadata.create_all`；Compose 中 api/celery 启动前执行 `alembic upgrade head`。
- pytest-cov 覆盖率门禁：全局初始 ≥ 50%，核心安全模块（`common` / `config` /
  `dependencies` / `services.ssh_service`）≥ 80%（当前 91%）。
- 更多测试（E2）：资产/告警/Cron/部署 CRUD 与 404/400/409/422 错误响应、批量执行边界
  （空资产 / 超 50 台 / 资产缺失 / 重复请求）、Worker 单主机失败隔离、SSH 成功路径 /
  私钥加载 / 远端命令失败（`RemoteCommandError`）。
- CI 门禁（E2）：`pip-audit` 依赖审计、Alembic SQLite 迁移有效性校验、kubeconform
  Kubernetes 清单 schema 检查、README/docs 相对链接检查。
- 升级运行时依赖修复已知漏洞：fastapi 0.111.0 → 0.141.1（starlette 0.37.2 → 1.6.0，
  `prometheus-fastapi-instrumentator` 7.0.0 → 8.1.0 以兼容）、python-multipart
  0.0.9 → 0.0.32、requests 2.32.3 → 2.34.2、paramiko 3.4.0 → 5.0.0（移除已废的
  DSSKey 支持）。
- JWT 实现由 `python-jose` 迁移至 `PyJWT==2.13.0`（HS256 用法一致）：消除
  python-jose 及其 `ecdsa` 传递依赖的审计告警（HSA-2024-232/233、Minerva
  侧信道无修复版）。

### Changed

- `main.py` 不再在启动时 `create_all`；表结构统一由 Alembic 管理。
- `services/ssh_service.connect_and_run`：远端命令非 0 退出改为抛
  `RemoteCommandError`（不再静默返回 status=2），失败路径更可区分。

### Security

- `pip-audit` / `npm audit --omit=dev` 均 0 已知漏洞。

### Added

- `.env.example`：完整环境变量参考，字段名、格式与开发示例；仓库不保存真实凭据。
- 三角色 RBAC：`admin`（系统管理员）/ `operator`（运维操作员）/ `viewer`（只读用户），
  由 `dependencies.require_write` / `require_admin` 在路由层强制执行。
- `init-admin` 一次性 bootstrap：重复调用返回 409，管理员初始密码来自
  `INITIAL_ADMIN_PASSWORD` 环境变量。
- `/health/live` 与 `/health/ready` 端点；Compose 全部服务增加 healthcheck，
  `depends_on` 使用健康条件。
- `host_key_fingerprint` 资产字段：SSH 主机密钥指纹存储与严格校验。
- SSH 凭据加密存储：`common/crypto.py` 使用 Fernet（版本前缀 `v1:`），
  主密钥来自 `CREDENTIAL_ENCRYPTION_KEY`。
- `services/ssh_service.py`：主机密钥校验（拒绝未知/不匹配指纹）、可区分错误类型
  （认证失败 / 指纹不匹配 / 未登记密钥 / 连接超时 / 主机不可达 / 远端命令失败）。
- `common/redact.py`：日志与异常脱敏过滤器，以及 `audit_log` 审计表
  （登录失败、权限拒绝、敏感操作）。
- pytest 测试套件：覆盖配置启动校验、鉴权矩阵、禁用用户、凭据脱敏、host key 与
  加密回环；配套 `requirements-dev.txt`。
- CI 门禁：后端 Ruff / compileall / pytest，前端 `npm audit --omit=dev` / build，
  部署 `docker compose config` 校验。

### Changed

- **鉴权覆盖**：全部业务路由统一要求登录（未登录返回 401），写操作要求
  admin/operator，用户管理仅 admin。
- **默认凭据**：`SECRET_KEY`、数据库密码、管理员初始密码不再存在代码中的安全风险
  默认值；生产环境缺失或使用默认值将拒绝启动。
- **CORS**：改为显式 allowlist（`CORS_ORIGINS`），禁止 `*` 与 credentials 组合。
- **端口收敛**：MySQL / Redis 默认只在 Compose 内部网络开放，宿主机端口通过可选
  `docker-compose.ports.yml` 覆盖文件启用；Prometheus / Grafana 保持暴露便于演示。
- **SSH 凭据**：资产 API 只返回 `has_password` / `has_private_key` 与指纹，不再返回
  明文；Celery 任务改传 `asset_id`，Worker 从数据库读取并在内存中解密。
- **主机信任**：废弃 Paramiko `AutoAddPolicy`，默认拒绝未登记 host key 的主机。
- 禁用用户（`status=0`）无法登录，且旧 Token 立即失效。

### Security

- 非开发环境缺少关键 Secret 或使用危险默认值时启动失败并给出清晰错误。
- 日志、审计和异常堆栈对密码、私钥、Token、数据库 URL 统一脱敏。

### Fixed

- 资产更新改为部分更新（只更新显式传入字段），不再清空未提交的密码。

## [Baseline] - 2026-08-14（1b661e9）

初始基线：FastAPI + SQLAlchemy + MySQL / Redis + Celery + Vue 3 + Element Plus，
Docker Compose 单机部署与 Prometheus / Grafana 观测组合。前端依赖固定版本，
`npm audit --omit=dev` 为 0 漏洞。