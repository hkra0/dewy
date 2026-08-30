#pragma once
#include <Arduino.h>

struct SensorReadings {
    float temperature;   // 环境温度 (AHT20, ℃)
    bool  temp_ok;
    float humidity;      // 环境湿度 (AHT20, %)
    bool  hum_ok;
    float pressure;      // 气压 (BMP280, hPa)
    bool  press_ok;
    float water_temp;    // 水温 (DS18B20, ℃)
    bool  water_temp_ok; // 水温是否有效
};

void sensors_init();
SensorReadings sensors_read();
