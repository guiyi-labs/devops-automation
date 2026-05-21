from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database.session import get_db
from database.models import ServerAsset
from schemas.all import AssetCreate, AssetUpdate, AssetOut
router = APIRouter()
@router.get('/', response_model=list[AssetOut])
def list_assets(db: Session = Depends(get_db)): return db.query(ServerAsset).order_by(ServerAsset.id.desc()).all()
@router.post('/', response_model=AssetOut)
def create_asset(payload: AssetCreate, db: Session = Depends(get_db)):
    item = ServerAsset(**payload.model_dump()); db.add(item); db.commit(); db.refresh(item); return item
@router.put('/{asset_id}', response_model=AssetOut)
def update_asset(asset_id: int, payload: AssetUpdate, db: Session = Depends(get_db)):
    item = db.get(ServerAsset, asset_id)
    if not item: raise HTTPException(status_code=404, detail='资产不存在')
    for k,v in payload.model_dump().items(): setattr(item,k,v)
    db.commit(); db.refresh(item); return item
@router.delete('/{asset_id}')
def delete_asset(asset_id: int, db: Session = Depends(get_db)):
    item = db.get(ServerAsset, asset_id)
    if not item: raise HTTPException(status_code=404, detail='资产不存在')
    db.delete(item); db.commit(); return {'ok': True}
