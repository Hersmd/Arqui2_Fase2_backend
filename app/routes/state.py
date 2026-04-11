from fastapi import APIRouter
from app.config.database import db
from datetime import datetime

router = APIRouter()

@router.get("/state/latest")
def get_latest_state():
    state = db.state.find_one(sort=[("timestamp", -1)])
    
    if state:
        state.pop("_id", None)
    
    return state or {}

@router.get("/state/history")
def get_state_history(limit: int = 50):
    states = list(
        db.state.find({}, {"_id": 0})
        .sort("timestamp", -1)
        .limit(limit)
    )
    return states

@router.get("/state/parking")
def get_parking_history(start: str, end: str):
    states = list(db.state.find({
        "timestamp": {
            "$gte": datetime.fromisoformat(start),
            "$lte": datetime.fromisoformat(end)
        }
    }))

    resultado = []

    for s in states:
        parking = s.get("parking", [])

        ocupados = sum(1 for p in parking if p is True)

        hora = s["timestamp"].strftime("%H:%M")

        resultado.append({
            "hora": hora,
            "ocupacion": ocupados
        })

    return resultado