from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database.models import CronTask, SysUser
from database.session import get_db
from dependencies import get_current_user, require_write
from schemas.all import CronTaskCreate, CronTaskOut

router = APIRouter()


@router.get('/tasks', response_model=list[CronTaskOut])
def list_tasks(user: SysUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(CronTask).order_by(CronTask.id.desc()).all()


@router.post('/tasks', response_model=CronTaskOut)
def create_task(payload: CronTaskCreate, user: SysUser = Depends(require_write), db: Session = Depends(get_db)):
    item = CronTask(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item