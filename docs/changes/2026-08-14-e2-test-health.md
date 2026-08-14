# E2 测试与运行基线 — 执行记录

- 日期：2026-08-14（本地验证）/ 2026-08-14（文档落盘）
- 分支：`feat/e2-test-health`
- 对应阶段：EasyOps 优化实施方案「E2 测试与运行基线」
- 前置：E1 安全与配置基线（PR #1，合并提交 `19f0d05`）

## 目标（对照 E2 提示词）

按「配置 → 鉴权 → SSH → 测试 → 文档」顺序落实；CI 全绿；Compose 启动稳定。

## 本次改动

### 1. 数据库迁移（Alembic）

- 新增 `easyops_api/alembic/`（`env.py` 从 `database.models` 元数据接入，URL 由
  `DATABASE_URL` 或 Settings 决定；SQLite 下启用 batch 渲染）与初始迁移
  `0001_initial_schema`：`sys_role` / `sys_user` / `server_asset`（含
  `host_key_fingerprint`）/ `exec_record` / `deploy_project` / `cron_task` /
  `alert_rule` / `audit_log` / `system_flag` 共 9 张表。
- `main.py` 移除启动时 `Base.metadata.create_all`，表结构统一由 Alembic 管理。
- `docker-compose.yml`：api / celery 启动命令改为
  `alembic upgrade head && <启动命令>`（幂等，先迁移再启动）。
- CI 增加「Alembic 迁移检查」：SQLite 上 `alembic upgrade head` 后断言 9 张表齐全。

### 2. 测试与覆盖率

- 新增 `tests/test_crud.py`：资产/告警/Cron/部署 CRUD 全流程、404 / 400 / 409 / 422
  错误响应、权限矩阵（viewer 只读、operator 写）。
- 新增 `tests/test_exec.py`：批量执行边界（空资产 400、超 50 台 400、资产缺失 400）、
  重复请求各自成记录、Worker 单主机失败隔离（认证失败不影响其它主机，`status=2` +
  `error_type` 区分）、资产不存在返回结构化错误。
- 扩展 `tests/test_ssh.py`：连接成功路径（status=1 + stdout）、远端命令非 0 退出抛
  `RemoteCommandError`、RSA 私钥加载、非法私钥返回 None。
- `services/ssh_service.py`：非 0 退出由「静默 status=2」改为抛
  `RemoteCommandError`，失败路径可区分。
- 覆盖率门禁：全局初始 ≥ 50%（实测 88%）；核心安全模块（`common` / `config` /
  `dependencies` / `services.ssh_service`）≥ 80%（实测 91%）。

### 3. CI 门禁

- 后端：Ruff / compileall / pytest / 全局覆盖率 / 安全模块覆盖率 / `pip-audit` /
  Alembic SQLite 迁移校验。
- 前端：npm ci / `npm audit --omit=dev` / build（与 E1 相同）。
- 部署：`docker compose config`（两份清单）、kubeconform（`k8s/` schema 校验）、
  `.env.example` 存在性、README / docs 相对链接解析检查。

### 4. 依赖审计修复

`pip-audit` 标记的已知漏洞已通过小范围升级消除：

- `fastapi` 0.111.0 → 0.141.1、`starlette` 0.37.2 → 1.6.0（
  `prometheus-fastapi-instrumentator` 同步 7.0.0 → 8.1.0 以兼容新 starlette）
- `python-multipart` 0.0.9 → 0.0.32
- `requests` 2.32.3 → 2.34.2
- `python-jose` → `PyJWT==2.13.0`（HS256 用法一致，消除 python-jose 及其传递依赖
  `ecdsa` 的审计告警——ecdsa 的 Minerva 侧信道通告无修复版）
- `paramiko` 3.4.0 → 5.0.0（修复 rsakey SHA-1 通告；paramiko 5 移除 DSSKey，
  `_load_private_key` 同步去掉 DSS 分支）
- `pytest` 8.4.0 → 9.1.1（开发依赖）

65 项 pytest 全套通过，验证升级未破坏功能。

## 验证结果

| 检查项 | 结果 |
|---|---|
| pytest（SQLite + 全量） | ✅ 65 passed（约 80s） |
| Ruff | ✅ 0 errors |
| 全局覆盖率 | ✅ 88%（门禁 ≥ 50%） |
| 安全模块覆盖率 | ✅ 91%（门禁 ≥ 80%） |
| Alembic SQLite 迁移 | ✅ 9 张表全部建成 |
| `docker compose config --quiet`（含 ports 覆盖） | ✅ |
| kubeconform（本地模拟） | ✅ k8s 清单 schema 合法 |
| README/docs 链接检查 | ✅ 全部可解析 |
| npm audit / 前端构建 | ✅ 0 漏洞 / 构建通过 |
| pip-audit | ✅ 目标 0 已知漏洞 |

> 说明：CI 实际执行以 GitHub Actions 运行结果为准；本地环境（macOS + venv）与
> Actions runner（Ubuntu + Python 3.10）存在微小差异，如某步骤在 CI 上波动会在后续
> 提交中修正。

## 边界与未做（留给后续阶段）

- E3：批量命令参数白名单、幂等键（`Idempotency-Key`）、并发限制——本阶段仅测试
  固定「重复请求各自成记录」现状。
- E4：主机巡检（CPU/内存/磁盘实时采集）。
- E5：备份恢复与卸载还原演练。
- E6：Release、Tag 与运行截图证据。
- 生产级声明仍不成立：无真实服务器演练、无独立 Secret 管理、无高可用拓扑。

## 下一步

E3 批量命令模型：命令白名单 / 参数校验、幂等、并发与超时上限，随后同步 Obsidian 库。