#pragma once
// Portable policy: no Arduino, network, wall clock or Flash dependencies.
#include <algorithm>
#include <cmath>
#include <cstdint>

namespace aqua {
struct Config {
    float temp_alarm_high=32, temp_alarm_low=18;
    bool low_alarm_enabled=true, accumulation=false, skip_cycle=false;
    int start_hour=7, end_hour=21;
    float feed_min_temp=10, feed_max_temp=31.5f;
    float rate1=1.5f, rate2=2.25f, rate3=4.6f, rate4=5;
    float score_threshold=100, score_cap=120;
    float change_threshold=1.8f;
    int change_minutes=30;
    bool valid() const {
        return temp_alarm_low < temp_alarm_high && start_hour>=0 && end_hour<=24 &&
            start_hour<end_hour && feed_min_temp<12.5f && feed_max_temp>20 &&
            feed_max_temp<=temp_alarm_high && score_threshold>0 && score_cap>=score_threshold &&
            rate1>=0 && rate2>=0 && rate3>=0 && rate4>=0 && change_minutes>=5 && change_minutes<=60 && change_threshold>0;
    }
    float rate(float t) const {
        if (!feedAllowed(t)) return 0;
        return t<12.5f ? rate1 : t<15 ? rate2 : t<20 ? rate3 : rate4;
    }
    bool feedAllowed(float t) const {
        return t>=feed_min_temp && t<feed_max_temp &&
            (!low_alarm_enabled || t>=temp_alarm_low) && t<temp_alarm_high;
    }
};
struct Time {
    uint32_t ms=0;
    int64_t utc=0;
    int date=0, tomorrow=0, hour=0; // complete YYYYMMDD, 0 means unsynchronised
};
struct Sample {
    enum Pause { Running, Cold, Hot, Fault };
    float value=0;
    bool valid=false, fresh=false;
    uint32_t age=0;
    Pause pause=Running;
};
constexpr uint32_t MAX_SAMPLE_GAP=15000, SILENCE_MS=6*60*60*1000UL;
class ProbeQuality {
    bool hasSample=false;
    float value=0;
    uint32_t success=0;
    unsigned failures=0;
public:
    Sample snapshot(uint32_t ms) const {
        Sample s; s.value=value; s.age=hasSample ? uint32_t(ms-success) : UINT32_MAX;
        s.valid=hasSample && failures<3 && s.age<=MAX_SAMPLE_GAP; return s;
    }
    Sample converted(float t,uint32_t ms) {
        bool ok=std::isfinite(t) && t>=-55 && t<=125 && t!=85 && t!=-127;
        if(ok) { hasSample=true; value=t; success=ms; failures=0; }
        else if(failures<3) ++failures;
        auto s=snapshot(ms); s.fresh=ok; return s;
    }
};
enum AlarmKind { Probe, High, Low, Change, AlarmCount, None=AlarmCount };
struct AlarmEvent {
    bool active=false, acknowledged=false;
    uint32_t id=0, started=0, silent_at=0;
    int64_t triggered_utc=0, silent_until=0;
    bool silenced=false;
    unsigned bad=0, good=0;
};
class Alarms {
    struct Point { uint32_t ms; float t; };
    Point history[128]{};
    unsigned head=0, count=0;
    uint32_t lastFresh=0, lastStored=0, invalidSince=0;
    bool hadFresh=false, invalid=false;
    void condition(AlarmKind k, bool bad, bool recovered, const Time& n) {
        auto& e=events[k];
        if (!e.active) {
            e.bad=bad ? e.bad+1 : 0;
            if (e.bad>=3) {
                auto id=e.id+1; e=AlarmEvent{}; e.active=true; e.id=id;
                e.started=n.ms; e.triggered_utc=n.utc; dirty=true;
            }
        } else {
            e.good=recovered ? e.good+1 : 0;
            if (e.good>=3) { e.active=false; e.good=0; e.bad=0; dirty=true; }
        }
    }
    float median(unsigned start) const {
        float v[3]; for(unsigned i=0;i<3;i++) v[i]=history[(start+i)%128].t;
        std::sort(v,v+3); return v[1];
    }
public:
    AlarmEvent events[AlarmCount];
    bool dirty=false;
    int direction=0;
    void silence(AlarmKind k, const Time& n, bool ack=true) {
        if(k==None) return;
        auto& e=events[k]; e.acknowledged=ack; e.silenced=true;
        e.silent_at=n.ms; e.silent_until=n.utc ? n.utc+21600 : 0; dirty=true;
    }
    bool audible(AlarmKind k,const Time& n) const {
        const auto& e=events[k];
        if(!e.active) return false;
        if(!e.silenced) return true;
        // Recovered NVS silence without a trusted clock must never reflash on boot.
        if(!n.utc) return false;
        return e.silent_until && n.utc>=e.silent_until;
    }
    AlarmKind showing(const Time& n) const {
        for(int i=0;i<AlarmCount;i++) if(audible(AlarmKind(i),n)) return AlarmKind(i);
        return None;
    }
    void tick(const Time& n) {
        for(int i=0;i<AlarmCount;i++) {
            auto& e=events[i];
            if(e.active && e.silenced && !e.silent_until && n.utc) {
                e.silent_until=n.utc+21600; dirty=true;
            }
            if(e.active && audible(AlarmKind(i),n)) {
                if(e.silenced) {
                    e.silenced=false; e.acknowledged=false; e.started=n.ms; dirty=true;
                } else if(uint32_t(n.ms-e.started)>=900000) silence(AlarmKind(i),n,false);
            }
        }
    }
    void sample(const Config& c,const Time& n,const Sample& s) {
        bool usable=s.valid && s.fresh;
        if(!usable) {
            if(!invalid) { invalid=true; invalidSince=n.ms; }
            if(!s.valid || (hadFresh && uint32_t(n.ms-lastFresh)>MAX_SAMPLE_GAP)) count=0;
            condition(Probe,uint32_t(n.ms-invalidSince)>=15000,false,n);
            return;
        }
        invalid=false;
        condition(Probe,false,true,n);
        if(hadFresh && uint32_t(n.ms-lastFresh)>MAX_SAMPLE_GAP) count=0;
        hadFresh=true; lastFresh=n.ms;
        condition(High,s.value>=c.temp_alarm_high,s.value<=c.temp_alarm_high-0.5f,n);
        condition(Low,c.low_alarm_enabled && s.value<c.temp_alarm_low,
                  !c.low_alarm_enabled || s.value>=c.temp_alarm_low+0.5f,n);
        if(!count || uint32_t(n.ms-lastStored)>=30000) {
            history[head]={n.ms,s.value}; head=(head+1)%128; count=std::min(count+1,128u); lastStored=n.ms;
        }
        const uint32_t window=c.change_minutes*60000UL;
        bool covered=false; float delta=0;
        if(count>=6) {
            unsigned oldest=(head+128-count)%128;
            // Choose window endpoints, each a 3-point (one minute) median.
            for(unsigned i=0;i+5<count;i++) {
                unsigned p=(oldest+i)%128;
                auto age=uint32_t(n.ms-history[p].ms);
                if(age>=window && age<=window+30000) {
                    delta=median((head+125)%128)-median(p); covered=true;
                }
            }
        }
        if(covered) {
            auto previousId=events[Change].id;
            condition(Change,std::fabs(delta)>=c.change_threshold,
                      std::fabs(delta)<=c.change_threshold*0.7f,n);
            if(events[Change].id!=previousId) direction=delta>=0 ? 1 : -1;
        }
    }
};
enum class Action : int { Waiting, Fed, Skipped };
struct FeedRecord {
    float score=0;
    int evaluated=0, action_date=0, next_date=0;
    int64_t fed_utc=0;
    Action action=Action::Waiting;
    bool due=false;
};
class Feeding {
    uint32_t lastSample=0, undoAt=0;
    bool haveSample=false, previousAllowed=false, undoAvailable=false;
    float previousRate=0;
    FeedRecord before;
public:
    FeedRecord state;
    bool dirty=false;
    bool allowed(const Config& c,const Sample& s) const {
        return s.valid && s.pause==Sample::Running && s.age<=MAX_SAMPLE_GAP && c.feedAllowed(s.value);
    }
    void sample(const Config& c,const Time& n,const Sample& s) {
        if(!s.fresh) { if(!s.valid) haveSample=false; return; }
        bool ok=allowed(c,s);
        uint32_t elapsed=n.ms-lastSample;
        if(haveSample && elapsed<=MAX_SAMPLE_GAP && ok && previousAllowed) {
            float gain=previousRate*elapsed/3600000.f;
            state.score=std::min(c.score_cap,state.score+gain);
            if(undoAvailable) before.score=std::min(c.score_cap,before.score+gain);
        }
        haveSample=true; lastSample=n.ms; previousRate=c.rate(s.value); previousAllowed=ok;
    }
    void tick(const Config& c,const Time& n,const Sample& s) {
        if(!n.date) return;
        if(state.due && n.date>state.evaluated) { state.due=false; dirty=true; }
        if(n.hour>=c.end_hour && state.due) { skip(c,n,false); return; }
        if(n.hour<c.start_hour || n.hour>=c.end_hour || !allowed(c,s)) return;
        if(n.date<=state.evaluated || n.date<state.next_date || n.date<=state.action_date) return;
        state.evaluated=n.date;
        state.due=!c.accumulation || state.score>=c.score_threshold;
        dirty=true;
    }
    bool prompting(const Config& c,const Time& n,const Sample& s) const {
        return n.date && n.date==state.evaluated && n.date>=state.next_date && n.date>state.action_date &&
            n.hour>=c.start_hour && n.hour<c.end_hour && state.due && allowed(c,s);
    }
    bool canUndo(uint32_t ms) const { return undoAvailable && uint32_t(ms-undoAt)<=10000; }
    void feed(const Time& n) {
        before=state; undoAt=n.ms; undoAvailable=true;
        state.score=0; state.fed_utc=n.utc; state.action=Action::Fed;
        state.action_date=n.date; state.next_date=n.tomorrow; state.due=false; dirty=true;
    }
    void skip(const Config& c,const Time& n,bool manual=true) {
        if(manual) { before=state; undoAt=n.ms; undoAvailable=true; }
        else undoAvailable=false;
        if(c.skip_cycle) state.score=0;
        state.action=Action::Skipped; state.action_date=n.date;
        state.next_date=n.tomorrow; state.due=false; dirty=true;
    }
    void undo(const Time& n) {
        if(canUndo(n.ms)) { state=before; undoAvailable=false; dirty=true; }
    }
    const char* status(const Config& c,const Time& n,const Sample& s) const {
        if(!s.valid || s.pause==Sample::Fault) return "probe_fault";
        if(s.pause==Sample::Cold || s.value<c.feed_min_temp || (c.low_alarm_enabled && s.value<c.temp_alarm_low)) return "cold_pause";
        if(s.pause==Sample::Hot || s.value>=c.feed_max_temp || s.value>=c.temp_alarm_high) return "hot_pause";
        if(!n.date) return "time_pending";
        if(state.action_date==n.date && state.action==Action::Fed) return "fed";
        if(state.action_date==n.date && state.action==Action::Skipped) return "skipped";
        return prompting(c,n,s) ? "due" : "waiting";
    }
};
// Debounced press/release recogniser. Alarm capture belongs to the whole gesture.
class Touch {
    bool raw=false, stable=false, alarmGesture=false;
    uint32_t changed=0, pressed=0;
public:
    enum Gesture { NoGesture, Short, Long, Acknowledge };
    Gesture update(bool high,uint32_t ms,bool alarmShowing) {
        if(high!=raw) { raw=high; changed=ms; }
        if(stable && alarmShowing) alarmGesture=true;
        if(raw==stable || uint32_t(ms-changed)<50) return NoGesture;
        stable=raw;
        if(stable) { pressed=ms; alarmGesture=alarmShowing; return NoGesture; }
        if(alarmGesture) return Acknowledge;
        return uint32_t(ms-pressed)>=1500 ? Long : Short;
    }
};
} // namespace aqua
