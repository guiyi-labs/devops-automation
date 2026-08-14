from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database.models import DeployProject, SysUser
from database.session import get_db
from dependencies import get_current_user, require_write
from schemas.all import DeployProjectCreate, DeployProjectOut

router = APIRouter()


@router.get('/projects', response_model=list[DeployProjectOut])
def list_projects(user: SysUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(DeployProject).order_by(DeployProject.id.desc()).all()


@router.post('/projects', response_model=DeployProjectOut)
def create_project(payload: DeployProjectCreate, user: SysUser = Depends(require_write), db: Session = Depends(get_db)):
    item = DeployProject(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.post('/projects/{project_id}/run')
def run_deploy(project_id: int, user: SysUser = Depends(require_write)):
    return {'project_id': project_id, 'status': 'submitted'}