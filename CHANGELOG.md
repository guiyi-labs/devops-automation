# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循
[Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added

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