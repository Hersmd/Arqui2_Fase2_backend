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

    def _bool(value) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "t", "yes", "y", "on", "open", "up"}
        return bool(value)

    def _get(obj: dict, path: str):
        cur = obj
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return cur

    def _first(obj: dict, paths: list[str]):
        for p in paths:
            v = _get(obj, p)
            if v is not None:
                return v
        return None

    def _to_mode(value) -> str:
        if value is None:
            return "unknown"
        if isinstance(value, str):
            v = value.strip().lower()
            if v in {"on", "encendido", "encendida"}:
                return "on"
            if v in {"off", "apagado", "apagada"}:
                return "off"
            if v in {"auto", "automatico", "automático"}:
                return "auto"
            if v in {"unknown", "desconocido", "desconocida"}:
                return "unknown"
        return str(value)

    def _to_motion(value, mapping: dict[str, str], default: str = "unknown") -> str:
        if value is None:
            return default
        if isinstance(value, str):
            v = value.strip().lower()
            return mapping.get(v, default)
        if isinstance(value, bool):
            return mapping.get("true" if value else "false", default)
        return default

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

        door = "open" if _bool(data.get("puertaAbierta")) else "closed"

        barrier_bool = _first(
            data,
            [
                "talanqueraAbierta",
                "barreraArriba",
                "barrierUp",
            ],
        )
        barrier = "up" if _bool(barrier_bool) else "down" if barrier_bool is not None else "unknown"

        conveyor_principal = "running" if _bool(_first(data, ["bandaPrincipal", "banda_principal"])) else "stopped"
        conveyor_plastico = "running" if _bool(_first(data, ["bandaPlastico", "banda_plastico"])) else "stopped"
        conveyor_vidrio = "running" if _bool(_first(data, ["bandaVidrio", "banda_vidrio"])) else "stopped"
        conveyor_metal = "running" if _bool(_first(data, ["bandaMetal", "banda_metal"])) else "stopped"

        lighting = _to_mode(
            _first(
                data,
                [
                    "luz",
                    "iluminacion",
                    "modoIluminacion",
                    "lighting",
                ],
            )
        )

        return {
            "parking": parking,
            "door": door,
            "barrier": barrier,
            "conveyor": conveyor_principal,
            "lighting": lighting,
            "conveyor_principal": conveyor_principal,
            "conveyor_plastico": conveyor_plastico,
            "conveyor_vidrio": conveyor_vidrio,
            "conveyor_metal": conveyor_metal,
            "bin_plastico_full": _first(data, ["bodegaPlasticoLlena", "bodega_plastico_llena", "bin_plastic_full"]),
            "bin_vidrio_full": _first(data, ["bodegaVidrioLlena", "bodega_vidrio_llena", "bin_glass_full"]),
            "bin_metal_full": _first(data, ["bodegaMetalLlena", "bodega_metal_llena", "bin_metal_full"]),
            "smoke_alarm": _first(data, ["humo", "alarmaHumo", "alarmaActiva", "smoke_alarm"]),
            "emergency": _first(data, ["emergencia", "emergency"]),
            "timestamp": _ensure_datetime(data.get("timestamp")),
        }

    # Formato Arduino (JSON crudo) - intenta mapear si viene con secciones típicas
    if isinstance(data.get("access_control"), dict) or isinstance(data.get("system_global"), dict) or isinstance(data.get("sorting_plant"), dict):
        access = data.get("access_control") if isinstance(data.get("access_control"), dict) else {}
        global_ = data.get("system_global") if isinstance(data.get("system_global"), dict) else {}
        plant = data.get("sorting_plant") if isinstance(data.get("sorting_plant"), dict) else {}

        door_bool = _first(access, ["door_open", "doorOpen", "puerta_abierta", "puertaAbierta"])
        barrier_bool = _first(access, ["barrier_up", "barrierUp", "talanquera_abierta", "talanqueraAbierta"])
        lighting_mode = _first(global_, ["lighting", "lighting_mode", "light", "luz", "modoIluminacion"])
        smoke = _first(global_, ["smoke", "smoke_alarm", "alarmaHumo", "humo"])
        emergency = _first(global_, ["emergency", "emergencia"])

        # Líneas / bandas
        principal = _first(plant, ["main_conveyor", "banda_principal", "bandaPrincipal", "conveyor"])
        plastico = _first(plant, ["plastic_conveyor", "banda_plastico", "bandaPlastico"])
        vidrio = _first(plant, ["glass_conveyor", "banda_vidrio", "bandaVidrio"])
        metal = _first(plant, ["metal_conveyor", "banda_metal", "bandaMetal"])

        conveyor_principal = _to_motion(principal, {"running": "running", "on": "running", "true": "running", "stopped": "stopped", "off": "stopped", "false": "stopped"})
        conveyor_plastico = _to_motion(plastico, {"running": "running", "on": "running", "true": "running", "stopped": "stopped", "off": "stopped", "false": "stopped"}, default="unknown")
        conveyor_vidrio = _to_motion(vidrio, {"running": "running", "on": "running", "true": "running", "stopped": "stopped", "off": "stopped", "false": "stopped"}, default="unknown")
        conveyor_metal = _to_motion(metal, {"running": "running", "on": "running", "true": "running", "stopped": "stopped", "off": "stopped", "false": "stopped"}, default="unknown")

        # Parking puede venir como lista o como (ocupados,total)
        parking_list = data.get("parking") if isinstance(data.get("parking"), list) else None
        if parking_list is None:
            total = _first(data, ["totalParqueos", "total_parqueos", "parking_total"]) or 0
            occupied = _first(data, ["parqueosOcupados", "parqueos_ocupados", "parking_occupied"]) or 0
            try:
                total_i = int(total)
                occupied_i = int(occupied)
            except Exception:
                total_i = 0
                occupied_i = 0
            parking_list = ([True] * max(0, min(occupied_i, total_i))) + ([False] * max(0, total_i - occupied_i))

        return {
            "parking": parking_list,
            "door": "open" if _bool(door_bool) else "closed" if door_bool is not None else "unknown",
            "barrier": "up" if _bool(barrier_bool) else "down" if barrier_bool is not None else "unknown",
            "conveyor": conveyor_principal,
            "lighting": _to_mode(lighting_mode),
            "conveyor_principal": conveyor_principal,
            "conveyor_plastico": conveyor_plastico,
            "conveyor_vidrio": conveyor_vidrio,
            "conveyor_metal": conveyor_metal,
            "smoke_alarm": smoke,
            "emergency": emergency,
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