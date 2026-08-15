"""E5 受控部署 API：预览计划 / 执行发布 / 记录回滚点 / 回滚。

把 E2 占位 `POST /projects/{id}/run`（返回 submitted）改为受控部署计划：
POST /projects/{id}/preview 生成计划，POST /releases 执行发布（Celery），
GET /releases 查记录，POST /releases/{id}/rollback 回滚。
"""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database.models import DeployProject, DeployRelease, SysUser
from database.session import get_db
from dependencies import get_current_user, require_write
from schemas.all import DeployProjectCreate, DeployReleaseOut
from services import deploy_service

router = APIRouter()


def _audit(request, db, username, action, status_code, detail) -> None:
    from database.models import AuditLog
    db.add(AuditLog(username=username, action=action, method=request.method,
                    path=str(request.url.path)[:255], status_code=status_code,
                    ip_address=request.client.host if request.client else None,
                    detail=detail[:512]))
    db.commit()


def _get_project(db, project_id):
    project = db.query(DeployProject).filter(DeployProject.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail='部署项目不存在')
    return project


@router.get('/projects')
def list_projects(user: SysUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(DeployProject).order_by(DeployProject.id.desc()).all()


@router.post('/projects')
def create_project(payload: DeployProjectCreate, user: SysUser = Depends(require_write),
                   db: Session = Depends(get_db)):
    item = DeployProject(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.post('/projects/{project_id}/preview')
def preview_deploy(project_id: int, body: dict | None = None, request: Request = None,
                   user: SysUser = Depends(require_write), db: Session = Depends(get_db)):
    """生成受控部署预览计划（不执行任何命令）。"""
    body = body or {}
    project = _get_project(db, project_id)
    plan = deploy_service.build_plan(
        project,
        image=body.get('image'), version=body.get('version', 'latest'),
        port=int(body.get('port', 8080)), template=body.get('template', deploy_service.DEFAULT_TEMPLATE),
    )
    _audit(request, db, user.username, 'deploy_preview', 200, f'预览部署计划 {project.project_name}')
    return {'plan': plan.to_dict(), 'rollback_point': deploy_service.last_valid_release(db, project_id)}


@router.post('/releases')
def create_release(payload: dict, request: Request, user: SysUser = Depends(require_write),
                   db: Session = Depends(get_db)):
    """按预览计划参数创建发布记录并派发 Celery 部署。"""
    project = _get_project(db, int(payload.get('project_id')))
    plan = deploy_service.build_plan(
        project,
        image=payload.get('image'), version=payload.get('version', 'latest'),
        port=int(payload.get('port', 8080)),
        template=payload.get('template', deploy_service.DEFAULT_TEMPLATE),
    )
    release = DeployRelease(
        project_id=project.id, release_type='deploy', status='requested',
        image=plan.image, version=plan.version,
        exec_user=user.username, result=json.dumps({'plan': plan.to_dict()}, ensure_ascii=False),
    )
    db.add(release)
    db.commit()
    db.refresh(release)

    from tasks.deploy_tasks import run_deploy_release
    run_deploy_release.delay(release.id)

    _audit(request, db, user.username, 'deploy_release', 200,
           f'触发部署 {plan.image}:{plan.version}（release #{release.id}）')
    return {'release_id': release.id, 'status': release.status}


@router.get('/projects/{project_id}/releases', response_model=list[DeployReleaseOut])
def list_releases(project_id: int, user: SysUser = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    _get_project(db, project_id)
    return db.query(DeployRelease).filter(
        DeployRelease.project_id == project_id).order_by(DeployRelease.id.desc()).all()


@router.get('/releases/{release_id}', response_model=DeployReleaseOut)
def get_release(release_id: int, user: SysUser = Depends(get_current_user),
                db: Session = Depends(get_db)):
    release = db.query(DeployRelease).filter(DeployRelease.id == release_id).first()
    if not release:
        raise HTTPException(status_code=404, detail='发布记录不存在')
    return release


@router.post('/releases/{release_id}/rollback')
def rollback_release(release_id: int, request: Request, user: SysUser = Depends(require_write),
                     db: Session = Depends(get_db)):
    """回滚到该发布之前的最近一个成功发布。"""
    release = db.query(DeployRelease).filter(DeployRelease.id == release_id).first()
    if not release:
        raise HTTPException(status_code=404, detail='发布记录不存在')
    point = deploy_service.last_valid_release(db, release.project_id, before_id=release.id)
    if not point:
        raise HTTPException(status_code=400, detail='无有效回滚点（该项目还没有成功发布）')
    rollback = DeployRelease(
        project_id=release.project_id, release_type='rollback', status='requested',
        image=point['image'], version=point['version'], git_ref=point['git_ref'],
        exec_user=user.username,
        result=json.dumps({'rollback_to': point['id'], 'rollback_release': release.id},
                          ensure_ascii=False),
    )
    db.add(rollback)
    db.commit()
    db.refresh(rollback)

    from tasks.deploy_tasks import run_rollback_release
    run_rollback_release.delay(rollback.id)

    _audit(request, db, user.username, 'deploy_rollback', 200,
           f'回滚 release #{release.id} 到 #{point["id"]}（rollback #{rollback.id}）')
    return {'rollback_id': rollback.id, 'rollback_to': point['id'], 'status': rollback.status}


@router.get('/templates')
def list_templates(user: SysUser = Depends(get_current_user)):
    """可用的受控部署模板（静态清单，模板目录必须已存在）。"""
    return {'templates': ['compose-web'], 'default': deploy_service.DEFAULT_TEMPLATE}