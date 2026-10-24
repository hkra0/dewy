Import("env")
import json
import os
import secrets
from pathlib import Path
try:
    import tomllib
except ImportError:
    import tomli as tomllib

root = Path(env.get("PROJECT_DIR"))
# Rollback needs the real SDK/bootloader option and Arduino's delayed-check hook.
# A compiler -D cannot retrofit a precompiled bootloader. Fail the build on an
# incompatible framework rather than publish an unprotected OTA image.
framework = Path(env.PioPlatform().get_package_dir("framework-arduinoespressif32"))
sdk = framework / "tools" / "sdk" / env.BoardConfig().get("build.mcu") / "sdkconfig"
sdk_text = sdk.read_text(encoding="utf-8")
core_text = (framework / "cores" / "esp32" / "esp32-hal-misc.c").read_text(encoding="utf-8")
if ("CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE=y" not in sdk_text
        or "CONFIG_APP_ROLLBACK_ENABLE=y" not in sdk_text
        or "if(!verifyRollbackLater())" not in core_text):
    raise ValueError("Framework must provide rollback-enabled SDK/bootloader and verifyRollbackLater hook")
path = root / "hardware_config.toml"
if not path.exists():
    path = root / "hardware_config.example.toml"
node_id = os.environ.get("DEWY_NODE") or env.GetProjectOption("custom_node", "")
if not node_id:
    raise ValueError("Select a target with DEWY_NODE or PlatformIO custom_node")
with path.open("rb") as f:
    node = tomllib.load(f)["nodes"][node_id]
if node.get("type") != "mqtt_node":
    raise ValueError("Firmware target must be a mqtt_node")
definitions = {"WIFI_SSID": node["wifi_ssid"], "WIFI_PASSWORD": node["wifi_password"],
               "MQTT_HOST": node["mqtt_host"], "MQTT_CLIENT_ID": node["mqtt_client_id"],
               "MQTT_DATA_TOPIC": node["topic"], "MQTT_CONFIG_TOPIC": node["config_topic"]}
key = os.environ.get("DEWY_MAINTENANCE_KEY", node.get("maintenance_key", ""))
if key and (len(key) < 32 or not key.isascii()):
    raise ValueError("maintenance_key must be ASCII and at least 32 characters")
definitions.update(DEWY_NODE_ID=node_id, DEWY_BOARD=env.BoardConfig().id,
                   DEWY_BUILD_ID=secrets.token_hex(16), DEWY_MAINTENANCE_KEY=key)
if not key:
    print("Remote maintenance disabled: configure maintenance_key before the first USB flash")
env.Append(CPPDEFINES=[(key, env.StringifyMacro(value)) for key, value in definitions.items()])
print(f"Firmware target: {node_id}")
