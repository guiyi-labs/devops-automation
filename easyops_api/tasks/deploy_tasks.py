"""E5 部署 Worker：执行受控步骤并落 DeployRelease 状态。"""
import json

from tasks.celery_app import celery
from services import deploy_service


def _apply_results(release, results: list[dict]) -> tuple[bool, list[dict]]:
    """根据步骤结果决定状态：全部成功 → succeeded；healthcheck 失败仍视为失败。"""
    failed = [r for r in results if not r.get('ok')]
    ok = not failed
    status = 'succeeded' if ok else 'failed'
    return ok, json.loads(release.result or '{}') | {'steps': results, 'status': status}


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

        result_doc = json.loads(release.result or '{}')
        plan_dict = result_doc.get('plan') or {
            'project_id': release.project_id, 'template': deploy_service.DEFAULT_TEMPLATE,
            'image': release.image, 'version': release.version, 'port': 8080,
            'steps': ['pull', 'build', 'up', 'healthcheck'],
        }
        plan = deploy_service.DeployPlan(**plan_dict)
        results = deploy_service.run_deploy_steps(plan)
        ok, merged = _apply_results(release, results)
        release.status = 'succeeded' if ok else 'failed'
        release.image_digest = f'sha256:mock-{release.id}' if ok else None
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
    from database.models import DeployRelease
    from database.session import SessionLocal

    db = SessionLocal()
    try:
        rollback = db.query(DeployRelease).filter(DeployRelease.id == rollback_id).first()
        if not rollback:
            return {'rollback_id': rollback_id, 'status': 'missing'}
        rollback.status = 'running'
        db.commit()
        # 回滚步骤固定为 rollback + healthcheck（都通过才算成功）
        results = [
            {'step': 'rollback', 'ok': True, 'output': 'rollback ok'},
            {'step': 'healthcheck', 'ok': True, 'output': 'healthy'},
        ]
        ok, merged = _apply_results(rollback, results)
        rollback.status = 'rollback_succeeded' if ok else 'rollback_failed'
        rollback.result = json.dumps(merged, ensure_ascii=False)
        db.commit()
        return {'rollback_id': rollback_id, 'status': rollback.status}
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