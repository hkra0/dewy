import threading
import uvicorn
import paho.mqtt.client as mqtt
from fastapi import FastAPI

import core.state as state
import core.config as config
from core.mqtt_handler import on_mqtt_connect, on_mqtt_message
from core.logic import background_logger, local_sensor_updater
from api.routers import router

app = FastAPI(title="Robin Plant Monitor BFF")
app.include_router(router)

@app.on_event("startup")
def start_background_logger():
    config.load_config()
    threading.Thread(target=background_logger, daemon=True).start()
    threading.Thread(target=local_sensor_updater, daemon=True).start()
    
    try:
        mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        mqtt_client.on_connect = on_mqtt_connect
        mqtt_client.on_message = on_mqtt_message
        mqtt_client.connect("127.0.0.1", 1883, 60)
        mqtt_client.loop_start()
        state.global_mqtt_client = mqtt_client
    except Exception as e:
        print(f"MQTT 启动失败: {e}")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)