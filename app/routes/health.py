from fastapi import APIRouter
from pymongo.errors import PyMongoError

from app.config.database import client
from app.config.settings import settings

router = APIRouter()


@router.get("/health")
def health():
    mongo_uri_state = (
        "default_local"
        if settings.MONGO_URI == "mongodb://localhost:27017"
        else "placeholder"
        if "USUARIO:CONTRASENA" in settings.MONGO_URI
        else "configured"
    )

    mongo_ok = False
    mongo_error = None

    try:
        client.admin.command("ping")
        mongo_ok = True
    except PyMongoError as exc:
        mongo_error = f"{type(exc).__name__}: {exc}"

    return {
        "ok": True,
        "mongo": {
            "ok": mongo_ok,
            "uri_state": mongo_uri_state,
            "db_name": settings.DB_NAME,
            "error": mongo_error,
        },
        "mqtt": {
            "enabled": settings.ENABLE_MQTT,
            "subscribe_topics": settings.MQTT_SUBSCRIBE_TOPICS,
        },
    }
