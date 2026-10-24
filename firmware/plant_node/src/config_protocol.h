#pragma once
#include "aqua_model.h"
#include <ArduinoJson.h>
#include <string>
namespace aqua {
inline std::string config_values(const Config& c) {
    JsonDocument doc;
    doc["temp_alarm_high"]=c.temp_alarm_high;
    doc["temp_alarm_low"]=c.temp_alarm_low;
    doc["low_alarm_enabled"]=c.low_alarm_enabled;
    doc["feed_start_hour"]=c.start_hour;
    doc["feed_end_hour"]=c.end_hour;
    doc["feed_min_temp"]=c.feed_min_temp;
    doc["feed_max_temp"]=c.feed_max_temp;
    doc["feed_rate_1"]=c.rate1;
    doc["feed_rate_2"]=c.rate2;
    doc["feed_rate_3"]=c.rate3;
    doc["feed_rate_4"]=c.rate4;
    doc["feed_threshold"]=c.score_threshold;
    doc["feed_score_cap"]=c.score_cap;
    doc["temp_change_threshold"]=c.change_threshold;
    doc["temp_change_minutes"]=c.change_minutes;
    doc["skip_cycle"]=c.skip_cycle;
    doc["feeding_mode"]=c.accumulation ? "temperature_accumulation" : "daily";
    std::string text; serializeJson(doc,text); return text;
}
inline bool parse_config(const std::string& text,const Config& base,Config& out,std::string& error) {
    JsonDocument doc;
    if(text.size()>=2048 || deserializeJson(doc,text) || !doc.is<JsonObject>()) {
        error="invalid_json"; return false;
    }
    Config c=base;
    if(doc.containsKey("temp_alarm_high")) {
        if(!doc["temp_alarm_high"].is<float>() || !std::isfinite(doc["temp_alarm_high"].as<double>()) || doc["temp_alarm_high"].as<double>()<-10 || doc["temp_alarm_high"].as<double>()>60) { error="temp_alarm_high"; return false; }
        c.temp_alarm_high=doc["temp_alarm_high"].as<float>();
    }
    if(doc.containsKey("temp_alarm_low")) {
        if(!doc["temp_alarm_low"].is<float>() || !std::isfinite(doc["temp_alarm_low"].as<double>()) || doc["temp_alarm_low"].as<double>()<-20 || doc["temp_alarm_low"].as<double>()>40) { error="temp_alarm_low"; return false; }
        c.temp_alarm_low=doc["temp_alarm_low"].as<float>();
    }
    if(doc.containsKey("low_alarm_enabled")) {
        if(!doc["low_alarm_enabled"].is<bool>()) { error="low_alarm_enabled"; return false; }
        c.low_alarm_enabled=doc["low_alarm_enabled"].as<bool>();
    }
    if(doc.containsKey("feed_start_hour")) {
        if(!doc["feed_start_hour"].is<int>() || !std::isfinite(doc["feed_start_hour"].as<double>()) || doc["feed_start_hour"].as<double>()<0 || doc["feed_start_hour"].as<double>()>23) { error="feed_start_hour"; return false; }
        c.start_hour=doc["feed_start_hour"].as<int>();
    }
    if(doc.containsKey("feed_end_hour")) {
        if(!doc["feed_end_hour"].is<int>() || !std::isfinite(doc["feed_end_hour"].as<double>()) || doc["feed_end_hour"].as<double>()<1 || doc["feed_end_hour"].as<double>()>24) { error="feed_end_hour"; return false; }
        c.end_hour=doc["feed_end_hour"].as<int>();
    }
    if(doc.containsKey("feed_min_temp")) {
        if(!doc["feed_min_temp"].is<float>() || !std::isfinite(doc["feed_min_temp"].as<double>()) || doc["feed_min_temp"].as<double>()<-10 || doc["feed_min_temp"].as<double>()>12.4) { error="feed_min_temp"; return false; }
        c.feed_min_temp=doc["feed_min_temp"].as<float>();
    }
    if(doc.containsKey("feed_max_temp")) {
        if(!doc["feed_max_temp"].is<float>() || !std::isfinite(doc["feed_max_temp"].as<double>()) || doc["feed_max_temp"].as<double>()<20.1 || doc["feed_max_temp"].as<double>()>45) { error="feed_max_temp"; return false; }
        c.feed_max_temp=doc["feed_max_temp"].as<float>();
    }
    if(doc.containsKey("feed_rate_1")) {
        if(!doc["feed_rate_1"].is<float>() || !std::isfinite(doc["feed_rate_1"].as<double>()) || doc["feed_rate_1"].as<double>()<0 || doc["feed_rate_1"].as<double>()>20) { error="feed_rate_1"; return false; }
        c.rate1=doc["feed_rate_1"].as<float>();
    }
    if(doc.containsKey("feed_rate_2")) {
        if(!doc["feed_rate_2"].is<float>() || !std::isfinite(doc["feed_rate_2"].as<double>()) || doc["feed_rate_2"].as<double>()<0 || doc["feed_rate_2"].as<double>()>20) { error="feed_rate_2"; return false; }
        c.rate2=doc["feed_rate_2"].as<float>();
    }
    if(doc.containsKey("feed_rate_3")) {
        if(!doc["feed_rate_3"].is<float>() || !std::isfinite(doc["feed_rate_3"].as<double>()) || doc["feed_rate_3"].as<double>()<0 || doc["feed_rate_3"].as<double>()>20) { error="feed_rate_3"; return false; }
        c.rate3=doc["feed_rate_3"].as<float>();
    }
    if(doc.containsKey("feed_rate_4")) {
        if(!doc["feed_rate_4"].is<float>() || !std::isfinite(doc["feed_rate_4"].as<double>()) || doc["feed_rate_4"].as<double>()<0 || doc["feed_rate_4"].as<double>()>20) { error="feed_rate_4"; return false; }
        c.rate4=doc["feed_rate_4"].as<float>();
    }
    if(doc.containsKey("feed_threshold")) {
        if(!doc["feed_threshold"].is<float>() || !std::isfinite(doc["feed_threshold"].as<double>()) || doc["feed_threshold"].as<double>()<1 || doc["feed_threshold"].as<double>()>1000) { error="feed_threshold"; return false; }
        c.score_threshold=doc["feed_threshold"].as<float>();
    }
    if(doc.containsKey("feed_score_cap")) {
        if(!doc["feed_score_cap"].is<float>() || !std::isfinite(doc["feed_score_cap"].as<double>()) || doc["feed_score_cap"].as<double>()<1 || doc["feed_score_cap"].as<double>()>1200) { error="feed_score_cap"; return false; }
        c.score_cap=doc["feed_score_cap"].as<float>();
    }
    if(doc.containsKey("temp_change_threshold")) {
        if(!doc["temp_change_threshold"].is<float>() || !std::isfinite(doc["temp_change_threshold"].as<double>()) || doc["temp_change_threshold"].as<double>()<0.1 || doc["temp_change_threshold"].as<double>()>20) { error="temp_change_threshold"; return false; }
        c.change_threshold=doc["temp_change_threshold"].as<float>();
    }
    if(doc.containsKey("temp_change_minutes")) {
        if(!doc["temp_change_minutes"].is<int>() || !std::isfinite(doc["temp_change_minutes"].as<double>()) || doc["temp_change_minutes"].as<double>()<5 || doc["temp_change_minutes"].as<double>()>60) { error="temp_change_minutes"; return false; }
        c.change_minutes=doc["temp_change_minutes"].as<int>();
    }
    if(doc.containsKey("skip_cycle")) {
        if(!doc["skip_cycle"].is<bool>()) { error="skip_cycle"; return false; }
        c.skip_cycle=doc["skip_cycle"].as<bool>();
    }
    if(doc.containsKey("feeding_mode")) {
        const char* mode=doc["feeding_mode"].as<const char*>();
        if(!mode || (strcmp(mode,"daily") && strcmp(mode,"temperature_accumulation"))) {
            error="feeding_mode"; return false;
        }
        c.accumulation=!strcmp(mode,"temperature_accumulation");
    }
    if(!doc.containsKey("feed_start_hour") && doc.containsKey("feed_reset_hour")) {
        if(!doc["feed_reset_hour"].is<int>()) { error="feed_reset_hour"; return false; }
        c.start_hour=doc["feed_reset_hour"].as<int>();
    }
    if(!c.valid()) { error="inconsistent_fields"; return false; }
    out=c; error.clear(); return true;
}
} // namespace aqua
