#include <Arduino.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_AHTX0.h>
#include <Adafruit_BMP280.h>
#include <ArduinoJson.h>

// I2C 引脚定义
#define SDA_PIN 13
#define SCL_PIN 12

// 雾化器引脚定义
#define ATOMIZER_PIN 11

// 传感器与网络对象初始化
Adafruit_AHTX0 aht;
Adafruit_BMP280 bmp;
WiFiClient espClient;
PubSubClient client(espClient);

unsigned long lastSendTime = 0;

// MQTT 消息接收回调函数
void callback(char* topic, byte* payload, unsigned int length) {
  Serial.print("收到消息 [");
  Serial.print(topic);
  Serial.print("] ");
  String msg = "";
  for (unsigned int i = 0; i < length; i++) {
    msg += (char)payload[i];
  }
  Serial.println(msg);

  if (String(topic) == "device/esp32/atomizer/set") {
    if (msg == "ON" || msg == "1" || msg == "on") {
      digitalWrite(ATOMIZER_PIN, HIGH);
      Serial.println("-> 执行：开启雾化器");
    } else if (msg == "OFF" || msg == "0" || msg == "off") {
      digitalWrite(ATOMIZER_PIN, LOW);
      Serial.println("-> 执行：关闭雾化器");
    }
  }
}

void setup_wifi() {
  delay(10);
  Serial.println();
  Serial.print("正在连接 WiFi: ");
  Serial.println(WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("\nWiFi 连接成功!");
  Serial.print("ESP32 IP 地址: ");
  Serial.println(WiFi.localIP());

  // 启动 mDNS 客户端
  if (!MDNS.begin("esp32-sensor")) {
    Serial.println("mDNS 启动失败!");
  } else {
    Serial.println("mDNS 启动成功!");
  }
}

// 动态获取树莓派 IP 的函数
IPAddress getMqttServerIp() {
  Serial.printf("正在局域网内寻找 %s.local 的 IP...\n", MQTT_HOST);
  IPAddress serverIp;
  
  while (serverIp.toString() == "0.0.0.0" || serverIp.toString() == "(IP unset)") {
    serverIp = MDNS.queryHost(MQTT_HOST); // 发送 mDNS 广播查询
    
    if(serverIp.toString() != "0.0.0.0" && serverIp.toString() != "(IP unset)") {
      Serial.print("✅ 找到树莓派! IP地址是: ");
      Serial.println(serverIp);
      return serverIp;
    }
    Serial.println("未找到，1秒后重试...");
    delay(1000);
  }
  return serverIp;
}

void reconnect() {
  // 循环直到连接上 MQTT 服务器
  while (!client.connected()) {
    // 每次断开重连时，重新通过 mDNS 获取最新 IP
    IPAddress currentServerIp = getMqttServerIp();
    client.setServer(currentServerIp, 1883);

    Serial.print("尝试连接 MQTT 服务器...");
    // 建立连接
    if (client.connect(MQTT_CLIENT_ID)) {
      Serial.println("✅ 已连接到 MQTT!");
      // 连接成功后订阅雾化器控制主题
      client.subscribe("device/esp32/atomizer/set");
    } else {
      Serial.print("❌ 失败, 错误码 rc=");
      Serial.print(client.state());
      Serial.println(" 5秒后重试");
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(1);

  // 0. 初始化雾化器引脚
  pinMode(ATOMIZER_PIN, OUTPUT);
  digitalWrite(ATOMIZER_PIN, LOW); // 默认关闭

  // 1. 初始化 WiFi 和网络
  setup_wifi();

  // 设置 MQTT 回调
  client.setCallback(callback);

  // 2. 初始化 I2C 总线
  Wire.begin(SDA_PIN, SCL_PIN);

  // 3. 初始化 AHT20 传感器
  if (!aht.begin()) {
    Serial.println("未找到 AHT20 传感器！请检查接线。");
    while (1) delay(10);
  }
  Serial.println("AHT20 初始化成功!");

  // 4. 初始化 BMP280 传感器 (地址 0x77)
  if (!bmp.begin(0x77)) {
    Serial.println("未找到 BMP280 传感器！请检查接线。");
    while (1) delay(10);
  }
  // 配置 BMP280 参数
  bmp.setSampling(Adafruit_BMP280::MODE_NORMAL,
                  Adafruit_BMP280::SAMPLING_X2,
                  Adafruit_BMP280::SAMPLING_X16,
                  Adafruit_BMP280::FILTER_X16,
                  Adafruit_BMP280::STANDBY_MS_500);
  Serial.println("BMP280 初始化成功!");
}

void loop() {
  if (!client.connected()) {
    reconnect();
  }
  client.loop(); // 维持 MQTT 心跳并处理接收到的订阅消息

  unsigned long now = millis();
  // 每 5秒采集并发送一次数据（非阻塞方式）
  if (now - lastSendTime > 5000) {
    lastSendTime = now;

    // --- 读取传感器数据 ---
    sensors_event_t humidity, temp;
    aht.getEvent(&humidity, &temp); // 读取 AHT20

    float air_pressure = bmp.readPressure() / 100.0F; // 读取 BMP280 气压 (转换为 hPa)
    
    // 为了准确反映环境温度，这里采用 AHT20 的温度数据，BMP280 负责提供气压
    float current_temp = temp.temperature; 
    float current_hum = humidity.relative_humidity;

    // --- 使用 ArduinoJson 打包数据 ---
    StaticJsonDocument<200> doc;
    doc["temperature"] = serialized(String(current_temp, 2)); // 保留两位小数
    doc["humidity"] = serialized(String(current_hum, 2));
    doc["pressure"] = serialized(String(air_pressure, 2));

    char jsonBuffer[512];
    serializeJson(doc, jsonBuffer);

    // --- 发送数据到 MQTT ---
    Serial.print("正在发布数据: ");
    Serial.println(jsonBuffer);
    
    // 发布到 sensor/esp32/env_data 主题
    client.publish("sensor/esp32/env_data", jsonBuffer);
  }
}
