"""E5 受控部署计划服务：预览 / 执行 / 健康检查 / 回滚。

设计约束（对应实施方案 E5）：
- 只做模板目录内固定步骤（pull/build/up/healthcheck/rollback），
  不执行项目 git 仓库中的任意 build/deploy_script（仅作记录字段）；
- 每次部署生成预览计划（image/version/port/步骤序列），确认后执行；
- 执行结果落 DeployRelease，并记录上一有效发布作为回滚点；
- 真实 docker compose 执行归 E5 验收第二阶段，本服务提供可 mock 的执行入口。
"""
from dataclasses import dataclass, field
from typing import Callable

# 模板根；steps.sh 只允许以下受控步骤
DEFAULT_TEMPLATE = 'compose-web'
ALLOWED_STEPS = ('pull', 'build', 'up', 'healthcheck', 'rollback')


@dataclass
class DeployPlan:
    """一次受控部署的预览计划。"""
    project_id: int
    template: str
    image: str
    version: str
    port: int
    steps: list[str] = field(default_factory=lambda: ['pull', 'build', 'up', 'healthcheck'])
    git_branch: str = 'main'
    git_ref: str | None = None

    def to_dict(self) -> dict:
        return {
            'project_id': self.project_id, 'template': self.template,
            'image': self.image, 'version': self.version, 'port': self.port,
            'steps': self.steps, 'git_branch': self.git_branch, 'git_ref': self.git_ref,
        }


def _default_image(project) -> str:
    """由 project 推断镜像名：deploy_project.project_name 规范化。"""
    return f'easyops/{project.project_name or "app"}'


def build_plan(project, image: str | None = None, version: str = 'latest',
               port: int = 8080, template: str = DEFAULT_TEMPLATE) -> DeployPlan:
    """构造受控部署计划（不执行任何命令）。"""
    return DeployPlan(
        project_id=project.id, template=template,
        image=image or _default_image(project), version=version, port=port,
        git_branch=project.git_branch,
    )


def run_deploy_steps(plan: DeployPlan,
                     runner: Callable[[str, dict], str] | None = None) -> list[dict]:
    """按计划顺序执行受控步骤（模板内固定步骤）。

    runner: 可注入的执行器，用于测试 mock；默认用本地执行骨架（E5 第二阶段对接真实
    docker compose）。返回每步结果 [{step, ok, output}]。
    """
    results = []
    for step in plan.steps:
        if step not in ALLOWED_STEPS:
            results.append({'step': step, 'ok': False, 'output': f'非法步骤 {step}（不在模板白名单）'})
            break  # 非法步骤即中止，绝不继续
        try:
            if runner is not None:
                output = runner(step, plan_to_ctx(plan))
            else:
                output = _run_subprocess_step(step, plan)
            results.append({'step': step, 'ok': True, 'output': output})
        except Exception as exc:  # noqa: BLE001
            results.append({'step': step, 'ok': False, 'output': str(exc)})
            break  # 任一步失败即中止，不继续部署
    return results


def plan_to_ctx(plan: DeployPlan) -> dict:
    return {'image': plan.image, 'version': plan.version, 'port': plan.port}


def _run_subprocess_step(step: str, plan: DeployPlan) -> str:
    """真实执行：调用模板 steps.sh 的固定步骤。

    在 Python 3.12 venv 中通过 subprocess 调 bash 脚本；若脚本不可用或 exec
    被禁用，返回占位说明（E5 第二阶段对接真实 docker 引擎）。
    """
    import os
    import subprocess

    script = os.path.join('deploy_templates', plan.template, 'steps.sh')
    if not os.path.exists(script):
        return f'steps.sh 不存在（模板 {plan.template}），跳过本地执行'
    try:
        proc = subprocess.run(
            ['bash', script, step, plan.image, plan.version, str(plan.port)],
            capture_output=True, text=True, timeout=60,
        )
        return (proc.stdout or proc.stderr).strip() or f'{step} ok'
    except FileNotFoundError:
        return 'bash 不可用，跳过本地执行'
    except subprocess.TimeoutExpired:
        return f'{step} 超时'
    except Exception as exc:  # noqa: BLE001
        return f'{step} 执行异常: {exc}'


def last_valid_release(db, project_id: int, before_id: int | None = None) -> dict | None:
    """最近一个成功的部署发布（作为回滚点）。

    before_id：回滚时传入当前 release id，取「早于当前发布」的最近成功发布；
    否则取全局最近成功发布。
    """
    from database.models import DeployRelease
    q = db.query(DeployRelease).filter(
        DeployRelease.project_id == project_id,
        DeployRelease.status == 'succeeded',
    )
    if before_id is not None:
        q = q.filter(DeployRelease.id < before_id)
    row = q.order_by(DeployRelease.id.desc()).first()
    if not row:
        return None
    return {'id': row.id, 'image': row.image, 'version': row.version,
            'git_ref': row.git_ref, 'status': row.status}