# E4 主机巡检与监控（2026-08-15）

> 阶段：E4 主机巡检与监控（P0）
> 分支：`feat/e4-host-inspection` → PR 合入 `main`
> 验收方式：本地 pytest 100 项全绿、覆盖率/审计门禁、Alembic 往返迁移（含 0003）、
> Prometheus 规则文件与 Grafana dashboard 静态校验、前端生产构建。
> 说明：本次验收为 mock/单测与静态/构建证据；真实 Linux VM（≥2 台 Ubuntu 24.04）
> 演练归 E4 验收门禁第二阶段（复现正常/异常、Prometheus 真实指标、Grafana 截图）。

## 背景

运维主机缺少可解释的「健康」数据：没有结构化事实采集（OS/内核/磁盘/端口/服务），
没有规则化巡检判定，可观测性只有 Instrumentator 默认 HTTP 指标。E4 补齐：

```text
资产 → SSH 只读探测（一次会话多命令）→ HostFacts（observed_at/source/timeout_ms）
→ 规则引擎（healthy/warning/critical/unknown，缺数据固定 unknown）
→ 落库 inspection_record / host_inspection / inspection_rule
→ Prometheus 自定义指标 + 告警规则 + Grafana dashboard
```

## 后端

### 事实采集（`services/host_inspection.py`）

一次 SSH 会话执行只读探测命令（`hostname` / `/etc/os-release` / `uname -r` /
`uptime` / `nproc` / `free -m` / `df -hP` / `df -iP` / `ss -tln` /
`systemctl list-units --type=service --state=running`），逐探测独立容错：
单个探测失败（如 `ss` 未安装）只记入 `probes_failed`，不拖垮整台采集。

- `HostFacts` 结构化：hostname/os_name/kernel/uptime/cpu_count/load_1-5-15/
  memory/swap（MB 与百分比）/disks（total/used/used_pct/inode_pct）/listening_ports/
  active_services，固定带 `observed_at/source/timeout_ms/unavailable_reason`。
- 复用 `ssh_service` 的 `VerifyHostKeyPolicy` + 错误分类；凭据由 Worker 解密后传入，
  未登记 host key 默认拒绝连接（`SSH_ALLOW_UNVERIFIED_HOST_KEY` 可放开）。
- 纯解析函数（`parse_uptime/parse_free_m/parse_df_h/parse_df_i/parse_ss_tln/...`）
  暴露便于单测。
- 连接/认证/超时失败在 facts 上留痕（`probes_failed: connect:<error_type>` +
  `unavailable_reason`），对应规则判定 unknown，不误判健康。

### 规则引擎（`services/inspection_rules.py`）

规则 = `metric + operator + threshold + severity`，支持：

| metric | 含义 |
|---|---|
| `disk_used_pct` / `inode_used_pct` | 磁盘 / inode 使用率最大百分比（gt） |
| `memory_used_pct` / `swap_used_pct` | 内存 / swap 使用率（gt/lt） |
| `load_5` | 5 分钟负载（gt） |
| `service_stopped` | 关键服务不在运行列表（threshold=服务名，not_contains） |
| `port_not_listening` | 指定端口未监听（threshold=端口，not_contains） |

整体判定：缺数据固定 `unknown`（采集不可用/指标无数据/任一规则无数据）；
任何 `critical` 命中 → critical；否则任何 `warning` → warning；全部通过 → healthy；
一条规则都没有 → unknown。内置 8 条默认规则（磁盘 90/95、inode 90、内存 90、
swap 50、load 4、服务 nginx、端口 22），首次触发巡检且规则表为空时自动种子。

### API（`api/v1/inspection.py`，挂载于 `/api/v1/inspection`）

- `POST /collect`：校验资产（≤`BATCH_MAX_ASSETS`，缺失 400）→ 建记录 +
  逐主机行 → 派发 Celery `group`；空规则自动种子。
- `GET /records[/{id}]`、`GET /records/{id}/hosts`：任务汇总与逐主机结果。
- `GET /assets/{id}/latest`：某资产最近一次巡检。
- `GET /rules`、`POST|PUT /rules/{id}`、`DELETE /rules/{id}`：规则 CRUD
  （指标/操作符/严重度白名单校验，重名 409）。
- 全部写操作写审计；viewer 仅读，collect/规则写需写权限。

### Worker（`tasks/inspection_tasks.py`）

`inspect_host(record_id, asset_id)`：`soft_time_limit=50, time_limit=65`；
独立 DB 会话；凭据解密失败 → unknown；采集→规则评估→写 facts/rule_results/
overall_status；`finally` 聚合 `_recompute_record`（total/succeeded/failed/unknown，
全部非 running → done）并记 `easyops_inspection_*` 指标。
`tasks/inspection_tasks.py` 已加入 `celery_app.autodiscover_tasks`。

### 数据模型与迁移

- `InspectionRecord`（asset_ids/status/total_hosts/succeeded/failed/unknown/exec_user）。
- `HostInspection`（record_id FK/asset_id FK/host/overall_status/facts JSON/
  rule_results JSON/observed_at/source/timeout_ms/unavailable_reason）。
- `InspectionRule`（name 唯一/description/metric/operator/threshold/severity/enabled）。
- Alembic `0003_add_host_inspection`：SQLite 与 MySQL 均原生建表；
  `tests/test_migrations.py` 覆盖 0001→0002→0003→downgrade→re-upgrade 往返、
  head 与 models 对齐（含新 3 表与列）。

## 可观测性

### 自定义指标（`services/metrics.py`）

| 指标 | 类型 | 说明 |
|---|---|---|
| `easyops_exec_tasks_total{status}` | Counter | 批量执行主机结果（E3 接入，统一注册） |
| `easyops_exec_task_duration_seconds` | Histogram | 批量执行单主机耗时 |
| `easyops_inspection_hosts_total{status}` | Counter | 巡检主机总数（按状态） |
| `easyops_inspection_duration_seconds` | Histogram | 单主机巡检耗时 |
| `easyops_queue_depth{queue}` | Gauge | Celery 队列积压（`tasks/metrics_tasks.py` 采集） |
| `easyops_host_health{status}` | Gauge | 最近巡检健康分布 |

### 告警规则（`prometheus-alerts.yml`，compose 挂载）

`EasyOpsApiDown`（up==0，critical）、`EasyOpsQueueBacklog`（队列>50，5min）、
`EasyOpsTaskFailureRateHigh`（10min 失败率>30%）、`EasyOpsHostCritical`（critical>0）、
`EasyOpsInspectionFailures`（15min unknown 速率>0.2/s）。

### Grafana（`grafana/` + compose 挂载）

`dashboard easyops-overview`：请求速率 / P95 延迟 / 队列深度 / 任务成功·失败 /
延迟分位（p50/p95/p99）/ 执行耗时 / 任务成功率 / 巡检健康分布。
`provisioning/` 自动注册 Prometheus datasource + dashboard 文件，
匿名只读访问（演示环境），默认首页为该 dashboard。

## 前端（`easyops_web`）

`HostInspection.vue`（路由 `/inspect`，侧栏「主机巡检」）：

- 巡检采集 tab：多选主机（上限 50）→ 触发 → 记录列表（执行人/主机数/成功·unknown/
  状态/采集时间）→ 详情弹窗逐主机（状态/事实快照/规则明细 tooltip）；
  采集时间有值才显示，unknowe 主机显示不可用原因。
- 巡检规则 tab：规则表格 + 新增/编辑/删除（指标下拉、操作符、阈值、严重度）。

`src/api/inspection.js` 9 个端点。

## 测试与门禁

| 门禁 | 结果 |
|---|---|
| pytest 全量 | 100 passed（E3 77 + 新 E4 23） |
| 覆盖率全局 | 86.10%（≥50%） |
| 覆盖率安全模块 | 91.09%（≥80%） |
| E4 新增模块（host_inspection/rules/metrics/worker/api） | 76.51%（mock SSH 口径） |
| Ruff | 0 错误 |
| pip-audit | 0 漏洞 |
| npm audit（--omit=dev） | 0 漏洞 |
| Alembic head（SQLite） | 0001+0002+0003 建表，往返降级通过 |
| 前端生产构建 | 390ms 成功 |
| compose config / ports override | 通过 |
| 告警规则 YAML / dashboard JSON | 静态校验通过 |

E4 新测试覆盖：解析函数、规则引擎（健康/预警/严重/unknown/无规则）、
collect API（记录创建、空/缺失资产 400、规则种子与 CRUD、viewer 403）、
Worker（healthy/critical/unknown/missing asset）、mock SSH 事实采集
（完整采集、未登记 key、探测失败隔离、解密失败）。全部 mock/单测口径。

## 已知限制

- 事实采集为瞬时快照（load/内存是单点采样），非时序打点；持续趋势观测依赖
  Prometheus 侧（本阶段提供 dashboard 指标，真实打点由 Agent/Beat 扩展）。
- `easyops_queue_depth` 由任务手动触发采样（无 beat）；部署可自行加
  `celery -B` 或 cron 调 `queue_depth_metric.delay()`。
- 页面对大结果集未分页（单任务 ≤50 台）。
- 真实双 Linux VM 复现正常/异常、Prometheus 真实指标与 Grafana 截图，
  属 E4 验收第二阶段，需按环境规范提供脱敏主机名/IP 记录。