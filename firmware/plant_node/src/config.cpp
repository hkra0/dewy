#include "config.h"
#include <Preferences.h>
#include <ArduinoJson.h>

RuntimeConfig rtConfig;
static Preferences prefs;

void config_init() {
    prefs.begin("aqua_cfg", true);  // 只读模式打开
    rtConfig.temp_alarm_high = prefs.getFloat("t_high", 32.0f);
    rtConfig.temp_alarm_low  = prefs.getFloat("t_low",  18.0f);
    rtConfig.feed_reset_hour = prefs.getInt("feed_hr", 7);
    prefs.end();

    Serial.println("⚙️ 已从 NVS 加载配置:");
    Serial.printf("   - 高温报警: %.1f ℃\n", rtConfig.temp_alarm_high);
    Serial.printf("   - 低温报警: %.1f ℃\n", rtConfig.temp_alarm_low);
    Serial.printf("   - 喂食重置时刻: %d:00\n", rtConfig.feed_reset_hour);
}

void config_apply(const char* json) {
    StaticJsonDocument<256> doc;
    DeserializationError error = deserializeJson(doc, json);
    if (error) {
        Serial.printf("❌ JSON 解析失败: %s\n", error.c_str());
        return;
    }

    bool changed = false;
    if (doc.containsKey("temp_alarm_high")) {
        rtConfig.temp_alarm_high = doc["temp_alarm_high"].as<float>();
        changed = true;
    }
    if (doc.containsKey("temp_alarm_low")) {
        rtConfig.temp_alarm_low = doc["temp_alarm_low"].as<float>();
        changed = true;
    }
    if (doc.containsKey("feed_reset_hour")) {
        rtConfig.feed_reset_hour = doc["feed_reset_hour"].as<int>();
        changed = true;
    }

    if (changed) {
        prefs.begin("aqua_cfg", false);  // 读写模式
        prefs.putFloat("t_high", rtConfig.temp_alarm_high);
        prefs.putFloat("t_low",  rtConfig.temp_alarm_low);
        prefs.putInt("feed_hr",  rtConfig.feed_reset_hour);
        prefs.end();

        Serial.println("💾 远程配置已更新并持久化至 NVS:");
        Serial.printf("   - 高温报警: %.1f ℃\n", rtConfig.temp_alarm_high);
        Serial.printf("   - 低温报警: %.1f ℃\n", rtConfig.temp_alarm_low);
        Serial.printf("   - 喂食重置时刻: %d:00\n", rtConfig.feed_reset_hour);
    }
}

String config_to_json() {
    StaticJsonDocument<256> doc;
    doc["temp_alarm_high"] = serialized(String(rtConfig.temp_alarm_high, 1));
    doc["temp_alarm_low"]  = serialized(String(rtConfig.temp_alarm_low, 1));
    doc["feed_reset_hour"] = rtConfig.feed_reset_hour;

    String out;
    serializeJson(doc, out);
    return out;
}
