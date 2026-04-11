import json
import os
import ssl
import paho.mqtt.client as mqtt
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv


# Carga variables desde backend/.env si existe
load_dotenv(override=False)


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in ("1", "true", "yes", "on")


def _connect_client() -> mqtt.Client:
    broker = os.getenv("MQTT_BROKER", "broker.hivemq.com")
    port = int(os.getenv("MQTT_PORT", "1883"))
    use_tls = _env_bool("MQTT_TLS")
    username = os.getenv("MQTT_USERNAME")
    password = os.getenv("MQTT_PASSWORD")

    client = mqtt.Client()
    if username:
        client.username_pw_set(username, password or "")
    if use_tls:
        tls_context = ssl.create_default_context()
        client.tls_set_context(tls_context)
    client.connect(broker, port, 60)
    return client

topic = os.getenv("MQTT_TOPIC", "ecosort/eventos")

client = _connect_client()


def _iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


# Generamos datos para los últimos 3 días, con separación >= 30 minutos.
now_utc = datetime.now(timezone.utc)
start_utc = now_utc - timedelta(days=3)

# Redondea hacia abajo a la hora para que los buckets se vean “limpios”
start_utc = start_utc.replace(minute=0, second=0, microsecond=0)
now_utc = now_utc.replace(minute=0, second=0, microsecond=0)

# Usaremos 1 hora de separación (cumple >= 30 min)
step = timedelta(hours=1)
timeline: list[datetime] = []
cursor = start_utc
while cursor <= now_utc:
    timeline.append(cursor)
    cursor += step

materials = ["plastic", "glass", "metal"]
lines = ["1", "2", "3"]


def _state_for(ts: datetime, idx: int) -> dict:
    total_parking = 10
    occupied = (idx % (total_parking + 1))

    # De vez en cuando marcamos “bodega llena” para provocar alerts warehouse_full (vía script/telemetría)
    vidrio_llena = (idx % 17) == 0
    metal_llena = (idx % 19) == 0
    plastico_llena = (idx % 23) == 0

    # Humo cada ~12 horas
    humo = (idx % 12) == 0

    return {
        "kind": "state",
        "puertaAbierta": (idx % 8) < 4,
        "talanqueraAbierta": (idx % 6) < 3,
        "luz": "auto" if (idx % 3) == 0 else ("on" if (idx % 3) == 1 else "off"),
        "bandaPrincipal": True,
        "bandaVidrio": (idx % 10) != 0,
        "bandaMetal": (idx % 9) != 0,
        "bandaPlastico": (idx % 7) != 0,
        "bodegaVidrioLlena": vidrio_llena,
        "bodegaMetalLlena": metal_llena,
        "bodegaPlasticoLlena": plastico_llena,
        "parqueosOcupados": occupied,
        "totalParqueos": total_parking,
        "alarmaHumoActiva": humo,
        # compat
        "alarmaActiva": humo,
        "timestamp": _iso_utc(ts),
    }


def _alert_for(ts: datetime, idx: int) -> dict | None:
    # Una alerta cada 6 horas aprox.
    if idx % 6 != 0:
        return None

    # Alterna tipos para que Grafana pueda agrupar
    alert_type = "smoke" if (idx % 12) == 0 else "warehouse_full"
    description = "smoke detected (test)" if alert_type == "smoke" else "warehouse full (test)"

    return {
        "kind": "alert",
        "type": alert_type,
        "description": description,
        "timestamp": _iso_utc(ts + timedelta(minutes=1)),
    }


def _events_for(ts: datetime, idx: int) -> list[dict]:
    # 2 eventos por punto: uno accepted (para materials_by_line) y uno rejected (para rejects_by_line/throughput)
    mat = materials[idx % len(materials)]
    line = lines[idx % len(lines)]

    accepted = {
        "kind": "event",
        "type": "classification",
        "material": mat,
        "result": "accepted",
        "line": line,
        "timestamp": _iso_utc(ts + timedelta(minutes=2)),
    }

    rejected = {
        "kind": "event",
        "type": "classification",
        "material": mat,
        "result": "rejected",
        "line": line,
        "timestamp": _iso_utc(ts + timedelta(minutes=3)),
    }

    return [accepted, rejected]

for idx, ts in enumerate(timeline):
    state_msg = _state_for(ts, idx)
    client.publish(topic, json.dumps(state_msg), qos=0).wait_for_publish(timeout=2)
    client.loop(timeout=2)

    alert_msg = _alert_for(ts, idx)
    if alert_msg:
        client.publish(topic, json.dumps(alert_msg), qos=0).wait_for_publish(timeout=2)
        client.loop(timeout=2)

    for event_msg in _events_for(ts, idx):
        client.publish(topic, json.dumps(event_msg), qos=0).wait_for_publish(timeout=2)
        client.loop(timeout=2)
client.disconnect()

print(
    "Mensajes MQTT de prueba enviados a",
    topic,
    f"(desde {start_utc.isoformat()} hasta {now_utc.isoformat()}, paso={step})",
)