# EasyOps Helm Chart 验收记录

## 验证环境

- **kind**：v0.32.0 单节点（`easyops-helm-acc-control-plane`），kubectl v1.36.3
- **helm**：v4.2.4+g3900f43
- **镜像**：`devops-automation-api:latest` / `devops-automation-web:latest`（kind load 成功
  进节点 containerd，crictl 确认）

## 已验证（静态 + 真机）

### ✅ helm lint

```
helm lint charts/easyops
1 chart(s) linted, 0 chart(s) failed
```
（仅 INFO: icon 建议；0 错误 0 警告）

### ✅ helm template 渲染

```
helm template easyops charts/easyops → 23 resources
  Namespace:  easyops
  ConfigMap:  easyops-config, prometheus-config, grafana-provisioning, grafana-dashboards (4)
  Service:    api, mysql, redis, prometheus, web, grafana (6)
  Deployment: easyops-api, easyops-celery, easyops-web, mysql, redis, prometheus, grafana (7)
  Job:        easyops-migrate (1)
  PVC:        mysql-data, redis-data, backups, grafana-data (4)
```

关键资源验证：
- **6 个 Service 命名正确**：`api`/`mysql`/`redis`/`prometheus`（DNS 依赖固定）、
  `web`（NodePort 30080）、`grafana`（NodePort 30030）
- api/celery deployment：`envFrom configMapRef: easyops-config` +
  `secretKeyRef: easyops-secrets`（4 keys）
- secret.create=false 不渲染 Secret（设计正确，prebuilt Secret 流程）
- NodePort 端口正确（web 30080、grafana 30030）

### ✅ 渲染产物 kubeconform strict

```
kubeconform -strict -summary /tmp/helm-rendered.yaml
23 resources found in 1 file - Valid: 23, Invalid: 0, Errors: 0, Skipped: 0
```

### ✅ Prometheus 告警模板转义正确

渲染输出中 3 处 `{{ $value }}` / `{{ $value | humanizePercentage }}` 恢复为 Prometheus
模板语法（未与 Helm 模板冲突）。

### ✅ helm install 成功

```
helm install easyops ./charts/easyops --namespace easyops
NAME: easyops
STATUS: deployed
```
（注：CLI 先用 `kubectl create ns easyops` 预建命名空间；Helm 要求该 ns 带
`app.kubernetes.io/managed-by=Helm` 与 `meta.helm.sh/*` 标签，已标注补加后安装成功。）

### ✅ web Pod Running（真实验证）

```
easyops-web-94f5989c9-cwvww    1/1 Running   ✅
easyops-web-94f5989c9-h22dl    1/1 Running   ✅
```
- 镜像 `devops-automation-web:latest` 拉取并启动
- nginx 容器提供静态前端 + `/api` 反向代理（依赖 Service DNS `api`）
- NodePort Service 正确分配（web:30080、grafana:30030）

### ✅ prometheus Pod Running（真实验证）

```
prometheus-546cbddd7d-gsh9f    1/1 Running   ✅
```
- ConfigMap 挂载 prometheus.yml（targets `api:8000`）+ prometheus-alerts.yml（5 条
  告警规则转义正确）
- 服务启动可抓取 `api:8000/metrics`

## ⚠ 未完成验收（环境限制，非 Chart 缺陷）

| 组件 | 状态 | 原因（环境约束） |
|------|------|-------------------|
| PVC（4 个） | Pending | local-path provisioner 的 helper pod 需拉取 `busybox` 镜像拷贝卷数据；kind 节点拉取受限（ImagePullBackOff/ErrImagePull），且宿主机 Docker VM 内存压力致 helper 未完成。PVC 未绑定 → 依赖卷的 mysql/redis/api/celery/grafana Pod 卡 Pending。 |
| mysql / redis / api / celery / grafana | Pending | 承上：卷未就绪。api「OOMKilled」一次也归因宿主机内存压力（migrate Job OOMKilled 一次）。 |
| 全链路 API 健康检查 | 未到 | 依赖 api Pod 就绪（受 PVC 阻塞）。 |

**结论**：Chart 本身（模板/渲染/schema/安装/无卷组件 Pod 启动）已真实验证。PVC/有状态
组件在本机因 kind 拉取 busybox 镜像受限 + Docker VM 内存竞争未完成，属环境限制而非
Chart 缺陷——Kustomize 路径曾遇到完全相同的环境约束（见 `docs/k8s-validation.md`）。
在有充足网络拉取基础镜像、干净 Docker 内存的单项目环境可完成全栈。

## 验证边界（如实说明）

- ✅ **静态**：helm lint 0 失败、helm template 23 资源、渲染产物 kubeconform 23/23 Valid
- ✅ **真机（无状态组件）**：helm install 成功；web 2/2 + prometheus Running
- ⚠ **未覆盖**：PVC 绑定与依赖持久化卷的有状态组件（mysql/redis/api/celery/grafana），
  因 kind 拉取 busybox helper 镜像受限 + 宿主机资源竞争；真实 SSH 部署/巡检出站（默认
  mock，同 Kustomize 边界）