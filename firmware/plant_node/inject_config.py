Import("env")
import os
import re

print("Running inject_config.py...")

# 获取项目根目录 (现在 PlatformIO 项目根目录直接就是当前整个大项目的根目录)
root_dir = env.get("PROJECT_DIR")

# 优先读取真实的 hardware_config.toml，如果没有则读取 example
config_path = os.path.join(root_dir, "hardware_config.toml")
if not os.path.exists(config_path):
    config_path = os.path.join(root_dir, "hardware_config.example.toml")
    print(f"Warning: using {config_path} because hardware_config.toml not found")

wifi_ssid = ""
wifi_pwd = ""
mqtt_host = ""
mqtt_client_id = ""
topic = "sensor/esp32/aqua_data"
config_topic = "device/aqua/config"

try:
    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 优先匹配 [nodes.aqua]，向下兼容 [nodes.sub1]
    match = re.search(r'\[nodes\.aqua\](.*?)(?:\[nodes\.|$)', content, re.DOTALL)
    if not match:
        match = re.search(r'\[nodes\.sub1\](.*?)(?:\[nodes\.|$)', content, re.DOTALL)
    if match:
        section = match.group(1)
        s_match = re.search(r'wifi_ssid\s*=\s*"([^"]+)"', section)
        if s_match: wifi_ssid = s_match.group(1)
        
        p_match = re.search(r'wifi_password\s*=\s*"([^"]+)"', section)
        if p_match: wifi_pwd = p_match.group(1)
        
        h_match = re.search(r'mqtt_host\s*=\s*"([^"]+)"', section)
        if h_match: mqtt_host = h_match.group(1)
        
        c_match = re.search(r'mqtt_client_id\s*=\s*"([^"]+)"', section)
        if c_match: mqtt_client_id = c_match.group(1)

        t_match = re.search(r'topic\s*=\s*"([^"]+)"', section)
        if t_match: topic = t_match.group(1)

        cfg_match = re.search(r'config_topic\s*=\s*"([^"]+)"', section)
        if cfg_match: config_topic = cfg_match.group(1)
        
    print(f"Injected Config -> SSID: {wifi_ssid}, MQTT Host: {mqtt_host}, Topic: {topic}, ConfigTopic: {config_topic}")

    # 将提取到的配置转化为 C++ 的宏定义注入编译环境
    env.Append(CPPDEFINES=[
        ("WIFI_SSID", '\\"' + wifi_ssid + '\\"'),
        ("WIFI_PASSWORD", '\\"' + wifi_pwd + '\\"'),
        ("MQTT_HOST", '\\"' + mqtt_host + '\\"'),
        ("MQTT_CLIENT_ID", '\\"' + mqtt_client_id + '\\"'),
        ("MQTT_DATA_TOPIC", '\\"' + topic + '\\"'),
        ("MQTT_CONFIG_TOPIC", '\\"' + config_topic + '\\"')
    ])

except Exception as e:
    print(f"Error reading config: {e}")
