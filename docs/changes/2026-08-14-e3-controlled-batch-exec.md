# E3 受控批量运维（2026-08-14）

> 阶段：E3 受控批量运维（P0）
> 分支：`feat/e3-controller-exec` → PR 合入 `main`
> 验收方式：本地 pytest 77 项全绿、覆盖率/审计门禁、Alembic 往返迁移、前端生产构建。
> 说明：本次验收全部为 mock/单测与静态/构建证据，不含真实 Linux 主机执行，
> 真实主机演练归 E4。

## 背景

E2 的批量执行只有一个「任意命令 + 文本区」入口：无操作目录、无预览确认、无幂等、
并发只受 Celery 默认约束、逐主机结果不落库。E3 把它改造成受控链路：

```text
选择资产 → 固定操作/参数（或 break-glass）→ preview 校验+确认令牌 → 幂等提交
→ Celery 有界并发逐主机执行 → 逐主机状态（queued/running/succeeded/failed/timed_out）
→ 失败隔离与重试 → 审计
```

## 后端

### 固定操作目录与参数白名单（`services/operations.py`）

6 个固定操作，全部为运维常见只读/单点写操作：

| code | 名称 | 风险 | 命令 |
|---|---|---|---|
| `disk_usage` | 磁盘检查 | read | `df -h [path]` |
| `memory_usage` | 内存检查 | read | `free -m` |
| `service_status` | 服务状态 | read | `systemctl status --no-pager <svc> 2>&1 \| head -40` |
| `service_restart` | 服务重启 | write | `systemctl restart <svc> && systemctl is-active <svc>` |
| `log_tail` | 日志尾部 | read | `tail -n <lines> [path|/var/log/syslog]` |
| `port_listen` | 端口监听 | read | `ss -tlnp [\| grep -E :<port>\b]` |

安全模型：

- 每个参数先经白名单正则校验（服务名 `^[A-Za-z0-9_.:@-]{1,64}$`、绝对路径
  `^/[A-Za-z0-9_./-]{1,200}$`、普通串、整数区间），通过后再 `shlex.quote` 二次包裹，
  参数永不可能进入任意 shell 位置。
- 写操作（`service_restart`）`risk='write'`，必须 preview 确认。

### 受控执行 API（`api/v1/exec_task.py`）

- `GET  /api/v1/exec/operations`：操作目录（含参数 schema，前端渲染表单）。
- `POST /api/v1/exec/preview`：校验资产/操作/参数，返回最终命令、风险与（写操作）
  确认令牌；只读不返回令牌。
- `POST /api/v1/exec/batch`：幂等键去重（同一用户同键返回既有记录不重复派发）；
  写操作必须带 preview 的确认令牌；创建 `ExecRecord` + 逐主机 `ExecHostResult`
  （queued）行，派发 Celery `group`。
- `GET  /api/v1/exec/records[/{id}]`、`GET /records/{id}/hosts`：任务汇总与逐主机结果。
- `POST /records/{id}/retry`：仅重试 `failed`/`timed_out` 主机，其余不动。
- `GET/POST /api/v1/exec/break_glass`：读取/切换任意命令开关（POST 仅 admin，
  启用必须填理由，写审计）。

### Worker（`tasks/exec_tasks.py`）

- `exec_host_result(record_id, asset_id)`：`soft_time_limit=75, time_limit=90`
  与配置 `EXEC_TASK_HARD_TIMEOUT=90` 一致；独立 DB 会话；连接失败/认证失败/命令
  失败/超时各自归类，更新对应 `ExecHostResult` 行；`finally` 中
  `_recompute_record` 聚合 succeeded/failed/running/timed_out 并刷新任务状态。
- 保留 `batch_exec_command` 别名兼容旧引用。

### 数据模型与迁移

- `ExecRecord` 新增 `exec_type/operation/params/status/idempotency_key/
  confirm_token/worker_concurrency/total_hosts/succeeded/failed/running/timed_out`，
  移除旧 `exec_status`。
- 新表 `exec_host_result`（record_id/asset_id/host/status/exit_code/stdout/stderr/
  error_type/error + 时间戳）。
- Alembic `0002_extend_exec_record_and_host_result`：SQLite 走 batch 重建
  （旧数据保留，`status` 映射 `pending`），MySQL 走原生 ALTER；
  `tests/test_migrations.py` 覆盖 0001→0002→downgrade→re-upgrade 往返与
  head 与 models 对齐。
- `alembic/env.py`：优先读实时 `DATABASE_URL` 环境变量，与 CLI/CI 行为一致。

### 配置（`config.py` + `.env.example` + compose）

`BATCH_MAX_ASSETS=50`（超限 400）、`BATCH_CONCURRENCY=8`（celery `-c`）、
`EXEC_TASK_HARD_TIMEOUT=90`、`BREAK_GLASS_DEFAULT=false`。

## 前端（`easyops_web`）

`BatchExec.vue` 重写为 4 步向导：

1. 选择资产（多选、上限 50）；
2. 选择操作目录（表格）+ 动态参数表单，或 break-glass 任意命令；
3. 预览确认（命令、风险、主机列表、确认令牌、幂等键生成）；
4. 提交后逐主机结果表（状态/退出码/输出/错误），1.5s 轮询，可重试失败主机。

`src/api/exec.js` 扩展 9 个端点调用。

## 测试与门禁

| 门禁 | 结果 |
|---|---|
| pytest 全量 | 77 passed（E2 65 + 新 E3 12，含迁移往返 2） |
| 覆盖率全局 | 85.49%（≥50%） |
| 覆盖率安全模块 | 91.09%（≥80%） |
| Ruff | 0 错误 |
| pip-audit | 0 漏洞 |
| npm audit（--omit=dev） | 0 漏洞 |
| Alembic head（SQLite） | 0001+0002 建表 + `exec_host_result` 存在 |
| 前端生产构建 | 328ms 成功 |
| compose config / ports override | 通过 |
| README/docs 链接 | 全部可解析 |

## 已知限制

- 本次为 mock/单测与构建证据；真实 Linux 命令产物、超时边界与批量压测归 E4。
- break-glass 令牌校验为服务端会话级最小校验（长度≥20），未做一次性消费绑定；
  后续可在任务表记录 preview 令牌指纹做强关联。
- 逐主机结果不做分页（单任务 ≤50 台）。