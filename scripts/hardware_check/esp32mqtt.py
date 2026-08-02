import paho.mqtt.client as mqtt
import json

# 当连接到 Broker 时触发
def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("✅ 已成功连接到本地 MQTT Broker")
        # 订阅 ESP32 发送数据的主题
        client.subscribe("sensor/esp32/env_data")
    else:
        print(f"❌ 连接失败，返回码: {reason_code}")

# 当收到消息时触发
def on_message(client, userdata, msg):
    try:
        # 接收并解析 JSON 格式的数据
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)
        
        # 提取温湿度和气压
        temp = data.get('temperature')
        hum = data.get('humidity')
        pressure = data.get('pressure')
        
        print(f"📡 收到实时环境数据 -> 温度: {temp} °C | 湿度: {hum} % | 气压: {pressure} hPa")
        
        # ==========================================
        # 这里可以加入你的后续逻辑，例如：
        # 1. 写入 SQLite 数据库
        # 2. 判断如果土壤/环境太干，发布控制水泵的 MQTT 指令
        #    client.publish("esp32/pump/control", '{"action": "ON"}')
        # ==========================================
        
    except json.JSONDecodeError:
        print("❌ 数据解析失败，收到的不是有效 JSON 格式")
    except Exception as e:
        print(f"❌ 发生未知错误: {e}")

# 初始化 MQTT 客户端，显式声明使用最新的 VERSION2 API 以消除警告
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message

# 连接到本地 Broker (127.0.0.1)
try:
    client.connect("127.0.0.1", 1883, 60)
    print("🚀 开始监听 ESP32 传感器数据...")
    # 永久循环，保持连接并接收消息
    client.loop_forever()
except KeyboardInterrupt:
    print("\n🛑 程序已手动停止")
    client.disconnect()
except Exception as e:
    print(f"连接 MQTT 服务器出错: {e}")