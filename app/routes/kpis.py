from fastapi import APIRouter
from app.config.database import db

router = APIRouter()

@router.get("/kpis")
def get_kpis():
    return list(db.kpis.find({}, {"_id": 0}))