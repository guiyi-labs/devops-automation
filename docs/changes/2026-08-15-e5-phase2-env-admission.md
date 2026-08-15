# E5 第二阶段环境准入报告

| 项 | 值 |
|---|---|
| 日期 | 2026-08-15 |
| 分支 | feat/e5-phase2-env-admission |
| PR | #6 |
| 基线 | main @ 7359e02 |

## 一、环境与版本

两台全新隔离的 Ubuntu 24.04.4 LTS x86_64 Lima VM（qemu，各 4 vCPU / 6GiB / 40GiB）为被管目标；EasyOps 控制端本地 Docker Compose（API + Celery + MySQL 8.0 + Redis 6 + Prometheus + Grafana）。目标 docker 29.7.2 + compose v5.4.0。

## 二、easyops-lab 专用用户

两台 VM 均创建 easyops-lab：仅密钥登录、无 sudo、加入 docker 组。私钥 ed25519 仅存 ~/.easyops-lab/（gitignored），公钥入 authorized_keys，sshd 密码认证保持拒绝。

## 三、SSH host-key 指纹校验

Worker 容器内真实 SSH 路径验证：DNS 解析 host.docker.internal → TCP 连通 → paramiko 连接严格比对指纹 → 密钥认证 → id/docker。指纹已记录于本地 inventory：
- e5-node-1: 50hsdh7MRTAw4enuYxvg6lD+kZ8I10Yjw5eY7LkhpHo=
- e5-node-2: qbtBnLUgEkn64cXa4U4jMAMpvhsJWUhZJHti8cnhMo0=

## 四、Docker 运行结果

两台 VM 均验证 docker version（server 29.7.2/client 29.7.2）与 docker run --rm hello-world 成功，sudo 被拒绝。

## 五、E4 巡检结果

两资产在 API 容器内完成事实采集并落库（record #8）：Ubuntu 24.04.4、kernel 6.8.0-134、4 核、5.9GiB 内存（8.8%）、磁盘 7.0%、端口 22/53、active_services 含 docker/containerd。整体 critical（默认规则检测未运行的 nginx——预期）。

## 六、动态端口复现方式

limactl show-ssh <name> 重新获取；host-key ssh-keyscan 复核；inventory 存 ~/.easyops-lab/inventory.env。

## 七、Secret 存放策略

SSH 私钥、动态端口、host-key、inventory 全部位于 ~/.easyops-lab/（gitignored/仓库外）；凭据经 Fernet 加密落库；不提交备份原文件与真实 IP。

## 八、工作树状态

本报告分支已推送 PR #6（工作树干净）。环境准入修复（paramiko 5 host-key 签名、operator VARCHAR(20)+迁移 0005+回归测试）已提交。
