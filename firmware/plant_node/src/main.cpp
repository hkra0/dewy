#include <Arduino.h>
#include "config.h"
#include "sensors.h"
#include "led.h"
#include "feeding.h"
#include "network.h"

static unsigned long lastSendTime = 0;
static SensorReadings lastReadings = {};

void setup() {
    Serial.begin(115200);
    delay(2000);
    Serial.println("\n========== ESP32 鱼缸监控节点启动 ==========");

    config_init();     // 1. 从 NVS 读取用户配置
    led_init();        // 2. 初始化 WS2812B RGB 灯
    feeding_init();    // 3. 初始化 TTP223 触摸按键
    sensors_init();    // 4. 初始化 AHT20, BMP280, DS18B20 传感器
    network_init();    // 5. 初始化 WiFi、mDNS、NTP、MQTT
}

void loop() {
    network_loop(); // 维持 MQTT 连接与心跳

    // 传感器采样周期 (5秒)
    unsigned long now = millis();
    if (now - lastSendTime >= SENSOR_INTERVAL_MS) {
        lastSendTime = now;
        lastReadings = sensors_read();
        FeedingState f = feeding_get_state();
        network_publish_data(lastReadings, f);
    }

    // 喂食状态机更新 (检测触摸与每日定时重置)
    feeding_update(lastReadings.water_temp, lastReadings.water_temp_ok);

    // RGB 灯效更新 (温度报警 > 触摸闪烁 > 未喂食呼吸 > 已喂食灭)
    FeedingState currentFeeding = feeding_get_state();
    led_update(currentFeeding.is_fed, lastReadings.water_temp, lastReadings.water_temp_ok);

    delay(10); // 微小延时出让 CPU
}
