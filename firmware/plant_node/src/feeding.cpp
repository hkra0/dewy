#include "feeding.h"
#include "config.h"
#include "led.h"
#include <time.h>

static FeedingState state = {false, ""};
static unsigned long fed_timestamp = 0;
static int last_reset_day = -1;

static int last_touch_state = LOW;
static unsigned long last_debounce_time = 0;
static bool touch_processed = false;

void feeding_init() {
    pinMode(TOUCH_PIN, INPUT);
    Serial.println("👆 TTP223 触摸按键初始化完成");
}

FeedingState feeding_get_state() {
    return state;
}

static String get_current_time_str() {
    struct tm timeinfo;
    if (getLocalTime(&timeinfo, 10)) {
        char buf[16];
        snprintf(buf, sizeof(buf), "%02d:%02d", timeinfo.tm_hour, timeinfo.tm_min);
        return String(buf);
    }
    return "00:00";
}

void feeding_update(float water_temp, bool water_temp_ok) {
    unsigned long now = millis();

    // 1. 触摸按键检测 (带防抖与单次触发)
    int reading = digitalRead(TOUCH_PIN);
    if (reading != last_touch_state) {
        last_debounce_time = now;
    }
    last_touch_state = reading;

    if ((now - last_debounce_time) > TOUCH_DEBOUNCE_MS) {
        if (reading == HIGH && !touch_processed) {
            touch_processed = true;

            if (!state.is_fed) {
                // 首次触摸：记录已喂食
                state.is_fed = true;
                state.fed_time = get_current_time_str();
                fed_timestamp = now;
                Serial.printf("🐟 触摸确认喂食! 记录时间: %s (10秒内再次触摸可撤销)\n", state.fed_time.c_str());
            } else if (state.is_fed && (now - fed_timestamp <= FEED_CANCEL_WINDOW_MS)) {
                // 10 秒内二次触摸：撤销喂食
                state.is_fed = false;
                state.fed_time = "";
                Serial.println("↩️ 10秒内再次触摸：已撤销喂食确认 (恢复未喂食状态)");
            } else {
                // 平时已喂食状态下触摸：触发水温混色闪烁提示
                Serial.println("🌡️ 已喂食状态下触摸：触发水温指示闪烁");
                led_trigger_temp_flash(water_temp, water_temp_ok);
            }
        } else if (reading == LOW) {
            touch_processed = false;
        }
    }

    // 2. 每天本地时间定时重置喂食状态
    struct tm timeinfo;
    if (getLocalTime(&timeinfo, 10)) {
        if (timeinfo.tm_hour == rtConfig.feed_reset_hour && last_reset_day != timeinfo.tm_mday) {
            last_reset_day = timeinfo.tm_mday;
            state.is_fed = false;
            state.fed_time = "";
            Serial.printf("🌅 到达本地时间 %d:00，已重置今日喂食状态为未喂食\n", rtConfig.feed_reset_hour);
        }
    }
}
