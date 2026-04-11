import paho.mqtt.client as mqtt
import os
import ssl

def on_message(client, userdata, msg):
    print("Mensaje recibido:")
    print("Topic:", msg.topic)
    print("Payload:", msg.payload.decode())

client = mqtt.Client()
client.on_message = on_message

broker = os.getenv("MQTT_BROKER", "broker.hivemq.com")
port = int(os.getenv("MQTT_PORT", "1883"))
use_tls = os.getenv("MQTT_TLS", "false").lower() in ("1", "true", "yes", "on")
username = os.getenv("MQTT_USERNAME")
password = os.getenv("MQTT_PASSWORD")
topic = os.getenv("MQTT_TOPIC", "ecosort/comandos")

if username:
    client.username_pw_set(username, password or "")

if use_tls:
    tls_context = ssl.create_default_context()
    client.tls_set_context(tls_context)

client.connect(broker, port)
client.subscribe(topic)

print("Escuchando comandos MQTT... topic=", topic)
client.loop_forever()