# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循
[Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

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