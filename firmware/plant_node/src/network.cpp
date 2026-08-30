#include "network.h"
#include "config.h"
#include <WiFi.h>
#include <ESPmDNS.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

#ifndef WIFI_SSID
#define WIFI_SSID "YOUR_WIFI_SSID"
#endif

#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
#endif

#ifndef MQTT_HOST
#define MQTT_HOST "robin"
#endif

#ifndef MQTT_CLIENT_ID
#define MQTT_CLIENT_ID "ESP32_Aqua_Node"
#endif

#ifndef MQTT_DATA_TOPIC
#define MQTT_DATA_TOPIC "sensor/esp32/aqua_data"
#endif

#ifndef MQTT_CONFIG_TOPIC
#define MQTT_CONFIG_TOPIC "device/aqua/config"
#endif

static WiFiClient espClient;
static PubSubClient client(espClient);

static unsigned long lastSuccessTime = 0;
#define WIFI_CONNECT_TIMEOUT_MS 30000UL
#define MDNS_LOOKUP_TIMEOUT_MS 30000UL
#define MQTT_RECONNECT_TIMEOUT_MS 120000UL
#define WATCHDOG_TIMEOUT_MS (5UL * 60UL * 1000UL)

void network_publish_config_state() {
    String stateJson = config_to_json();
    String topic = String(MQTT_CONFIG_TOPIC) + "/state";
    if (client.connected()) {
        client.publish(topic.c_str(), stateJson.c_str(), true); // retain = true
        Serial.printf("📤 已上报配置状态至 %s: %s\n", topic.c_str(), stateJson.c_str());
    }
}

static void mqtt_callback(char* topic, byte* payload, unsigned int length) {
    String topicStr = String(topic);
    String msg = "";
    for (unsigned int i = 0; i < length; i++) {
        msg += (char)payload[i];
    }
    Serial.printf("📥 收到 MQTT 消息 [%s]: %s\n", topicStr.c_str(), msg.c_str());

    String setTopic = String(MQTT_CONFIG_TOPIC) + "/set";
    if (topicStr == setTopic) {
        config_apply(msg.c_str());
        network_publish_config_state();
    }
}

static void setup_wifi() {
    Serial.printf("正在连接 WiFi: %s\n", WIFI_SSID);
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    unsigned long startTime = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - startTime > WIFI_CONNECT_TIMEOUT_MS) {
            Serial.println("\n⚠️ WiFi 连接超时，重启设备重试...");
            ESP.restart();
        }
        delay(500);
        Serial.print(".");
    }

    Serial.println("\n✅ WiFi 连接成功!");
    Serial.print("ESP32 IP: ");
    Serial.println(WiFi.localIP());

    if (MDNS.begin("esp32-aqua")) {
        Serial.println("✅ mDNS 启动成功!");
    }

    // 配置 NTP 获取东八区时间
    configTzTime("CST-8", "ntp.aliyun.com", "pool.ntp.org", "time.nist.gov");
    Serial.println("⏰ 已启动 NTP 时间同步 (CST-8)");
}

static IPAddress getMqttServerIp() {
    Serial.printf("🔍 正在局域网内寻找 %s.local 的 IP...\n", MQTT_HOST);
    IPAddress serverIp;
    unsigned long startTime = millis();

    while (serverIp.toString() == "0.0.0.0" || serverIp.toString() == "(IP unset)") {
        serverIp = MDNS.queryHost(MQTT_HOST);
        if (serverIp.toString() != "0.0.0.0" && serverIp.toString() != "(IP unset)") {
            Serial.print("✅ 找到 MQTT Broker! IP: ");
            Serial.println(serverIp);
            return serverIp;
        }
        if (millis() - startTime > MDNS_LOOKUP_TIMEOUT_MS) {
            Serial.println("⚠️ mDNS 查找超时，本轮放弃");
            return IPAddress(0, 0, 0, 0);
        }
        delay(1000);
    }
    return serverIp;
}

static void reconnect_mqtt() {
    unsigned long startTime = millis();
    while (!client.connected()) {
        if (millis() - startTime > MQTT_RECONNECT_TIMEOUT_MS) {
            Serial.println("⚠️ MQTT 重连超时，重启设备...");
            ESP.restart();
        }

        IPAddress currentServerIp = getMqttServerIp();
        if (currentServerIp == IPAddress(0, 0, 0, 0)) {
            delay(1000);
            continue;
        }
        client.setServer(currentServerIp, 1883);

        Serial.print("正在连接 MQTT Broker...");
        if (client.connect(MQTT_CLIENT_ID)) {
            Serial.println(" ✅ 已连接!");
            lastSuccessTime = millis();

            // 订阅配置下发主题
            String setTopic = String(MQTT_CONFIG_TOPIC) + "/set";
            client.subscribe(setTopic.c_str());
            Serial.printf("📡 已订阅配置下发主题: %s\n", setTopic.c_str());

            // 连接建立后主动回报一次当前配置
            network_publish_config_state();
        } else {
            Serial.printf(" ❌ 失败, rc=%d，5秒后重试\n", client.state());
            delay(5000);
        }
    }
}

void network_init() {
    setup_wifi();
    client.setCallback(mqtt_callback);
    client.setBufferSize(512);
    lastSuccessTime = millis();
}

void network_loop() {
    if (!client.connected()) {
        reconnect_mqtt();
    }
    client.loop();

    if (millis() - lastSuccessTime > WATCHDOG_TIMEOUT_MS) {
        Serial.println("⚠️ 超过 5 分钟未能成功发布数据，看门狗触发重启...");
        ESP.restart();
    }
}

bool network_publish_data(const SensorReadings& sensors, const FeedingState& feeding) {
    if (!client.connected()) return false;

    StaticJsonDocument<300> doc;
    if (sensors.temp_ok) {
        doc["temperature"] = serialized(String(sensors.temperature, 2));
    }
    if (sensors.hum_ok) {
        doc["humidity"] = serialized(String(sensors.humidity, 2));
    }
    if (sensors.press_ok) {
        doc["pressure"] = serialized(String(sensors.pressure, 2));
    }
    if (sensors.water_temp_ok) {
        doc["water_temp"] = serialized(String(sensors.water_temp, 2));
    }

    doc["fed"] = feeding.is_fed ? 1 : 0;
    if (feeding.is_fed && feeding.fed_time.length() > 0) {
        doc["fed_time"] = feeding.fed_time;
    }

    char jsonBuffer[512];
    serializeJson(doc, jsonBuffer);

    Serial.printf("📤 发布传感器数据 [%s]: %s\n", MQTT_DATA_TOPIC, jsonBuffer);
    bool ok = client.publish(MQTT_DATA_TOPIC, jsonBuffer);
    if (ok) {
        lastSuccessTime = millis();
    } else {
        Serial.println("⚠️ MQTT 数据发布失败");
    }
    return ok;
}
