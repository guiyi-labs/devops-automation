# Change Record: E1 安全与配置基线

- 日期：2026-08-14
- 范围：`devops-automation` / EasyOps E1（安全、鉴权、SSH 凭据、健康检查）
- 基线 commit：`1b661e9`（README 与 Vite 配置引用更新）
- 相关文档：`docs/roadmap.md`、`CHANGELOG.md`、`.env.example`

## 背景

基线仓库存在五类高危缺口：默认凭据（`SECRET_KEY`、MySQL 密码、管理员密码）、
业务路由几乎全部匿名可读写、SSH 凭据明文落库且随 Celery 消息传输、Paramiko
`AutoAddPolicy` 自动接受任意主机密钥、没有任何自动化测试。E1 的目标是把风险面
收紧到「默认更安全、权限边界明确、SSH 凭据处理可靠」，不扩展新业务页面。

## 身份与权限（RBAC）

- 新增依赖 `dependencies.get_current_user`（含禁用用户校验）、`require_write`（admin/operator）、
  `require_admin`；全部业务路由接登录与角色校验。
- 三角色种子：`admin` / `operator` / `viewer`；用户管理仅 admin。
- `init-admin` 改为一次性 bootstrap（`system_flag.admin_bootstrapped` 标记，重复调用 409），
  初始密码来自 `INITIAL_ADMIN_PASSWORD`。
- 新增 `audit_log` 表：登录失败、登录成功、禁用用户拒绝、权限拒绝、资产写操作均留痕。

## 配置与 Secret

- `config.py`：新增 `APP_ENV`、`DATABASE_URL`、`CREDENTIAL_ENCRYPTION_KEY`、
  `INITIAL_ADMIN_PASSWORD`、`CORS_ORIGINS`、`SSH_ALLOW_UNVERIFIED_HOST_KEY`；
  `validate_settings()` 在非开发环境拒绝缺少/危险默认值并 `exit(1)`。
- `docker-compose.yml`：MySQL/Redis 不再映射宿主机端口（可选 `docker-compose.ports.yml`
  叠加启用）；全部服务增加 healthcheck，`depends_on` 使用 `service_healthy`；凭据全部
  环境变量注入。
- 新增 `.env.example`。

## SSH 凭据与主机信任

- `database/models.py`：`server_asset` 增加 `host_key_fingerprint` 列（已提供
  `scripts/e1_migrate.sql` 供旧库升级）。
- `common/crypto.py`：Fernet 对称加密，密文带 `v1:` 前缀；主密钥 `CREDENTIAL_ENCRYPTION_KEY`。
- `schemas/all.py`：`AssetOut` 不再暴露 `ssh_pwd` / `ssh_key`，仅返回
  `has_password` / `has_private_key` 与指纹；`AssetUpdate` 改为部分更新。
- `api/v1/asset.py`：明文凭据入参加密后落库，返回只含存在性标记。
- `tasks/exec_tasks.py`：Celery 只接收 `asset_id`，Worker 查询数据库并内存解密后连接，
  明文密码不再进入 Redis 消息。
- `services/ssh_service.py`：废弃 `AutoAddPolicy`；`VerifyHostKeyPolicy` 按指纹严格校验，
  未登记且未显式允许时拒绝；错误类型化（`AuthError` / `HostKeyError` /
  `UnknownHostKeyError` / `ConnectionTimeoutError` / `UnreachableError` /
  `RemoteCommandError`），错误信息经 `common/redact.py` 脱敏。
- 仅本地开发允许 `SSH_ALLOW_UNVERIFIED_HOST_KEY=true` 连接未登记主机。

## 文件级改动清单

| 文件 | 改动 |
|---|---|
| `easyops_api/config.py` | 环境变量化 + `validate_settings()` |
| `easyops_api/common/crypto.py` | 新增：Fernet 凭据加密 |
| `easyops_api/common/redact.py` | 新增：日志/异常脱敏 |
| `easyops_api/database/session.py` | 支持 `DATABASE_URL`（sqlite 测试） |
| `easyops_api/database/models.py` | 增加 `host_key_fingerprint`、`AuditLog`、`SystemFlag` |
| `easyops_api/schemas/all.py` | 资产输出脱敏、部分更新 |
| `easyops_api/dependencies.py` | 三角色依赖与审计 |
| `easyops_api/api/v1/*.py` | 全路由鉴权 + 审计 |
| `easyops_api/services/ssh_service.py` | 新增：主机密钥校验与错误类型 |
| `easyops_api/tasks/exec_tasks.py` | asset_id 传递、Worker 内解密 |
| `easyops_api/main.py` | CORS allowlist、logging 脱敏、health 端点 |
| `docker-compose.yml` / `docker-compose.ports.yml` | 端口收敛 + healthcheck |
| `.env.example` / `CHANGELOG.md` / `docs/roadmap.md` | 新增/更新 |
| `easyops_api/tests/*` | 新增 pytest 套件 |
| `.github/workflows/ci.yml` | 增加 pytest / ruff / compose config 门禁 |

## 验证命令与结果

```bash
cd easyops_api
python -m compileall -q .            # 通过
pip install -r requirements-dev.txt  # 安装测试依赖
pytest -v                             # 全部通过（见 tests/）

cd easyops_web
npm ci                               # 通过
npm audit --omit=dev                 # 0 漏洞
npm run build                        # 通过

cd ..
docker compose config                # 通过（healthcheck + 覆盖文件语法校验）
```

详细输出见 CI 运行记录。

## 剩余限制（明确不宣称已完成）

- 真实 Linux 主机上的 host key 指纹录入与回环验证尚未在真实环境演练（当前为 mock/pytest）。
- 未引入 Alembic（`create_all` 仍在 E2 迁移）；已有数据库升级需执行
  `scripts/e1_migrate.sql`。
- 任意命令批量执行仍接受任意 `command` 字符串，`break_glass` 模型、幂等键、预览确认、
  并发与输出上限属 E3。
- Swagger `/docs` 默认开放；生产建议再收敛入口。
- Prometheus / Grafana 端口保持宿主映射便于演示；如需收敛可参照 MySQL 覆盖文件做法。

## 风险与回滚

- 若 `CREDENTIAL_ENCRYPTION_KEY` 丢失，已加密凭据无法还原——生产需妥善备份该值。
- 升级后旧资产若无 `host_key_fingerprint`，批量任务默认拒绝连接（未知 host key），
  需补录指纹或临时开启 `SSH_ALLOW_UNVERIFIED_HOST_KEY`（仅开发）。
- 回滚：`git revert` 本分支合并；数据库层需注意新表/新列。