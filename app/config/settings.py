from pydantic_settings import BaseSettings
from dotenv import load_dotenv
from pathlib import Path
from typing import Optional


# Carga variables desde backend/.env (si existe)
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=False)

class Settings(BaseSettings):
    # Render: configura esto como variable de entorno (no hardcodear secretos en git)
    MONGO_URI: str = "mongodb://localhost:27017"
    DB_NAME: str = "ecosort"

    MQTT_BROKER: str = "broker.hivemq.com"
    MQTT_PORT: int = 1883

    MQTT_TLS: bool = False
    MQTT_USERNAME: Optional[str] = None
    MQTT_PASSWORD: Optional[str] = None

    MQTT_TOPIC_EVENTS: str = "ecosort/events"
    MQTT_TOPIC_STATE: str = "ecosort/state"
    MQTT_TOPIC_ALERTS: str = "ecosort/alerts"

    # Compatibilidad con el script de Raspberry (tópicos en español)
    MQTT_TOPIC_EVENTOS: str = "ecosort/eventos"
    MQTT_TOPIC_COMANDOS: str = "ecosort/comandos"

    # Lista de tópicos a suscribir (separados por coma). Si es None/vacío, se usan los default.
    # Ej: MQTT_SUBSCRIBE_TOPICS=ecosort/eventos
    MQTT_SUBSCRIBE_TOPICS: Optional[str] = None

    # Permite ejecutar el backend sin iniciar el listener MQTT (útil en Render si separas web/worker)
    ENABLE_MQTT: bool = True

    # Logging: imprime cada documento insertado en MongoDB (Atlas)
    LOG_MONGO_INSERTS: bool = True
    LOG_MONGO_INSERTS_MAX_CHARS: int = 2000

settings = Settings()