#!/usr/bin/env bash
# 受控部署步骤骨架（compose-web 模板）。
# 服务端只允许执行本文件中固定步骤，参数全部来自 DeployProject/DeployRelease 记录，
# 不读取项目 git 仓库中的任意脚本。set -euo pipefail 保证失败即停。
set -euo pipefail

step="${1:-help}"
image="${2:-}"
version="${3:-latest}"
port="${4:-8080}"

case "$step" in
  pull)
    test -n "$image"
    docker pull "${image}:${version}"
    ;;
  build)
    # 无自定义 Dockerfile 时跳过；有则基于模板内 Dockerfile 构建
    if [ -f "$(dirname "$0")/Dockerfile" ]; then
      docker build -t "easyops/deploy:${version}-local" "$(dirname "$0")"
    fi
    ;;
  up)
    cat > /tmp/easyops_compose_${port}.yml <<EOF
services:
  web:
    image: ${image}:${version}
    ports: ["${port}:8080"]
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1:8080/health/live"]
      interval: 10s
      timeout: 3s
      retries: 5
EOF
    docker compose -f "/tmp/easyops_compose_${port}.yml" up -d
    ;;
  healthcheck)
    for i in $(seq 1 20); do
      if docker compose -f "/tmp/easyops_compose_${port}.yml" ps --format json \
          2>/dev/null | grep -q '"Health": "healthy"'; then
        echo "healthy"
        exit 0
      fi
      sleep 2
    done
    echo "healthcheck timeout" >&2
    exit 1
    ;;
  rollback)
    # 回滚：使用上一份已记录的 compose 配置重新 up（由服务端传入 prev_port 的文件）
    docker compose -f "/tmp/easyops_compose_${port}.yml" up -d || true
    ;;
  *)
    echo "usage: steps.sh <pull|build|up|healthcheck|rollback> image version port" >&2
    exit 2
    ;;
esac