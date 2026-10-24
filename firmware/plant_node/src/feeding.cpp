#include "feeding.h"
#include "config.h"
#include "led.h"
#include "temperature_alarm.h"
#include <Preferences.h>
#include <ArduinoJson.h>
#include <time.h>
static aqua::Feeding policy;
static aqua::Touch touch;
static FeedingState view;
static uint32_t checkpoint=0;
static float saved_score=0;
static bool legacy_pending=false;
static void save_state() {
    auto& r=policy.state;
    StaticJsonDocument<512> d;
    d["version"]=2; d["score"]=r.score; d["evaluated"]=r.evaluated;
    d["action_date"]=r.action_date; d["next_date"]=r.next_date;
    d["fed_utc"]=r.fed_utc; d["action"]=int(r.action); d["due"]=r.due;
    d["legacy_pending"]=legacy_pending;
    String json; serializeJson(d,json);
    Preferences p; p.begin("feed_st",false); p.putString("v2",json); p.end();
    policy.dirty=false; checkpoint=millis(); saved_score=r.score;
}
void feeding_init() {
    pinMode(TOUCH_PIN,INPUT);
    Preferences p; p.begin("feed_st",true); String json=p.getString("v2",""); p.end();
    StaticJsonDocument<512> d;
    if(!deserializeJson(d,json) && d["version"]==2) {
        auto& r=policy.state;
        r.score=d["score"] | 0.f; r.evaluated=d["evaluated"] | 0;
        r.action_date=d["action_date"] | 0; r.next_date=d["next_date"] | 0;
        r.fed_utc=d["fed_utc"].as<int64_t>(); r.action=aqua::Action(d["action"] | 0);
        r.due=d["due"] | false; saved_score=r.score;
        legacy_pending=d["legacy_pending"] | false;
    } else {
        // A yearless legacy record cannot establish a real feeding timestamp.
        // Suppress one day's reminder conservatively, retaining the original keys.
        p.begin("feed_st",true);
        legacy_pending=p.getBool("is_fed",false) || p.getBool("is_skip",false);
        p.end();
        save_state();
    }
    temperature_alarm_init();
}
FeedingState feeding_get_state() { return view; }
void feeding_update(const aqua::Sample& s) {
    const auto n=local_time_now();
    if(legacy_pending && n.date) {
        policy.state.action=aqua::Action::Skipped; policy.state.action_date=n.date;
        policy.state.next_date=n.tomorrow; policy.state.evaluated=n.date; policy.state.due=false;
        policy.dirty=true; legacy_pending=false;
    }
    policy.sample(rtConfig,n,s);
    policy.tick(rtConfig,n,s);
    const auto alarm=temperature_alarms.showing(n);
    auto gesture=touch.update(digitalRead(TOUCH_PIN)==HIGH,n.ms,alarm!=aqua::None);
    if(gesture==aqua::Touch::Acknowledge) {
        temperature_alarms.silence(alarm,n);
    } else if(gesture==aqua::Touch::Short && policy.canUndo(n.ms)) {
        policy.undo(n);
    } else if(gesture==aqua::Touch::Long && policy.prompting(rtConfig,n,s)) {
        policy.skip(rtConfig,n);
    } else if(gesture==aqua::Touch::Short) {
        if(n.date && n.date>=policy.state.evaluated && n.date>policy.state.action_date && policy.allowed(rtConfig,s)) policy.feed(n);
        else led_trigger_temp_flash(s.value,s.valid);
    }
    if(policy.dirty || (uint32_t(n.ms-checkpoint)>=1800000 && policy.state.score!=saved_score)) save_state();
    temperature_alarm_save();
    view.status=policy.status(rtConfig,n,s); view.score=policy.state.score;
    view.next_date=policy.state.next_date; view.prompting=policy.prompting(rtConfig,n,s);
    view.is_fed=n.date && policy.state.action_date==n.date && policy.state.action==aqua::Action::Fed;
    view.fed_time="";
    if(policy.state.fed_utc) {
        time_t epoch=policy.state.fed_utc; tm t; localtime_r(&epoch,&t);
        char text[24]; strftime(text,sizeof(text),"%Y-%m-%d %H:%M",&t); view.fed_time=text;
    }
}
