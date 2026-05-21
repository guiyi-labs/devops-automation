#!/usr/bin/env bash
set -euo pipefail

# EasyOps Rocky Linux 在线修复脚本
# 适用场景：测试 Linux 服务器正在运行 EasyOps，需要修复 web 镜像构建时报
# `sh: vite: Permission denied` 的问题，并重新构建/启动 web 服务。

PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
WEB_DIR="${PROJECT_DIR}/easyops_web"

echo "[EasyOps] 当前项目目录: ${PROJECT_DIR}"

if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] 未检测到 docker 命令，请先在 Rocky Linux 上安装 Docker Engine。" >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "[ERROR] 未检测到 Docker Compose v2，请确认 docker compose 命令可用。" >&2
  exit 1
fi

if [ ! -d "${WEB_DIR}" ]; then
  echo "[ERROR] 未找到 easyops_web 目录，请在 EasyOps 项目根目录执行本脚本。" >&2
  exit 1
fi

echo "[EasyOps] 写入 easyops_web/.dockerignore，排除宿主机构建产物..."
cat > "${WEB_DIR}/.dockerignore" <<'DOCKERIGNORE'
node_modules
dist
.vite
npm-debug.log*
yarn-debug.log*
yarn-error.log*
.DS_Store
DOCKERIGNORE

echo "[EasyOps] 检查并修复 easyops_web/Dockerfile..."
python3 - <<'PY'
from pathlib import Path

path = Path('easyops_web/Dockerfile')
text = path.read_text(encoding='utf-8')
text = text.replace('COPY package.json ./', 'COPY package*.json ./')
text = text.replace('RUN npm run build', 'RUN chmod -R +x node_modules/.bin && npm run build')
path.write_text(text, encoding='utf-8')
PY

echo "[EasyOps] 清理宿主机前端依赖与构建缓存，避免污染 Docker 构建上下文..."
rm -rf "${WEB_DIR}/node_modules" "${WEB_DIR}/dist" "${WEB_DIR}/.vite"

echo "[EasyOps] 重新构建 web 镜像..."
docker compose build --no-cache web

echo "[EasyOps] 重启 web 服务..."
docker compose up -d web

echo "[EasyOps] 当前 web 服务状态:"
docker compose ps web

echo "[EasyOps] 最近 web 日志:"
docker compose logs --tail=80 web

echo "[EasyOps] 修复完成。请访问 http://服务器IP:8080 验证前端页面。"