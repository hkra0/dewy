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

try:
    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 使用正则表达式提取 [nodes.sub1] 节点下的配置项
    # 这里用正则避免强依赖 toml/tomli 库，让 PlatformIO 原生 Python 环境直接能跑
    match = re.search(r'\[nodes\.sub1\](.*?)(?:\[|$)', content, re.DOTALL)
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
        
    print(f"Injected Config -> SSID: {wifi_ssid}, MQTT Host: {mqtt_host}")

    # 将提取到的配置转化为 C++ 的宏定义注入编译环境
    env.Append(CPPDEFINES=[
        ("WIFI_SSID", '\\"' + wifi_ssid + '\\"'),
        ("WIFI_PASSWORD", '\\"' + wifi_pwd + '\\"'),
        ("MQTT_HOST", '\\"' + mqtt_host + '\\"'),
        ("MQTT_CLIENT_ID", '\\"' + mqtt_client_id + '\\"')
    ])

except Exception as e:
    print(f"Error reading config: {e}")
