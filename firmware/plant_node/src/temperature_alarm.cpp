#include "temperature_alarm.h"
#include "config.h"
#include <Preferences.h>
#include <ArduinoJson.h>
#include <time.h>
aqua::Alarms temperature_alarms;
aqua::Time local_time_now() {
    aqua::Time n; n.ms=millis();
    time_t epoch=time(nullptr);
    if(epoch<1704067200) return n;
    n.utc=epoch;
    tm t; localtime_r(&epoch,&t);
    n.date=(t.tm_year+1900)*10000+(t.tm_mon+1)*100+t.tm_mday; n.hour=t.tm_hour;
    t.tm_mday++; t.tm_hour=12; mktime(&t);
    n.tomorrow=(t.tm_year+1900)*10000+(t.tm_mon+1)*100+t.tm_mday;
    return n;
}
void temperature_alarm_init() {
    Preferences p; p.begin("aqua_alarm",true); String json=p.getString("v2",""); p.end();
    StaticJsonDocument<2048> doc;
    if(deserializeJson(doc,json)) return;
    for(int i=0;i<aqua::AlarmCount;i++) {
        JsonVariant d=doc[i]; auto& e=temperature_alarms.events[i];
        e.active=d["active"] | false; e.id=d["id"] | 0u;
        e.acknowledged=d["ack"] | false;
        e.triggered_utc=d["triggered"].as<int64_t>();
        e.silent_until=d["until"].as<int64_t>();
        if(i==aqua::Change) temperature_alarms.direction=d["direction"] | 0;
        // A reboot must not restart flashing an already active event.
        e.silenced=e.active;
    }
}
void temperature_alarm_save() {
    if(!temperature_alarms.dirty) return;
    StaticJsonDocument<2048> doc;
    auto arr=doc.to<JsonArray>();
    for(int i=0;i<aqua::AlarmCount;i++) {
        const auto& e=temperature_alarms.events[i]; auto d=arr.createNestedObject();
        d["active"]=e.active; d["id"]=e.id; d["ack"]=e.acknowledged;
        d["triggered"]=e.triggered_utc; d["until"]=e.silent_until;
        if(i==aqua::Change) d["direction"]=temperature_alarms.direction;
    }
    String json; serializeJson(doc,json);
    Preferences p; p.begin("aqua_alarm",false); p.putString("v2",json); p.end();
    temperature_alarms.dirty=false;
}
void temperature_alarm_update(const aqua::Sample& sample) {
    auto n=local_time_now();
    // Only fresh samples count toward confirmation; invalid samples checked at 5 s cadence.
    static uint32_t checked=0;
    if(sample.fresh || uint32_t(n.ms-checked)>=5000) {
        checked=n.ms; temperature_alarms.sample(rtConfig,n,sample);
    }
    temperature_alarms.tick(n);
    temperature_alarm_save();
}
