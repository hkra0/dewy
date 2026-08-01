# 日志必须在任何 core 模块导入前配置好，
# 否则 core.state / hardware.manager 的启动期日志会丢失（故意不放在 import 块顶部）。
from core.logging_setup import setup_logging

setup_logging()

import logging  # noqa: E402
import threading  # noqa: E402

import uvicorn  # noqa: E402
import paho.mqtt.client as mqtt  # noqa: E402
from fastapi import FastAPI  # noqa: E402

import core.state as state  # noqa: E402
import core.config as config  # noqa: E402
from core.mqtt_handler import on_mqtt_connect, on_mqtt_message  # noqa: E402
from core.logic import background_logger, local_sensor_updater  # noqa: E402
from api.routers import router  # noqa: E402

logger = logging.getLogger(__name__)

MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883
MQTT_KEEPALIVE = 60

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
        mqtt_client.connect(MQTT_HOST, MQTT_PORT, MQTT_KEEPALIVE)
        mqtt_client.loop_start()
        state.global_mqtt_client = mqtt_client
    except OSError as e:
        # broker 未启动/端口不通：本地传感器与浇水仍可用，只是 MQTT 节点和灯控失效
        logger.error("MQTT 连接失败 (%s:%s): %s", MQTT_HOST, MQTT_PORT, e)
    except Exception:
        logger.exception("MQTT 启动异常")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
