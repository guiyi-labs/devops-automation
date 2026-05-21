from sqlalchemy.orm import Session
from database.models import ServerAsset
from schemas.all import AssetCreate

def create_asset(db: Session, payload: AssetCreate) -> ServerAsset:
    item = ServerAsset(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item
