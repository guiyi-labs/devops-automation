from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database.models import AlertRule, SysUser
from database.session import get_db
from dependencies import get_current_user, require_write
from schemas.all import AlertRuleCreate, AlertRuleOut

router = APIRouter()


@router.get('/rules', response_model=list[AlertRuleOut])
def list_rules(user: SysUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(AlertRule).order_by(AlertRule.id.desc()).all()


@router.post('/rules', response_model=AlertRuleOut)
def create_rule(payload: AlertRuleCreate, user: SysUser = Depends(require_write), db: Session = Depends(get_db)):
    item = AlertRule(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item