"""E5 受控部署计划、真实远端 Compose 执行和回滚辅助。

安全边界：真实执行只接受已登记资产，命令仅由本模块拼接；项目的
``build_script`` / ``deploy_script`` 永不读取或执行。模板名称、镜像、版本和端口
在进入 shell 前全部校验，远端 compose 文件由 base64 内容写入固定工作目录。
"""
from __future__ import annotations

import base64
import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from typing import Callable

from common.redact import redact
from services.ssh_service import connect_and_run

DEFAULT_TEMPLATE = 'compose-web'
SUPPORTED_TEMPLATES = (DEFAULT_TEMPLATE,)
ALLOWED_STEPS = ('pull', 'build', 'up', 'healthcheck', 'rollback')

_IMAGE_RE = re.compile(r'^[a-z0-9][a-z0-9._/-]{0,240}$')
_VERSION_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$')


@dataclass
class DeployPlan:
    """一次只包含固定模板步骤的部署预览。"""

    project_id: int
    template: str
    image: str
    version: str
    port: int
    steps: list[str] = field(default_factory=lambda: ['pull', 'build', 'up', 'healthcheck'])
    git_branch: str = 'main'
    git_ref: str | None = None
    target_asset_id: int | None = None

    def to_dict(self) -> dict:
        return {
            'project_id': self.project_id,
            'template': self.template,
            'image': self.image,
            'version': self.version,
            'port': self.port,
            'steps': self.steps,
            'git_branch': self.git_branch,
            'git_ref': self.git_ref,
            'target_asset_id': self.target_asset_id,
        }


def _default_image(project) -> str:
    return f'easyops/{project.project_name or "app"}'


def validate_plan(plan: DeployPlan) -> None:
    """在命令执行前校验所有可能影响 shell 的输入（不校验步骤列表，步骤在循环逐项白名单）。"""
    if plan.template not in SUPPORTED_TEMPLATES:
        raise ValueError(f'不支持的部署模板: {plan.template}')
    if not _IMAGE_RE.fullmatch(plan.image):
        raise ValueError('镜像名只允许小写字母、数字、点、下划线、短横线和斜杠')
    if not _VERSION_RE.fullmatch(plan.version):
        raise ValueError('镜像版本只允许字母、数字、点、下划线和短横线')
    if not isinstance(plan.port, int) or not 1024 <= plan.port <= 65535:
        raise ValueError('部署端口必须在 1024-65535 范围内')


def build_plan(project, image: str | None = None, version: str = 'latest',
               port: int = 8080, template: str = DEFAULT_TEMPLATE) -> DeployPlan:
    """构造受控计划，不从项目记录执行任意脚本。"""
    plan = DeployPlan(
        project_id=project.id,
        template=template,
        image=image or _default_image(project),
        version=version,
        port=port,
        git_branch=project.git_branch,
        target_asset_id=getattr(project, 'target_asset_id', None),
    )
    validate_plan(plan)
    return plan


def plan_to_ctx(plan: DeployPlan) -> dict:
    return {
        'image': plan.image,
        'version': plan.version,
        'port': plan.port,
        'target_asset_id': plan.target_asset_id,
    }


def run_deploy_steps(plan: DeployPlan,
                     runner: Callable[[str, dict], str] | None = None) -> list[dict]:
    """按白名单执行；首个失败立即终止，绝不继续后续步骤。"""
    results: list[dict] = []
    try:
        validate_plan(plan)
    except ValueError as exc:
        return [{'step': 'validate', 'ok': False, 'output': str(exc)}]

    for step in plan.steps:
        if step not in ALLOWED_STEPS:
            results.append({'step': step, 'ok': False, 'output': f'非法步骤 {step}（不在模板白名单）'})
            break
        try:
            output = runner(step, plan_to_ctx(plan)) if runner else _run_subprocess_step(step, plan)
            results.append({'step': step, 'ok': True, 'output': redact(output)})
        except Exception as exc:  # noqa: BLE001
            results.append({'step': step, 'ok': False, 'output': redact(str(exc))})
            break
    return results


def _run_subprocess_step(step: str, plan: DeployPlan) -> str:
    """mock/local 骨架：调用模板 steps.sh；不存在则返回占位（仅 mock 模式调用）。"""
    script = os.path.join('deploy_templates', plan.template, 'steps.sh')
    if not os.path.exists(script):
        return f'steps.sh 不存在（模板 {plan.template}），跳过本地执行（mock）'
    try:
        proc = subprocess.run(
            ['bash', script, step, plan.image, plan.version, str(plan.port)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f'{step} 超时') from exc
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or f'{step} 执行失败').strip())
    return (proc.stdout or proc.stderr).strip() or f'{step} ok'


def _compose_document(plan: DeployPlan) -> str:
    """受控模板的唯一 Compose 内容；不接受项目仓库中的脚本或文件。"""
    image_ref = f'{plan.image}:{plan.version}'
    return f'''services:
  web:
    image: {image_ref}
    ports:
      - "127.0.0.1:{plan.port}:80"
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "wget -q -O /dev/null http://127.0.0.1/ || exit 1"]
      interval: 5s
      timeout: 3s
      retries: 12
      start_period: 5s
'''


class RemoteComposeRunner:
    """在一台已登记资产上运行模板固定步骤。"""

    def __init__(self, *, asset, plan: DeployPlan, release_id: int,
                 password: str | None, private_key: str | None,
                 compose_release_id: int | None = None):
        validate_plan(plan)
        self.asset = asset
        self.plan = plan
        self.release_id = release_id
        self.compose_release_id = compose_release_id or release_id
        self.password = password
        self.private_key = private_key
        self.project_key = f'easyops-p{plan.project_id}'

    @property
    def image_ref(self) -> str:
        return f'{self.plan.image}:{self.plan.version}'

    @property
    def _root_expr(self) -> str:
        return f'$HOME/.easyops/e5/p{self.plan.project_id}'

    @property
    def _compose_name(self) -> str:
        return f'release-{self.compose_release_id}.yml'

    def __call__(self, step: str, _ctx: dict) -> str:
        if step == 'pull':
            return self._run(f'docker pull {shlex.quote(self.image_ref)}')
        if step == 'build':
            return '模板使用固定镜像；未执行项目 build_script/deploy_script'
        if step == 'up':
            return self._run(self._up_command())
        if step == 'healthcheck':
            return self._run(self._healthcheck_command())
        if step == 'rollback':
            return self._run(self._rollback_command())
        raise ValueError(f'非法步骤 {step}')

    def _run(self, command: str) -> str:
        result = connect_and_run(
            self.asset.ip_address,
            port=self.asset.ssh_port,
            user=self.asset.ssh_user,
            password=self.password,
            private_key=self.private_key,
            cmd=command,
            host_key_fingerprint=self.asset.host_key_fingerprint,
            timeout=30,
            cmd_timeout=120,
        )
        return (result.get('stdout') or result.get('stderr') or 'ok').strip()

    def _up_command(self) -> str:
        payload = base64.b64encode(_compose_document(self.plan).encode('utf-8')).decode('ascii')
        project = shlex.quote(self.project_key)
        image = shlex.quote(self.image_ref)
        return (
            'set -eu; '
            f'root="{self._root_expr}"; '
            'install -d -m 700 "$root"; '
            f'printf %s {shlex.quote(payload)} | base64 -d > "$root/{self._compose_name}"; '
            f'chmod 600 "$root/{self._compose_name}"; '
            f'docker image inspect {image} >/dev/null; '
            f'docker compose -p {project} -f "$root/{self._compose_name}" up -d --remove-orphans'
        )

    def _healthcheck_command(self) -> str:
        project = shlex.quote(self.project_key)
        return (
            'set -eu; '
            f'root="{self._root_expr}"; '
            f'container="$(docker compose -p {project} -f "$root/{self._compose_name}" ps -q web)"; '
            'test -n "$container"; '
            'for attempt in $(seq 1 30); do '
            'state="$(docker inspect --format "{{.State.Health.Status}}" "$container")"; '
            'if [ "$state" = healthy ]; then echo healthy; exit 0; fi; '
            'if [ "$state" = unhealthy ]; then echo unhealthy >&2; exit 1; fi; '
            'sleep 2; '
            'done; echo healthcheck-timeout >&2; exit 1'
        )

    def _rollback_command(self) -> str:
        project = shlex.quote(self.project_key)
        return (
            'set -eu; '
            f'root="{self._root_expr}"; '
            f'test -f "$root/{self._compose_name}"; '
            f'docker compose -p {project} -f "$root/{self._compose_name}" up -d --remove-orphans'
        )

    def image_digest(self) -> str:
        command = (
            f'docker image inspect --format "{{{{index .RepoDigests 0}}}}" {shlex.quote(self.image_ref)} '
            f'|| docker image inspect --format "{{{{.Id}}}}" {shlex.quote(self.image_ref)}'
        )
        return self._run(command)

    def evidence_path(self) -> str:
        return f'$HOME/.easyops/e5/p{self.plan.project_id}/{self._compose_name}'


def last_valid_release(db, project_id: int, before_id: int | None = None) -> dict | None:
    """返回指定项目中、当前 release 前的最近成功发布。"""
    from database.models import DeployRelease

    query = db.query(DeployRelease).filter(
        DeployRelease.project_id == project_id,
        DeployRelease.status == 'succeeded',
    )
    if before_id is not None:
        query = query.filter(DeployRelease.id < before_id)
    row = query.order_by(DeployRelease.id.desc()).first()
    if not row:
        return None
    return {
        'id': row.id,
        'image': row.image,
        'version': row.version,
        'git_ref': row.git_ref,
        'status': row.status,
        'result': row.result,
    }
