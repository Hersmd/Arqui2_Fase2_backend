# app/main.py
from fastapi import FastAPI
from app.services.mqtt_service import start_mqtt
from app.routes import control
from fastapi.middleware.cors import CORSMiddleware
from app.config.settings import settings

# Importa todas las rutas
from app.routes import events, kpis, state, auth, metrics, health

# Crea la instancia de FastAPI
app = FastAPI(title="EcoSort Backend")

# Conecta las rutas con prefijo /api
app.include_router(events.router, prefix="/api")
app.include_router(kpis.router, prefix="/api")
app.include_router(state.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(control.router, prefix="/api")
app.include_router(metrics.router, prefix="/api")
app.include_router(health.router, prefix="/api")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Evento de inicio: arrancar MQTT
@app.on_event("startup")
def startup_event():
    if settings.MONGO_URI == "mongodb://localhost:27017":
        print("[startup] MONGO_URI no está configurado (usando default local)")
    elif "USUARIO:CONTRASENA" in settings.MONGO_URI:
        print("[startup] MONGO_URI parece tener placeholder (USUARIO:CONTRASENA). Revisa variables de entorno en Render")
    else:
        print(f"[startup] MONGO_URI configurado (redactado), DB_NAME={settings.DB_NAME}")

    if settings.ENABLE_MQTT:
        start_mqtt()
        print("MQTT service started!")
    else:
        print("MQTT service disabled (ENABLE_MQTT=false)")

# Opcional: ruta base
@app.get("/")
def root():
    return {"message": "EcoSort API is running"}


#uvicorn app.main:app --reload