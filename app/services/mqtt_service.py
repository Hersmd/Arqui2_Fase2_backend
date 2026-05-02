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
from typing import Any, List


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

    def _first(obj: dict, paths: List[str]):
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

    def _status_to_motion(value) -> str:
        if value is None:
            return "unknown"
        if isinstance(value, str):
            v = value.strip().lower()
            if any(token in v for token in ["avanz", "clasific", "horne", "compact", "prensa", "running", "on"]):
                return "running"
            if any(token in v for token in ["deten", "paro", "stop", "stopped", "off"]):
                return "stopped"
        return "unknown"

    def _status_to_door(value) -> str:
        if value is None:
            return "unknown"
        if isinstance(value, str):
            v = value.strip().lower()
            if "abiert" in v or "open" in v:
                return "open"
            if "cerrad" in v or "close" in v:
                return "closed"
        if isinstance(value, bool):
            return "open" if value else "closed"
        return "unknown"

    def _parking_from_capacity(occupied_value, total_value):
        try:
            total_i = int(total_value or 0)
            occupied_i = int(occupied_value or 0)
        except Exception:
            total_i = 0
            occupied_i = 0

        if total_i < 0:
            total_i = 0
        if occupied_i < 0:
            occupied_i = 0
        if occupied_i > total_i:
            occupied_i = total_i

        return ([True] * occupied_i) + ([False] * (total_i - occupied_i))

    def _parking_from_map(raw_map: str):
        if not isinstance(raw_map, str):
            return None
        tokens = [t.strip() for t in raw_map.replace("|", " ").split() if t.strip()]
        if not tokens:
            return None
        parking = []
        for tok in tokens:
            if "x" in tok.lower():
                parking.append(True)
            elif "[" in tok or "]" in tok:
                parking.append(False)
        return parking or None

    def _timestamp_from_ms(value):
        if value is None:
            return None
        try:
            ms = int(value)
        except Exception:
            return None
        # If looks like epoch milliseconds, convert. Otherwise fallback to now.
        if ms >= 10**12:
            return datetime.utcfromtimestamp(ms / 1000.0)
        return datetime.utcnow()

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
            "smoke_alarm": _first(data, ["alarmaHumoActiva", "alarmaHumo", "humo", "smoke_alarm", "alarmaActiva"]),
            "emergency": _first(data, ["emergencia", "emergency"]),
            "timestamp": _ensure_datetime(data.get("timestamp")),
        }

    # Formato Arduino (JSON crudo) - intenta mapear si viene con secciones tipicas
    if isinstance(data.get("access_control"), dict) or isinstance(data.get("system_global"), dict) or isinstance(data.get("sorting_plant"), dict):
        access = data.get("access_control") if isinstance(data.get("access_control"), dict) else {}
        global_ = data.get("system_global") if isinstance(data.get("system_global"), dict) else {}
        plant = data.get("sorting_plant") if isinstance(data.get("sorting_plant"), dict) else {}

        door_bool = _first(access, ["door_open", "doorOpen", "puerta_abierta", "puertaAbierta"])
        door_status = _first(access, ["door_status", "doorStatus", "estado_puerta", "estadoPuerta"])
        barrier_bool = _first(access, ["barrier_up", "barrierUp", "talanquera_abierta", "talanqueraAbierta"])
        barrier_open = _first(access, ["parking_barrier_open", "barrier_open", "barrierOpen"])
        lighting_mode = _first(global_, ["lighting", "lighting_mode", "light", "luz", "modoIluminacion"])
        smoke = _first(global_, ["smoke", "smoke_alarm", "alarmaHumo", "humo"])
        emergency = _first(global_, ["emergency", "emergencia", "emergency_active"])
        smoke_raw = _first(global_, ["smoke_raw_value", "smokeRawValue", "humo_raw", "humoRaw"])

        # Líneas / bandas
        principal = _first(plant, ["main_conveyor", "banda_principal", "bandaPrincipal", "conveyor", "main_belt_status"])
        plastico = _first(plant, ["plastic_conveyor", "banda_plastico", "bandaPlastico", "plastic_belt.status"])
        vidrio = _first(plant, ["glass_conveyor", "banda_vidrio", "bandaVidrio", "glass_belt.status"])
        metal = _first(plant, ["metal_conveyor", "banda_metal", "bandaMetal", "metal_belt.status"])

        glass_belt = plant.get("glass_belt") if isinstance(plant.get("glass_belt"), dict) else {}
        metal_belt = plant.get("metal_belt") if isinstance(plant.get("metal_belt"), dict) else {}
        plastic_belt = plant.get("plastic_belt") if isinstance(plant.get("plastic_belt"), dict) else {}

        conveyor_principal = _to_motion(principal, {"running": "running", "on": "running", "true": "running", "stopped": "stopped", "off": "stopped", "false": "stopped"})
        if conveyor_principal == "unknown":
            conveyor_principal = _status_to_motion(principal)

        conveyor_plastico = _to_motion(plastico, {"running": "running", "on": "running", "true": "running", "stopped": "stopped", "off": "stopped", "false": "stopped"}, default="unknown")
        if conveyor_plastico == "unknown":
            conveyor_plastico = _status_to_motion(plastico)

        conveyor_vidrio = _to_motion(vidrio, {"running": "running", "on": "running", "true": "running", "stopped": "stopped", "off": "stopped", "false": "stopped"}, default="unknown")
        if conveyor_vidrio == "unknown":
            conveyor_vidrio = _status_to_motion(vidrio)

        conveyor_metal = _to_motion(metal, {"running": "running", "on": "running", "true": "running", "stopped": "stopped", "off": "stopped", "false": "stopped"}, default="unknown")
        if conveyor_metal == "unknown":
            conveyor_metal = _status_to_motion(metal)

        # Parking puede venir como lista o como (ocupados,total)
        parking_list = data.get("parking") if isinstance(data.get("parking"), list) else None
        if parking_list is None:
            total = _first(data, ["totalParqueos", "total_parqueos", "parking_total"]) or _first(access, ["parking_capacity", "parkingCapacity"]) or 0
            occupied = _first(data, ["parqueosOcupados", "parqueos_ocupados", "parking_occupied"]) or _first(access, ["parking_occupied", "parkingOccupied"]) or 0
            parking_list = _parking_from_capacity(occupied, total)

        if parking_list is None:
            parking_list = _parking_from_map(_first(access, ["parking_map", "parkingMap"]) or "")

        if parking_list is None:
            parking_list = []

        timestamp = _ensure_datetime(data.get("timestamp"))
        if data.get("timestamp") is None:
            ts_ms = data.get("timestamp_ms") or _first(global_, ["timestamp_ms", "timestampMs"])
            ts_from_ms = _timestamp_from_ms(ts_ms)
            if ts_from_ms is not None:
                timestamp = ts_from_ms

        return {
            "parking": parking_list,
            "door": _status_to_door(door_status) if door_status is not None else ("open" if _bool(door_bool) else "closed" if door_bool is not None else "unknown"),
            "barrier": "up" if _bool(barrier_open if barrier_open is not None else barrier_bool) else "down" if (barrier_open is not None or barrier_bool is not None) else "unknown",
            "conveyor": conveyor_principal,
            "lighting": _to_mode(lighting_mode),
            "conveyor_principal": conveyor_principal,
            "conveyor_plastico": conveyor_plastico,
            "conveyor_vidrio": conveyor_vidrio,
            "conveyor_metal": conveyor_metal,
            "bin_plastico_full": _first(data, ["bodegaPlasticoLlena", "bodega_plastico_llena", "bin_plastic_full"]) if _first(data, ["bodegaPlasticoLlena", "bodega_plastico_llena", "bin_plastic_full"]) is not None else plastic_belt.get("bin_full"),
            "bin_vidrio_full": _first(data, ["bodegaVidrioLlena", "bodega_vidrio_llena", "bin_glass_full"]) if _first(data, ["bodegaVidrioLlena", "bodega_vidrio_llena", "bin_glass_full"]) is not None else glass_belt.get("bin_full"),
            "bin_metal_full": _first(data, ["bodegaMetalLlena", "bodega_metal_llena", "bin_metal_full"]) if _first(data, ["bodegaMetalLlena", "bodega_metal_llena", "bin_metal_full"]) is not None else metal_belt.get("bin_full"),
            "smoke_alarm": smoke if smoke is not None else (bool(smoke_raw) if smoke_raw is not None else None),
            "emergency": emergency,
            "timestamp": timestamp,
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

        # ====== LOGGING DE DEBUG ======
        print("\n[MQTT-RX] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"[MQTT-RX] Topic: {topic}")
        print(f"[MQTT-RX] Kind: {kind}")
        payload_raw = msg.payload.decode()
        print(f"[MQTT-RX] Payload size: {len(payload_raw)} bytes")
        print(f"[MQTT-RX] Has access_control: {isinstance(data.get('access_control'), dict)}")
        print(f"[MQTT-RX] Has system_global: {isinstance(data.get('system_global'), dict)}")
        print(f"[MQTT-RX] Has sorting_plant: {isinstance(data.get('sorting_plant'), dict)}")
        print("[MQTT-RX] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
        # ====================================

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
                        print(f"[MQTT-PRC] ► Procesando ecosort/eventos con kind='{kind}'")
            
            if kind == "alert":
                if not isinstance(data, dict):
                    raise ValueError("alert payload no es dict")
                                print(f"[MQTT-OK] ✅ Alert guardada en alerts")
                data["timestamp"] = _ensure_datetime(data.get("timestamp"))
                alert = Alert(**data)
                doc = alert.model_dump()
                res = db.alerts.insert_one(doc)
                _log_mongo_insert("alerts", res.inserted_id, doc)
                return

            if kind == "event":
                if not isinstance(data, dict):
                    raise ValueError("event payload no es dict")
                                print(f"[MQTT-OK] ✅ Event guardada en events")
                data["timestamp"] = _ensure_datetime(data.get("timestamp"))
                event = Event(**data)
                doc = event.model_dump()
                res = db.events.insert_one(doc)
                _log_mongo_insert("events", res.inserted_id, doc)
                process_kpi(doc)
                return

            # default: state
                        print(f"[MQTT-PRC] ► Default to state (no era alert/event)")
                        print(f"[MQTT-DBG] Antes normalize: parking? {isinstance(data.get('access_control'), dict)}")
                        print(f"[MQTT-DBG] Después normalize: parking={len(normalized.get('parking', []))} elementos, door='{normalized.get('door')}'")
                        print(f"[MQTT-OK] ✅ State guardada en state (parking={len(doc.get('parking', []))})")
            normalized = _normalize_state_payload(data)
            state = State(**normalized)
            doc = state.model_dump()
            res = db.state.insert_one(doc)
            _log_mongo_insert("state", res.inserted_id, doc)
            return

    except Exception as e:
        print(f"[MQTT-ERR] ❌ {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


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