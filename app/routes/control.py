from fastapi import APIRouter
import json
import ssl
import paho.mqtt.client as mqtt

from app.config.settings import settings

router = APIRouter()


_FRONTEND_ALIASES = {
    "abrir_puerta": {"comando": "ABRIR_PUERTA"},
    "cerrar_puerta": {"comando": "CERRAR_PUERTA"},
    "abrir_talanquera": {"comando": "ABRIR_TALANQUERA"},
    "cerrar_talanquera": {"comando": "CERRAR_TALANQUERA"},
    "luz_on": {"comando": "CAMBIAR_ILUMINACION", "param": "ENCENDIDO"},
    "luz_off": {"comando": "CAMBIAR_ILUMINACION", "param": "APAGADO"},
    "luz_auto": {"comando": "CAMBIAR_ILUMINACION", "param": "AUTOMATICO"},
    "pausar_principal": {"comando": "PAUSAR_LINEA", "param": "principal"},
    "reanudar_principal": {"comando": "REANUDAR_LINEA", "param": "principal"},
    "pausar_vidrio": {"comando": "PAUSAR_LINEA", "param": "vidrio"},
    "reanudar_vidrio": {"comando": "REANUDAR_LINEA", "param": "vidrio"},
    "pausar_metal": {"comando": "PAUSAR_LINEA", "param": "metal"},
    "reanudar_metal": {"comando": "REANUDAR_LINEA", "param": "metal"},
    "pausar_plastico": {"comando": "PAUSAR_LINEA", "param": "plastico"},
    "reanudar_plastico": {"comando": "REANUDAR_LINEA", "param": "plastico"},
    "emergencia": {"comando": "ACTIVAR_EMERGENCIA"},
}


def _normalize_command_payload(cmd: dict) -> dict:
    """Normaliza el comando entrante al contrato MQTT estándar:
    {"comando": "...", "param": "..."}

    - Si llega un alias del frontend (pausar_principal, luz_on, etc.), lo convierte.
    - Si ya viene en formato estándar, lo respeta.
    - Si viene con clave 'command', lo convierte a 'comando'.
    """
    if not isinstance(cmd, dict):
        raise ValueError("Payload debe ser JSON object")

    # Compatibilidad: {command: "..."}
    if "command" in cmd and "comando" not in cmd:
        cmd = {**cmd, "comando": cmd.get("command")}

    comando = cmd.get("comando")
    param = cmd.get("param")

    if isinstance(comando, str):
        alias = _FRONTEND_ALIASES.get(comando)
        if alias:
            normalized = dict(alias)
            # Si alguien mandó param explícito, tiene prioridad
            if param is not None:
                normalized["param"] = param
            return normalized

        # Ya es comando estándar
        normalized = {"comando": comando.strip()}
        if param is not None:
            normalized["param"] = param
        return normalized

    raise ValueError("Campo 'comando' requerido")

@router.post("/control")
def send_command(cmd: dict):
    payload = _normalize_command_payload(cmd)

    client = mqtt.Client()
    if settings.MQTT_USERNAME:
        client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD or "")

    if settings.MQTT_TLS:
        tls_context = ssl.create_default_context()
        client.tls_set_context(tls_context)

    client.connect(settings.MQTT_BROKER, settings.MQTT_PORT, 60)

    message = json.dumps(payload)
    info = client.publish(settings.MQTT_TOPIC_COMANDOS, message, qos=0)
    # En TLS es común que se pierda si desconectamos inmediatamente.
    info.wait_for_publish(timeout=2)
    client.loop(timeout=2)
    client.disconnect()

    return {"status": "command sent", "topic": settings.MQTT_TOPIC_COMANDOS, "payload": payload}
