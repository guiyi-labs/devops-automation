"""E5 部署 Worker：执行受控步骤并落 DeployRelease 状态。

- mock 模式（DEPLOY_EXECUTION_MODE=mock，默认）：保留本地可复现骨架，供单元测试；
- real 模式（DEPLOY_EXECUTION_MODE=real，由 Compose 显式开启）：在项目绑定的
  ServerAsset 上经 SSH 执行模板固定步骤（pull/build/up/healthcheck），
  凭据解密后仅传进程，命令由 RemoteComposeRunner 拼接。
"""
import json

from tasks.celery_app import celery
from services import deploy_service


def _apply_results(release, results: list[dict]) -> tuple[bool, list[dict]]:
    """根据步骤结果决定状态：全部成功 → succeeded；healthcheck 失败仍视为失败。"""
    failed = [r for r in results if not r.get('ok')]
    ok = not failed
    status = 'succeeded' if ok else 'failed'
    return ok, json.loads(release.result or '{}') | {'steps': results, 'status': status}


def _load_plan(release) -> deploy_service.DeployPlan:
    """从发布记录恢复计划；缺失时回退默认模板参数。"""
    result_doc = json.loads(release.result or '{}')
    plan_dict = result_doc.get('plan') or {
        'project_id': release.project_id, 'template': deploy_service.DEFAULT_TEMPLATE,
        'image': release.image, 'version': release.version, 'port': 8080,
        'steps': ['pull', 'build', 'up', 'healthcheck'],
    }
    return deploy_service.DeployPlan(**plan_dict)


def _resolve_runner(db, plan: deploy_service.DeployPlan, release_id: int,
                    compose_release_id: int | None = None):
    """real 模式下构造远端执行器；绑定资产缺失或无 target_asset_id 时 fail-closed。"""
    from config import settings
    if not settings.deploy_uses_real_executor():
        return None
    from common.crypto import decrypt_value
    from database.models import ServerAsset
    if plan.target_asset_id is None:
        raise RuntimeError('real 部署必须绑定目标资产（target_asset_id）')
    asset = db.query(ServerAsset).filter(ServerAsset.id == plan.target_asset_id).first()
    if not asset:
        raise RuntimeError(f'目标资产不存在: target_asset_id={plan.target_asset_id}')
    if not asset.host_key_fingerprint:
        raise RuntimeError(f'资产未登记 host key 指纹: {asset.ip_address}')
    return deploy_service.RemoteComposeRunner(
        asset=asset,
        plan=plan,
        release_id=release_id,
        compose_release_id=compose_release_id,
        password=decrypt_value(asset.ssh_pwd) if asset.ssh_pwd else None,
        private_key=decrypt_value(asset.ssh_key) if asset.ssh_key else None,
    )


@celery.task(bind=True, max_retries=0, soft_time_limit=150, time_limit=180)
def run_deploy_release(self, release_id: int) -> dict:
    """执行发布计划的受控步骤（pull/build/up/healthcheck）。"""
    from common.redact import redact
    from database.models import DeployProject, DeployRelease
    from database.session import SessionLocal

    db = SessionLocal()
    try:
        release = db.query(DeployRelease).filter(DeployRelease.id == release_id).first()
        if not release:
            return {'release_id': release_id, 'error': '发布记录不存在', 'status': 'missing'}
        release.status = 'running'
        db.commit()
        project = db.query(DeployProject).filter(DeployProject.id == release.project_id).first()

        plan = _load_plan(release)
        runner = _resolve_runner(db, plan, release_id)
        if runner is not None:
            mode = 'real'
            steps = ['pull', 'build', 'up', 'healthcheck']
            plan.steps = steps
            results = deploy_service.run_deploy_steps(plan, runner=runner)
            digest = runner.image_digest()
        else:
            mode = 'mock'
            results = deploy_service.run_deploy_steps(plan)
            digest = f'sha256:mock-{release_id}'

        ok, merged = _apply_results(release, results)
        merged['mode'] = mode
        release.status = 'succeeded' if ok else 'failed'
        release.image_digest = digest if ok else None
        release.git_ref = project.git_branch if project else None
        release.result = json.dumps(merged, ensure_ascii=False)
        db.commit()
        return {'release_id': release_id, 'status': release.status,
                'steps': [{'step': r['step'], 'ok': r['ok']} for r in results]}
    except Exception as exc:  # noqa: BLE001
        try:
            release = db.query(DeployRelease).filter(DeployRelease.id == release_id).first()
            if release:
                release.status = 'failed'
                release.result = json.dumps({'error': redact(str(exc))}, ensure_ascii=False)
                db.commit()
        except Exception:  # noqa: BLE001
            pass
        return {'release_id': release_id, 'error': redact(str(exc)), 'status': 'failed'}
    finally:
        db.close()


@celery.task(bind=True, max_retries=0, soft_time_limit=120, time_limit=180)
def run_rollback_release(self, rollback_id: int) -> dict:
    """执行回滚：将 rollback 记录状态置为 succeeded（受控步骤 rollback + healthcheck）。"""
    from common.redact import redact
    from database.models import DeployRelease, DeployProject
    from database.session import SessionLocal

    db = SessionLocal()
    try:
        rollback = db.query(DeployRelease).filter(DeployRelease.id == rollback_id).first()
        if not rollback:
            return {'rollback_id': rollback_id, 'status': 'missing'}
        rollback.status = 'running'
        db.commit()

        project = db.query(DeployProject).filter(DeployProject.id == rollback.project_id).first()
        # 回滚点：result JSON 中记录 rollback_to（目标 release id）
        result_doc = json.loads(rollback.result or '{}')
        target_release_id = result_doc.get('rollback_to')
        plan = deploy_service.DeployPlan(
            project_id=rollback.project_id,
            template=deploy_service.DEFAULT_TEMPLATE,
            image=rollback.image or 'easyops/app',
            version=rollback.version or 'latest',
            port=8080,
            steps=['rollback', 'healthcheck'],
            target_asset_id=getattr(project, 'target_asset_id', None),
        )

        runner = _resolve_runner(db, plan, rollback_id, compose_release_id=target_release_id)
        if runner is not None:
            results = deploy_service.run_deploy_steps(plan, runner=runner)
            mode = 'real'
        else:
            # mock：固定成功（保持既有测试语义）
            results = [
                {'step': 'rollback', 'ok': True, 'output': 'rollback ok'},
                {'step': 'healthcheck', 'ok': True, 'output': 'healthy'},
            ]
            mode = 'mock'

        ok, merged = _apply_results(rollback, results)
        merged['mode'] = mode
        rollback.status = 'rollback_succeeded' if ok else 'rollback_failed'
        rollback.result = json.dumps(merged, ensure_ascii=False)
        db.commit()
        return {'rollback_id': rollback_id, 'status': rollback.status,
                'steps': [{'step': r['step'], 'ok': r['ok']} for r in results]}
    except Exception as exc:  # noqa: BLE001
        try:
            rollback = db.query(DeployRelease).filter(DeployRelease.id == rollback_id).first()
            if rollback:
                rollback.status = 'rollback_failed'
                rollback.result = json.dumps({'error': redact(str(exc))}, ensure_ascii=False)
                db.commit()
        except Exception:  # noqa: BLE001
            pass
        return {'rollback_id': rollback_id, 'error': redact(str(exc)), 'status': 'rollback_failed'}
    finally:
        db.close()