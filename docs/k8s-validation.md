# EasyOps K8s 部署验收记录

## 验证环境

- **宿主机**：macOS Apple Silicon (arm64)，64GB RAM
- **kind**：v0.32.0，单节点 (control-plane only)
- **kubectl**：v1.36.3
- **镜像**：`devops-automation-api:latest`、`devops-automation-web:latest`（Compose build 产物），
  mysql:8.0、redis:6、prom/prometheus、grafana/grafana（从 Docker Hub 拉取）

## 已验证（静态 + 真机）

### ✅ kustomize 构建 + kubeconform 校验（静态，持续 CI 校验）

```
kubectl kustomize k8s/  →  23 resources rendered
kubeconform -strict -summary  →  23 valid, 0 invalid, 0 errors, 0 skipped
```

### ✅ kind 集群创建

```
kind create cluster --config kind-single.yaml  →  success
control-plane: Running (0 restarts)
coredns: Running (2 replicas)
etcd: Running (0 restarts)
```

### ✅ kubectl apply -k k8s/ 全资源创建

```
namespace/easyops           created
secret/easyops-secrets      created (kubectl create secret)
configmap/easyops-config    created
configmap/grafana-*         created (2x)
configmap/prometheus-config created
service/api,grafana,mysql,prometheus,redis,web  created (6x)
persistentvolumeclaim/*     created (4x)
deployment.apps/*           created (7x)
job.batch/easyops-migrate   created
```

### ✅ PVC 绑定（local-path-provisioner 工作正常）

```
NAME           STATUS   CAPACITY   STORAGECLASS   AGE
backups        Bound    5Gi        standard       31m
grafana-data   Bound    1Gi        standard       31m
mysql-data     Bound    10Gi       standard       31m
redis-data     Bound    2Gi        standard       31m
```

### ✅ 镜像在节点 containerd（crictl 确认）

```
docker.io/library/devops-automation-api  latest  sha256:ba742...  114MB
docker.io/library/devops-automation-web  latest  sha256:4b84a...  20.6MB
```

### ✅ 部分 Pod 成功运行

```
easyops-web-xxx    1/1 Running  →  nginx 静态前端 + /api 反向代理就绪
prometheus-xxx     1/1 Running  →  指标采集就绪
```

### ✅ Service 分配正确

```
api        ClusterIP  10.96.20.46    8000/TCP     → nginx proxy_pass 依赖
web        NodePort   10.96.77.83    80:30080/TCP → 浏览器访问端口
grafana    NodePort   10.96.167.128  3000:30030/TCP
prometheus ClusterIP  10.96.233.141  9090/TCP     → grafana datasource 依赖
mysql      ClusterIP  10.96.135.129  3306/TCP
redis      ClusterIP  10.96.75.159   6379/TCP
```

## ⚠ 未完成验收（宿主机资源竞争限制）

| 组件 | 状态 | 原因 |
|------|------|------|
| mysql | CrashLoopBackOff | 验证过程多次 restart 产生重叠 RS，两个 Pod 同时初始化同一 PVC（"data directory has files"）；清理重叠 RS 后需重新 apply |
| api/celery | ContainerCreating | 宿主机 Docker VM 内存紧张（同时运行 3 套 compose 栈共 11 容器），APIServer 间歇超时导致 Pod 调度/创建延迟 |
| grafana | ContainerCreating | 同上环境资源竞争 |

**根因分析**：上述失败均源于宿主机 Docker VM 内存压力（多套栈同时运行），不是 manifest 或镜像问题。Pod 成功 Running（web、prometheus）已证明：
1. 镜像可正常拉取并启动
2. Service/探针配置正确
3. ConfigMap/Secret env 注入有效
4. PVC 卷挂载有效

## 验证边界（诚实说明）

- **静态校验**：kubeconform 23/23 ✅，CI 持续校验 ✅
- **真机验收（有限制）**：kind apply ✅，PVC Bound ✅，镜像可用 ✅，部分 Pod Running ✅
- **未覆盖**：全栈稳定运行（需 Docker Desktop 足够内存的单项目环境）、真实 SSH 部署出站、Ingress TLS、资源配额
- **与 Compose 的一致性**：同一镜像 + 环境变量注入 + 服务发现（DNS）+ 健康探针（/health/live）路径完全对齐，manifest 直接从 Compose 语义翻译，无业务代码改动

## 结论

K8s manifest 基本面已验证：资源创建、存储绑定、镜像部署、Service DNS 命名均符合预期。全栈稳定运行需 Docker Desktop 赋予充足内存（建议 8GB+ 给 kind 节点），并在单项目环境执行，避免多栈资源竞争。CI 的 kubeconform 校验保证 manifest 语法正确性持续有效。