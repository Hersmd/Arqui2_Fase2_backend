from fastapi import APIRouter, HTTPException
from app.config.database import db
from datetime import datetime
from pymongo.errors import PyMongoError

router = APIRouter()

@router.get("/state/latest")
def get_latest_state():
    try:
        state = db.state.find_one(sort=[("timestamp", -1)])
    except PyMongoError as exc:
        print(f"[mongo] /state/latest error: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=503,
            detail="MongoDB no disponible (revisar MONGO_URI/DB_NAME en el backend)",
        ) from exc
    
    if state:
        state.pop("_id", None)

        # Compatibilidad: documentos viejos pueden no tener todos los campos.
        # Devolvemos siempre las llaves esperadas por el frontend.
        state.setdefault("parking", [])
        state.setdefault("door", "unknown")
        state.setdefault("barrier", "unknown")
        state.setdefault("conveyor", "unknown")
        state.setdefault("lighting", "unknown")
        state.setdefault("timestamp", datetime.utcnow())
    
    return state or {}

@router.get("/state/history")
def get_state_history(limit: int = 50):
    try:
        states = list(
            db.state.find({}, {"_id": 0})
            .sort("timestamp", -1)
            .limit(limit)
        )
        return states
    except PyMongoError as exc:
        print(f"[mongo] /state/history error: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=503,
            detail="MongoDB no disponible (revisar MONGO_URI/DB_NAME en el backend)",
        ) from exc

@router.get("/state/parking")
def get_parking_history(start: str, end: str):
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido (use ISO 8601)") from exc

    try:
        states = list(
            db.state.find(
                {
                    "timestamp": {
                        "$gte": start_dt,
                        "$lte": end_dt,
                    }
                }
            )
        )
    except PyMongoError as exc:
        print(f"[mongo] /state/parking error: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=503,
            detail="MongoDB no disponible (revisar MONGO_URI/DB_NAME en el backend)",
        ) from exc

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