# E5 受控部署模板：compose-web

本项目模板提供一个「受控」的 Docker Compose 部署骨架：所有构建/部署动作引用模板目录中的
受控命令，不直接执行项目 git 仓库里提交的任意脚本（build_script/deploy_script 仅作为
记录字段保留，不自动执行）。

模板结构：

```text
deploy_templates/compose-web/
├── docker-compose.yml   # 目标 compose 骨架：web（服务）+ 健康检查
└── steps.sh             # 受控步骤：pull → build → up → healthcheck → rollback
```

## 受控步骤（steps.sh）

只做以下固定动作，参数来自项目记录（镜像名/版本/端口），不允许任意 shell：

1. `pull`：拉取 `IMAGE:VERSION`；
2. `build`：基于模板内 Dockerfile（本模板默认直接使用已有镜像）构建 `IMAGE:VERSION-local`；
3. `up`：`docker compose -f docker-compose.generated.yml up -d`（用渲染后的配置）；
4. `healthcheck`：等待 `http://127.0.0.1:PORT/health/live` 返回 200，超时则标记失败；
5. `rollback`：用上一份有效 compose 配置重新 `up -d` 并再次健康检查。

> 说明：本模板为静态脚手架 + 服务端受控步骤编排；真实 `docker compose` 执行
> 归 E5 验收第二阶段（真实 Linux 演练），本阶段验证以 mock/静态证据为主。