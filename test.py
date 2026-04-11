import json
import os
import ssl
import paho.mqtt.client as mqtt
from datetime import datetime


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

state_msg = {
    "kind": "state",
    "puertaAbierta": True,
    "bandaPrincipal": True,
    "bandaVidrio": True,
    "bandaMetal": True,
    "bandaPlastico": True,
    "bodegaVidrioLlena": False,
    "bodegaMetalLlena": False,
    "bodegaPlasticoLlena": False,
    "parqueosOcupados": 2,
    "totalParqueos": 10,
    "alarmaActiva": False,
    "timestamp": datetime.now().isoformat(),
}

alert_msg = {
    "kind": "alert",
    "type": "smoke",
    "description": "smoke detected (test)",
    "timestamp": datetime.now().isoformat(),
}

event_msg = {
    "kind": "event",
    "type": "classification",
    "material": "metal",
    "result": "accepted",
    "line": "3",
    "timestamp": datetime.now().isoformat(),
}

client.publish(topic, json.dumps(state_msg), qos=0).wait_for_publish(timeout=2)
client.loop(timeout=2)
client.publish(topic, json.dumps(alert_msg), qos=0).wait_for_publish(timeout=2)
client.loop(timeout=2)
client.publish(topic, json.dumps(event_msg), qos=0).wait_for_publish(timeout=2)
client.loop(timeout=2)
client.disconnect()

print("Mensajes MQTT de prueba enviados a", topic)