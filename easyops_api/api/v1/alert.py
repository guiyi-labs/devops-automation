from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database.session import get_db
from database.models import AlertRule
from schemas.all import AlertRuleCreate, AlertRuleOut
router = APIRouter()
@router.get('/rules', response_model=list[AlertRuleOut])
def list_rules(db: Session = Depends(get_db)): return db.query(AlertRule).order_by(AlertRule.id.desc()).all()
@router.post('/rules', response_model=AlertRuleOut)
def create_rule(payload: AlertRuleCreate, db: Session = Depends(get_db)):
    item = AlertRule(**payload.model_dump()); db.add(item); db.commit(); db.refresh(item); return item
