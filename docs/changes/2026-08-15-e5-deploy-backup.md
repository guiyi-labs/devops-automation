# E5 部署、备份与恢复（2026-08-15）

> 阶段：E5 部署、备份与恢复（P1）
> 分支：`feat/e5-deploy-backup` → PR 合入 `main`
> 验收方式：本地 pytest 121 项全绿、覆盖率/审计门禁、Alembic 往返迁移（含 0004）、
> 前端生产构建、compose config 通过。
> 说明：本次验收为 mock/单测与静态/构建证据；真实部署→健康验证→回滚演练
> 和备份→恢复演练标注为 E5 验收第二阶段（本地 docker compose 可行，归 E6 前补做）。

## 背景

E2 的部署只留了一个占位接口（`POST /projects/{id}/run` 返回 `submitted`），
没有任何真实发布记录或回滚能力；备份只有占位 `run_backup_job`，无校验、恢复
或保留策略。E5 把它们改造成受控可回滚的完整链路：

```text
登记项目 → 受控模板选择（compose-web）→ 预览计划（pull/build/up/healthcheck）
→ 确认发布（Celery Worker 执行固定步骤，不执行仓库任意脚本）
→ 发布记录（image/version/digest/执行人/结果）→ 回滚（到最近有效发布）
```

```text
备份（mysqldump mock/真实 → gzip → sha256 校验 → 一致性检查）
→ 恢复（从校验通过的备份 → 表级一致性检查）
→ 保留：失败备份不覆盖最后一份有效备份
```

## 后端

### 数据模型与迁移（Alembic 0004）

- `DeployRelease`：project_id FK / release_type（deploy/rollback）/ status（requested/
  running/succeeded/failed/rollback_succeeded/rollback_failed）/ image / image_digest /
  version / exec_user / result（JSON：步骤结果/回滚点/错误）+ 时间戳。
- `BackupRecord`：op_type（backup/restore）/ status / file_path / file_size_bytes /
  backup_engine（mysql_dump）/ checksum / checksum_ok（1=校验通过，不可恢复标记为 0）/
  validation（JSON：一致性详情）/ exec_user / result（JSON）+ 时间戳。
- `tests/test_migrations.py` 覆盖 0003→0004→downgrade 往返与 head 与 models 完整对齐。

### 受控部署计划（`services/deploy_service.py`）

- `DeployPlan` dataclass：template / image / version / port / steps 列表
  （固定 `['pull','build','up','healthcheck']`，不允许从输入注入新步骤）。
- `build_plan(project, ...)`：从项目记录推断镜像名，默认 `easyops/{project_name}`，
  不执行任何 Shell。
- `run_deploy_steps(plan, runner)`：按白名单步骤顺序执行，`ALLOWED_STEPS` 元组
  硬编码；非法步骤（`rm -rf /` 等）立即中止整个链路，绝不继续执行后续步骤。
- `last_valid_release(db, project_id, before_id)`：取「早于当前发布」的最近成功发布
  作为回滚点，避免回滚时引用自身。
- 模板目录 `deploy_templates/compose-web/`：README 说明 + `steps.sh`（bash 骨架）；
  真实执行归 E5 验收第二阶段；本阶段测试用 runner 注入 mock 或跳过。

### 部署 API（`api/v1/deploy.py`）

- `POST /projects/{id}/preview`：返回 `plan`（步骤/image/version/port）+ `rollback_point`
  （最近成功发布，无则 null），不执行任何命令。
- `POST /projects`（保留）：登记项目。
- `POST /releases`：按预览计划参数创建 `DeployRelease`（status=requested）→ 派发
  Celery `run_deploy_release.delay(release_id)`。
- `GET /projects/{id}/releases`、`GET /releases/{id}`：查询发布记录。
- `POST /releases/{id}/rollback`：校验回滚点存在 → 创建 rollback 类型记录 → 派发
  `run_rollback_release.delay(rollback_id)` → 审计。
- `GET /templates`：可用模板静态清单（compose-web）。
- E2 占位 `POST /projects/{id}/run` 已移除（返回 404）。

### 部署 Worker（`tasks/deploy_tasks.py`）

- `run_deploy_release(release_id)`：status → running → 按 plan steps 执行
  → 全部成功 status=succeeded（写 image_digest）/ 任一步失败 status=failed + error。
- `run_rollback_release(rollback_id)`：固定执行 rollback + healthcheck 两步
  → rollback_succeeded / rollback_failed。
- `soft_time_limit=150/120, time_limit=180`。

### 备份服务（`services/backup_service.py`）

- `BackupEngine.dump()`：mock 路径生成 gzip 格式 `fake_dump_bytes()`（含 sys_user 表
  骨架），真实路径对接 mysqldump（E5 验收第二阶段）。
- `validate_dump_bytes(data)`：非空 + gzip magic 可解 + SHA256；校验结果为纯函数
  便于单测。
- `BackupEngine.consistency_check(data)`：dump→校验→restore→表级行数一致性→返回
  `consistent` 布尔；restore mock 返回 `{restored_rows, tables}`。

### 备份 API（`api/v1/backup.py`）

- `POST /create`：创建 `BackupRecord`（op_type=backup, status=running）→ 派发
  `run_backup_job.delay(backup_id)` → 审计。
- `POST /restore`：只允许从 `status=succeeded` 且 `checksum_ok=1` 的备份恢复；
  创建 restore 类型记录 → 派发 `run_restore_job.delay(restore_id)`。
- `GET /records[/{id}]`：备份/恢复记录查询。
- `GET /policy`：保留策略说明（失败备份不覆盖最后有效备份）。

### 备份 Worker（`tasks/backup_tasks.py`）

- `run_backup_job(backup_id)`：engine.dump() → consistency_check → 失败不覆盖
  最后有效备份（只有 consistent=true 才写 checksum_ok=1 + file_path）。
- `run_restore_job(restore_id)`：读取备份 → engine.consistency_check
  → 结果落 validation JSON。

## 前端（`easyops_web`）

### 受控部署（`DeployProject.vue`，路由 `/deploy`）

- 项目登记表单 + 项目列表；
- 「部署预览」弹窗：输入 image/version/port → 生成计划（步骤 tags + 回滚点提示）→
  确认发布按钮；
- 「发布记录」弹窗：release_type / status（颜色区分）/ image/version/exec_user /
  结果 JSON tooltip；成功状态可触发回滚（二次确认，调用 rollback API）。

### 备份恢复（`BackupRestore.vue`，路由 `/backup`，侧栏「备份恢复」）

- 备份记录表：op_type / status / database / 文件大小 / checksum_ok / checksum 摘要
  / 操作（成功备份显示「恢复」按钮，二次确认）；
- 「立即备份」按钮（显示 DB 名）；恢复后显示一致性校验详情弹窗；
- 顶部提示：保留策略说明。

`src/api/deploy.js` 扩展至 10 个端点（deploy 7 + backup 5）。

## 测试与门禁

| 门禁 | 结果 |
|---|---|
| pytest 全量 | 121 passed（E4 100 + 新 E5 21） |
| 覆盖率全局 | 86.07%（≥50%） |
| 覆盖率安全模块 | 91.09%（≥80%） |
| E5 新增模块（deploy_service/backup_service/deploy API/backup API/deploy_tasks/backup_tasks） | 83.20%（mock/静态口径） |
| Ruff | 0 错误 |
| pip-audit | 0 漏洞 |
| npm audit（--omit=dev） | 0 漏洞 |
| Alembic head（SQLite） | 0001–0004 建表，往返降级通过 |
| 前端生产构建 | 293ms 成功（DeployProject 6.69 kB + BackupRestore 3.53 kB） |
| compose config / ports override | 通过 |
| 部署步骤白名单测试 | 非法步骤立即中止，不继续执行 |
| 回滚点边界测试 | 无成功发布时拒绝回滚；回滚到早于当前发布的最近成功发布 |

E5 新测试覆盖：
- 部署：预览计划字段、viewer 403、Worker 成功状态/digest、Worker 步骤失败 →
  status=failed、非法步骤中止、回滚流（2 次发布→回滚验证 rollback_to=
  前一个 release id）、无回滚点拒绝、占位端点已移除、模板列表；
- 备份：gzip 正常/非 gzip SQL/空/损坏校验、engine.dump+consistency_check、
  创建备份→Worker 成功→checksum、恢复流→consistent、从未校验备份恢复 400、
  未登录 401、viewer 403、保留策略返回；
- 迁移：0004 升降级 + head 对齐。

全部为 mock/单测口径。

## 已知限制

- 真实部署→健康验证→回滚和备份→恢复演练（真实 MySQL dump/restore）为 E5 验收
  第二阶段，标注为 mock/静态证据；真实演练在本地 docker compose 环境可行，
  归 E6 交付前补做。
- `DeployProject` 现有字段 `build_script`/`deploy_script` 仍保留（记录用途），
  部署引擎只从模板目录执行固定步骤，不读取或执行这些字段内容。
- `BackupEngine.restore()` 在 mock 模式下返回固定骨架数据；真实 restore
  需对接 MySQL binlog/time point recovery，为 E5 第二阶段设计。
- 备份文件实际存储路径未做持久化（`file_path` 为占位）；真实存储归 E6。
- 恢复前「先备份当前数据」由页面提示引导，未做强制二次检查。