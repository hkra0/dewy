#include "feeding.h"
#include "config.h"
#include "led.h"
#include <time.h>
#include <Preferences.h>

static FeedingState state = {false, ""};
static unsigned long fed_timestamp = 0;
static int last_reset_day = -1;

static int last_touch_state = LOW;
static unsigned long last_debounce_time = 0;
static bool touch_processed = false;

static Preferences feedPrefs;

// ---- NVS 持久化辅助 ----

static void save_feeding_state() {
    struct tm ti;
    feedPrefs.begin("feed_st", false);
    feedPrefs.putBool("is_fed", state.is_fed);
    feedPrefs.putString("fed_time", state.fed_time);
    // 记录日历天 (tm_yday)，重启后据此判断是否跨天
    if (getLocalTime(&ti, 10)) {
        feedPrefs.putInt("fed_yday", ti.tm_yday);
    }
    feedPrefs.end();
}

void feeding_init() {
    pinMode(TOUCH_PIN, INPUT);

    // 从 NVS 恢复喂食状态——仅当记录属于当天时才恢复
    feedPrefs.begin("feed_st", true);  // 只读
    bool saved_fed     = feedPrefs.getBool("is_fed", false);
    String saved_time  = feedPrefs.getString("fed_time", "");
    int saved_yday     = feedPrefs.getInt("fed_yday", -1);
    feedPrefs.end();

    if (saved_fed) {
        struct tm timeinfo;
        // 给 NTP 同步留足时间；超时则不恢复（宁可少显示，不要错显示）
        if (getLocalTime(&timeinfo, 5000) && timeinfo.tm_yday == saved_yday) {
            state.is_fed = true;
            state.fed_time = saved_time;
            Serial.printf("🔁 从 NVS 恢复今日喂食状态: %s\n", saved_time.c_str());
        } else {
            Serial.println("⏭️ NVS 中有喂食记录但非当天或 NTP 未就绪，不恢复");
        }
    }

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
                save_feeding_state();
                Serial.printf("🐟 触摸确认喂食! 记录时间: %s (10秒内再次触摸可撤销)\n", state.fed_time.c_str());
            } else if (state.is_fed && (now - fed_timestamp <= FEED_CANCEL_WINDOW_MS)) {
                // 10 秒内二次触摸：撤销喂食
                state.is_fed = false;
                state.fed_time = "";
                save_feeding_state();
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
            save_feeding_state();
            Serial.printf("🌅 到达本地时间 %d:00，已重置今日喂食状态为未喂食\n", rtConfig.feed_reset_hour);
        }
    }
}
