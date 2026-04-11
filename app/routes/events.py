from fastapi import APIRouter
from app.config.database import db
from collections import defaultdict
from datetime import datetime

router = APIRouter()


def _parse_iso_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.fromisoformat(normalized)

@router.get("/events")
def get_events():
    return list(db.events.find({}, {"_id": 0}))

@router.get("/events/range")
def get_events_range(start: str, end: str):
    start_dt = _parse_iso_datetime(start)
    end_dt = _parse_iso_datetime(end)
    return list(db.events.find({
        "timestamp": {"$gte": start_dt, "$lte": end_dt}
    }, {"_id": 0}))

@router.get("/events/filter")
def filter_events(material: str = None, type: str = None):
    query = {}

    if material:
        query["material"] = material
    if type:
        query["type"] = type

    return list(db.events.find(query, {"_id": 0}))

@router.get("/events/history")
def get_history(start: str, end: str):
    events = list(db.events.find({
        "timestamp": {"$gte": start, "$lte": end}
    }, {"_id": 0}))

    return events

@router.get("/events/summary")
def get_summary(start: str, end: str):
    events = list(db.events.find({
        "timestamp": {"$gte": datetime.fromisoformat(start), "$lte": datetime.fromisoformat(end)}
    }))

    resumen = defaultdict(lambda: {"plastico": 0, "vidrio": 0, "metal": 0})

    for e in events:
        if e.get("type") == "classification":
            fecha = e["timestamp"].strftime("%Y-%m-%d")
            material = e.get("material")

            if material == "plastic":
                resumen[fecha]["plastico"] += 1
            elif material == "glass":
                resumen[fecha]["vidrio"] += 1
            elif material == "metal":
                resumen[fecha]["metal"] += 1

    # Convertir a lista para el frontend
    resultado = []
    for fecha, valores in resumen.items():
        resultado.append({
            "dia": fecha,
            **valores
        })

    return resultado