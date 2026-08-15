# E5-P2 真实部署与恢复验收报告

**日期**：2026-08-15  
**分支**：`feat/e5-phase2-real-acceptance`  
**验收环境**：两台 Ubuntu 24.04.4 Lima VM（e5-deploy-1/2），Docker 29.7.2，easyops-lab 密钥认证

---

## 1. 真实部署验收

| 步骤 | Release ID | 镜像 | 目标 VM | 状态 | 结果 |
|------|------------|------|---------|------|------|
| 首次部署 | #1 | nginx:1.27-alpine | VM1:18080 | succeeded | pull→up→healthcheck=healthy，HTTP 200 |
| 升级发布 | #2 | nginx:stable-alpine | VM1:18080 | succeeded | Container Recreate，健康检查通过 |
| 失败发布 | #3 | nginx:does-not-exist-9999 | VM1:18080 | failed | pull 报错 "No such image"，无非法步骤执行，不覆盖回滚点 |
| 回滚 | #4 (rollback) | → 恢复 #2 | VM1:18080 | rollback_succeeded | Container Running，healthcheck healthy，HTTP 200 |

**验证项**：
- deploy project 绑定 target_asset_id=1，RemoteComposeRunner 真实 SSH 连接
- build_script/deploy_script 未执行（安全）
- 失败发布不干扰回滚点（rollback #4 回到 #2，非 #3）
- 两台 VM 状态 Running

---

## 2. MySQL 备份与恢复验收

| 步骤 | Record ID | 类型 | 状态 | 结果 |
|------|-----------|------|------|------|
| 创建备份 | #4 | backup | succeeded | 17 tables/46 rows，checksum_ok=1，gzip_ok=true，SHA-256 已记录 |
| 数据破坏 | — | — | — | DROP TABLE e5_backup_probe（17→16表），UPDATE server_asset SET asset_name='tampered' |
| 恢复到全新库 | #6 | restore | succeeded | **easyops_restore** 库：17 tables/46 rows，consistent=true，target_database=easyops_restore |
| 一致性核验 | — | — | — | probe 表 3 行完整，asset_name='e5-node-1'（tampered 恢复），sys_user 1 行 |

**备份保护验证**：
- 损坏文件（corrupt gzip）：gzip_ok=false，ok=false（校验层拒绝）
- 篡改有效备份字节：checksum 从 887049aa 变为 88e8f423（校验变更检测），原文件未受影响
- API restore 端点只允许 checksum_ok=1 的 succeeded 备份，损坏记录无此标志

**备份持久化/权限/保留策略**：
- backup_data 卷挂载至 api + celery 双容器（共享）
- 文件权限：-rw-r--r--（644），目录 drwxr-xr-x（755）
- 保留策略：retention_count=7，按文件名排序淘汰旧文件
- 三件套：.sql + .sql.gz + .sha256，retention prune 清理时同步删除对应 .sql 和 .sha256
- 无明文密钥存储在卷中

---

## 3. E4 巡检证据与 Prometheus 真实指标

**同步巡检**（uvicorn 进程内执行，record #11）：
- VM1 (e5-node-1)：critical（缺 nginx 规则——环境准入阶段已知）
- VM2 (e5-node-2)：critical（同上）

**Prometheus 真实指标**（从 http://localhost:9090/api/v1/query 获取）：
- `easyops_inspection_hosts_total{status="critical"} = 2`
- `easyops_host_health{status="critical"} = 2`，healthy=0，warning=0，unknown=0
- `http_requests_total{handler="/api/v1/inspection/collect/sync", status="2xx"} = 1`

**Grafana**：Dashboard「EasyOps 概览」配置完整（8 面板，引用 http_requests_total / easyops_host_health / easyops_exec_tasks_total 等），数据源 Prometheus 已连接。Grafana image-renderer 插件未安装，无法生成 PNG 截图；已通过 Grafana API + Prometheus API 确认指标真实可查询，作为截图替代证据。

---

## 4. 测试矩阵

| 测试文件 | 用例数 | 状态 |
|----------|--------|------|
| tests/test_deploy.py（E5-P2 新增） | 4 | ✅ passed |
| tests/test_backup.py（E5-P2 新增） | 5 | ✅ passed |
| tests/test_migrations.py（0006） | 1 | ✅ passed |
| tests/test_inspection.py（同步巡检端点） | 23 | ✅ passed |
| 全量（135 passed） | 135 | ✅ 0 failed |

---

## 5. 代码变更摘要

**核心实现**：
- `deploy_service.py`：DeployPlan.target_asset_id，RemoteComposeRunner 真实远程部署
- `backup_service.py`：RealMySQLDumpEngine（dump/persist/restore/consistency_check），全新库恢复（DROP+CREATE easyops_restore），_enforce_retention 修复
- `deploy_tasks.py`：real 模式 RemoteComposeRunner，mock 保留骨架
- `backup_tasks.py`：real 模式 dump→persist→consistency_check，restore→全新库导入
- `config.py`：DEPLOY_EXECUTION_MODE/BACKUP_EXECUTION_MODE，BACKUP_STORAGE_DIR/RETENTION_COUNT
- `database/models.py`：DeployProject.target_asset_id，operator VARCHAR(20)
- `schemas/all.py`：DeployProjectCreate.target_asset_id

**迁移**：
- `alembic/versions/0005`：operator VARCHAR(20) + SSH fingerprint
- `alembic/versions/0006`：deploy_project.target_asset_id + index

**基础设施**：
- `docker-compose.yml`：api/celery 环境变量 real 模式，backup_data 卷 api+celery 共享
- `Dockerfile`：default-mysql-client（MariaDB）+ --skip-ssl（MySQL 8 自签名证书兼容）
- `api/v1/inspection.py`：POST /collect/sync 同步巡检端点（uvicorn 进程内）

---

## 6. 未完成边界与风险

- **Grafana 截图**：需安装 grafana-image-renderer 插件，当前以 API 验证代替
- **Prometheus 自定义指标**：巡检指标由同步端点在 API 进程内记录（与 worker 进程隔离），worker 独立指标未被 Prometheus 抓取（scrape 仅配 api:8000）
- **celery group dispatch**：kombu group()/dispatch 在 uvicorn 进程内有 pyamqp Connection refused 已知问题，sync 端点绕过此限制
- **operator VARCHAR(20)**：环境准入阶段已修，未改动其他字段
- **retention_count 变更需容器重建**：配置通过环境变量传入，不支持热更新
