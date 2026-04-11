import json
import ssl
import paho.mqtt.client as mqtt
from app.config.database import db
from app.services.kpi_service import process_kpi
from app.schemas.event_schema import Event
from app.schemas.state_schema import State
from datetime import datetime
from app.schemas.alert_schema import Alert
from app.config.settings import settings
from typing import Any


def _ensure_datetime(value):
    if isinstance(value, datetime):
        return value
    if value is None:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return datetime.utcnow()


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    # pymongo/bson ObjectId u otros objetos
    try:
        from bson import ObjectId  # type: ignore

        if isinstance(value, ObjectId):
            return str(value)
    except Exception:
        pass
    return value


def _log_mongo_insert(collection: str, inserted_id: Any, document: dict) -> None:
    if not getattr(settings, "LOG_MONGO_INSERTS", True):
        return

    payload = {
        "collection": collection,
        "inserted_id": str(inserted_id),
        "document": document,
    }

    try:
        serialized = json.dumps(_jsonable(payload), ensure_ascii=False)
    except Exception as exc:
        print(f"[MONGO][INSERT] {collection} id={inserted_id} (error serializando: {exc})")
        return

    max_chars = int(getattr(settings, "LOG_MONGO_INSERTS_MAX_CHARS", 2000) or 2000)
    if max_chars > 0 and len(serialized) > max_chars:
        serialized = serialized[:max_chars] + "... (truncado)"

    print(f"[MONGO][INSERT] {serialized}")


def _normalize_state_payload(data: dict) -> dict:
    """Normaliza distintos formatos de 'state' a lo esperado por `State`.

    - Formato backend: {parking: [...], door: str, barrier: str, conveyor: str, lighting: str, timestamp: ISO/datetime}
    - Formato script Raspberry: {puertaAbierta: bool, bandaPrincipal: bool, parqueosOcupados: int, totalParqueos: int, ...}
    """
    if not isinstance(data, dict):
        raise ValueError("state payload no es dict")

    # Formato del script de Raspberry
    if "puertaAbierta" in data and "parqueosOcupados" in data:
        total = int(data.get("totalParqueos") or 0)
        occupied = int(data.get("parqueosOcupados") or 0)
        if total < 0:
            total = 0
        if occupied < 0:
            occupied = 0
        if occupied > total:
            occupied = total

        parking = ([True] * occupied) + ([False] * (total - occupied))
        door = "open" if bool(data.get("puertaAbierta")) else "closed"
        conveyor = "on" if bool(data.get("bandaPrincipal")) else "off"

        return {
            "parking": parking,
            "door": door,
            "barrier": "unknown",
            "conveyor": conveyor,
            "lighting": "unknown",
            "timestamp": _ensure_datetime(data.get("timestamp")),
        }

    # Formato ya compatible
    normalized = dict(data)
    normalized["timestamp"] = _ensure_datetime(normalized.get("timestamp"))
    return normalized

def on_connect(client, userdata, flags, rc, properties=None):
    print("MQTT conectado")

    default_topics = [
        settings.MQTT_TOPIC_EVENTS,
        settings.MQTT_TOPIC_STATE,
        settings.MQTT_TOPIC_ALERTS,
        settings.MQTT_TOPIC_EVENTOS,
        settings.MQTT_TOPIC_COMANDOS,
    ]

    topics_raw = (settings.MQTT_SUBSCRIBE_TOPICS or "").strip()
    topics = (
        [t.strip() for t in topics_raw.split(",") if t.strip()]
        if topics_raw
        else default_topics
    )

    for topic in topics:
        client.subscribe(topic)

def on_message(client, userdata, msg):
    try:
        topic = msg.topic
        data = json.loads(msg.payload.decode())
        kind = data.get("kind") if isinstance(data, dict) else None

        # Topics canónicos
        if topic == settings.MQTT_TOPIC_EVENTS:
            if isinstance(data, dict):
                data["timestamp"] = _ensure_datetime(data.get("timestamp"))
            event = Event(**data)
            doc = event.model_dump()
            res = db.events.insert_one(doc)
            _log_mongo_insert("events", res.inserted_id, doc)
            process_kpi(doc)
            return

        if topic == settings.MQTT_TOPIC_STATE:
            normalized = _normalize_state_payload(data)
            state = State(**normalized)
            doc = state.model_dump()
            res = db.state.insert_one(doc)
            _log_mongo_insert("state", res.inserted_id, doc)
            return

        if topic == settings.MQTT_TOPIC_ALERTS:
            if isinstance(data, dict):
                data["timestamp"] = _ensure_datetime(data.get("timestamp"))
            alert = Alert(**data)
            doc = alert.model_dump()
            res = db.alerts.insert_one(doc)
            _log_mongo_insert("alerts", res.inserted_id, doc)
            return

        # Topic único (script Raspberry): enruta por `kind`
        if topic == settings.MQTT_TOPIC_EVENTOS:
            if kind == "alert":
                if not isinstance(data, dict):
                    raise ValueError("alert payload no es dict")
                data["timestamp"] = _ensure_datetime(data.get("timestamp"))
                alert = Alert(**data)
                doc = alert.model_dump()
                res = db.alerts.insert_one(doc)
                _log_mongo_insert("alerts", res.inserted_id, doc)
                return

            if kind == "event":
                if not isinstance(data, dict):
                    raise ValueError("event payload no es dict")
                data["timestamp"] = _ensure_datetime(data.get("timestamp"))
                event = Event(**data)
                doc = event.model_dump()
                res = db.events.insert_one(doc)
                _log_mongo_insert("events", res.inserted_id, doc)
                process_kpi(doc)
                return

            # default: state
            normalized = _normalize_state_payload(data)
            state = State(**normalized)
            doc = state.model_dump()
            res = db.state.insert_one(doc)
            _log_mongo_insert("state", res.inserted_id, doc)
            return

    except Exception as e:
        print("Error procesando MQTT:", e)


client = mqtt.Client()

if settings.MQTT_USERNAME:
    client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD or "")

if settings.MQTT_TLS:
    tls_context = ssl.create_default_context()
    client.tls_set_context(tls_context)

client.on_connect = on_connect
client.on_message = on_message

def start_mqtt():
    try:
        client.connect(settings.MQTT_BROKER, settings.MQTT_PORT, 60)
        client.loop_start()
    except Exception as exc:
        print(f"Error iniciando MQTT: {exc}")