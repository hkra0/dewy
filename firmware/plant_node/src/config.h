#pragma once
#include <Arduino.h>

// I2C 引脚定义 (AHT20 + BMP280)
#define SDA_PIN          12
#define SCL_PIN          13

// DS18B20 水温传感器引脚
#define DS18B20_PIN      11

// WS2812B RGB 灯引脚与数量
#define WS2812B_PIN      10
#define NUM_LEDS          1

// TTP223 触摸传感器引脚
#define TOUCH_PIN         9

// 常量
#define SENSOR_INTERVAL_MS      5000UL
#define TOUCH_DEBOUNCE_MS       50UL
#define LONG_PRESS_MS           1500UL
#define FEED_CANCEL_WINDOW_MS   10000UL

#include "aqua_model.h"
using RuntimeConfig = aqua::Config;
extern RuntimeConfig rtConfig;
void config_init();
bool config_apply(const char* json);
String config_to_json();
