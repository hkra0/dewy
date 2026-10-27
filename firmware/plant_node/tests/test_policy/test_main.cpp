#include <unity.h>
#include "aqua_model.h"
#include "config_protocol.h"
using namespace aqua;
void setUp() {}
void tearDown() {}
static Time at(uint32_t sec) {
    Time n; n.ms=sec*1000; n.utc=1704067200+sec;
    unsigned days=(sec+7*3600)/86400;
    n.date=20260101+days; n.tomorrow=n.date+1; n.hour=((sec/3600)+7)%24; return n;
}
static Sample good(float t) { Sample s; s.value=t; s.valid=true; s.fresh=true; return s; }
static void advance(Feeding& f,const Config& c,float temp,unsigned seconds) {
    for(unsigned t=0;t<=seconds;t+=5) { auto n=at(t); auto s=good(temp); f.sample(c,n,s); f.tick(c,n,s); }
}
void cool_third_morning() {
    Config c; c.low_alarm_enabled=false; c.accumulation=true; Feeding f; f.feed(at(0));
    advance(f,c,13.5f,86400);
    TEST_ASSERT_FALSE(f.state.due); TEST_ASSERT_FLOAT_WITHIN(.1f,54,f.state.score);
    advance(f,c,13.5f,86400); // Restarting a sample stream must not fill an unknown gap.
    TEST_ASSERT_FALSE(f.state.due);
    Feeding next; next.feed(at(0)); advance(next,c,13.5f,172800);
    TEST_ASSERT_TRUE(next.state.due); TEST_ASSERT_EQUAL(20260103,next.state.evaluated);
}
void warm_next_morning() {
    Config c; c.low_alarm_enabled=false; c.accumulation=true; Feeding f; f.feed(at(0)); advance(f,c,18.6f,86400);
    TEST_ASSERT_TRUE(f.state.due);
    Feeding slow; slow.feed(at(0)); advance(slow,c,13.5f,120000);
    TEST_ASSERT_FALSE(slow.state.due); // No afternoon re-evaluation.
}
void skip_dates_and_auto_skip() {
    Config c; c.low_alarm_enabled=false; Feeding f; auto s=good(22); f.state.score=110;
    f.tick(c,at(0),s); f.skip(c,at(0));
    TEST_ASSERT_EQUAL(20260102,f.state.next_date); TEST_ASSERT_FLOAT_WITHIN(.01,110,f.state.score);
    auto tomorrow=at(86400); f.tick(c,tomorrow,s); TEST_ASSERT_TRUE(f.state.due);
    f.tick(c,at(86400+14*3600),s);
    TEST_ASSERT_EQUAL(20260103,f.state.next_date); TEST_ASSERT_FALSE(f.state.due);
    f.tick(c,at(172800),good(8)); TEST_ASSERT_FALSE(f.state.due);
    f.tick(c,at(172805),good(22)); TEST_ASSERT_TRUE(f.state.due);
}
void undo_restores_progress_and_record() {
    Config c; c.low_alarm_enabled=false; Feeding f; f.state.score=105; f.state.fed_utc=123;
    f.sample(c,at(0),good(22)); f.feed(at(0)); f.sample(c,at(5),good(22)); f.undo(at(6));
    TEST_ASSERT_FLOAT_WITHIN(.001,105+5.f*5/3600,f.state.score);
    TEST_ASSERT_EQUAL_INT64(123,f.state.fed_utc);
    f.skip(c,at(10)); f.undo(at(15)); TEST_ASSERT_EQUAL(Action::Waiting,f.state.action);
    f.feed(at(20)); f.undo(at(31)); TEST_ASSERT_EQUAL(Action::Fed,f.state.action);
}
void invalid_cache_gap_and_boundaries() {
    Config c; c.low_alarm_enabled=false; Feeding f; auto s=good(22); f.sample(c,at(0),s);
    s.fresh=false; f.sample(c,at(5),s); TEST_ASSERT_EQUAL_FLOAT(0,f.state.score);
    f.sample(c,at(100),good(22)); TEST_ASSERT_EQUAL_FLOAT(0,f.state.score);
    f.sample(c,at(105),good(31.5f)); TEST_ASSERT_EQUAL_FLOAT(0,f.state.score);
    f.sample(c,at(110),good(8)); TEST_ASSERT_EQUAL_FLOAT(0,f.state.score);
    TEST_ASSERT_EQUAL_FLOAT(0,c.rate(31.5f)); TEST_ASSERT_EQUAL_FLOAT(1.5,c.rate(10));
    TEST_ASSERT_EQUAL_FLOAT(2.25,c.rate(12.5)); TEST_ASSERT_EQUAL_FLOAT(4.6,c.rate(15)); TEST_ASSERT_EQUAL_FLOAT(5,c.rate(20));
    Sample bad; f.tick(c,at(0),bad); TEST_ASSERT_FALSE(f.state.due);
}
void alarm_hysteresis_silence_priority() {
    Config c; c.low_alarm_enabled=false; Alarms a; auto s=good(33);
    for(unsigned t=0;t<=10;t+=5) a.sample(c,at(t),s);
    TEST_ASSERT_EQUAL(High,a.showing(at(10))); auto id=a.events[High].id;
    a.silence(High,at(11)); TEST_ASSERT_TRUE(a.events[High].active);
    TEST_ASSERT_EQUAL(None,a.showing(at(12)));
    a.tick(at(21611)); TEST_ASSERT_EQUAL(High,a.showing(at(21611)));
    a.tick(at(22511)); TEST_ASSERT_EQUAL(None,a.showing(at(22511)));
    for(unsigned t=22520;t<=22530;t+=5) a.sample(c,at(t),good(31.8));
    TEST_ASSERT_EQUAL(id,a.events[High].id); TEST_ASSERT_TRUE(a.events[High].active);
    for(unsigned t=22535;t<=22545;t+=5) a.sample(c,at(t),good(31));
    TEST_ASSERT_FALSE(a.events[High].active);
    for(unsigned t=22550;t<=22560;t+=5) a.sample(c,at(t),s);
    TEST_ASSERT_EQUAL(id+1,a.events[High].id);
    Sample bad;
    for(unsigned t=22565;t<=22600;t+=5) a.sample(c,at(t),bad);
    TEST_ASSERT_EQUAL(Probe,a.showing(at(22600)));
    for(unsigned t=22605;t<=22615;t+=5) a.sample(c,at(t),s);
    TEST_ASSERT_FALSE(a.events[Probe].active);
}
void temperature_window_and_gap() {
    Config c; c.low_alarm_enabled=false; c.low_alarm_enabled=false; Alarms stable,rise,gap;
    for(unsigned t=0;t<=1840;t+=5) {
        stable.sample(c,at(t),good(20));
        rise.sample(c,at(t),good(20+t*2.5f/1800));
        if(t<900 || t>1000) gap.sample(c,at(t),good(20+t*2.5f/1800));
        if(t<1800) TEST_ASSERT_FALSE(rise.events[Change].active);
    }
    TEST_ASSERT_FALSE(stable.events[Change].active);
    TEST_ASSERT_TRUE(rise.events[Change].active); TEST_ASSERT_EQUAL(1,rise.direction);
    TEST_ASSERT_FALSE(gap.events[Change].active);
}
void release_only_gestures_and_rollover() {
    Touch t; uint32_t start=0xfffffff0u;
    TEST_ASSERT_EQUAL(Touch::NoGesture,t.update(true,start,true));
    TEST_ASSERT_EQUAL(Touch::NoGesture,t.update(true,start+60,true));
    TEST_ASSERT_EQUAL(Touch::NoGesture,t.update(false,start+2000,false));
    TEST_ASSERT_EQUAL(Touch::Acknowledge,t.update(false,start+2060,false));
    t.update(true,3000,false); t.update(true,3060,false); t.update(false,5000,false);
    TEST_ASSERT_EQUAL(Touch::Long,t.update(false,5060,false));
    t.update(true,6000,false); t.update(true,6060,false); t.update(false,6200,false);
    TEST_ASSERT_EQUAL(Touch::Short,t.update(false,6260,false));
}
void restart_year_and_clock_correction() {
    Config c; c.low_alarm_enabled=false; Feeding f; Time n=at(0); n.date=20261231; n.tomorrow=20270101;
    f.tick(c,n,good(20)); f.skip(c,n);
    Feeding restored; restored.state=f.state;
    restored.tick(c,n,good(20)); TEST_ASSERT_FALSE(restored.state.due);
    Time unsynced; restored.tick(c,unsynced,good(20)); TEST_ASSERT_FALSE(restored.state.due);
    n.date=20270101; n.tomorrow=20270102; restored.tick(c,n,good(20)); TEST_ASSERT_TRUE(restored.state.due);
    n.date=20261230; restored.tick(c,n,good(20));
    TEST_ASSERT_EQUAL(20270101,restored.state.evaluated);
    Alarms a; a.events[High].active=true; a.events[High].silenced=true;
    TEST_ASSERT_EQUAL(None,a.showing(unsynced)); a.tick(at(1));
    TEST_ASSERT_GREATER_THAN_INT64(at(1).utc,a.events[High].silent_until);
}
void probe_quality_cache_and_first_sample() {
    ProbeQuality p;
    TEST_ASSERT_FALSE(p.snapshot(0).valid);
    TEST_ASSERT_FALSE(p.snapshot(749).valid);
    TEST_ASSERT_FALSE(p.converted(85,750).valid);
    auto s=p.converted(22,5750); TEST_ASSERT_TRUE(s.valid); TEST_ASSERT_TRUE(s.fresh);
    s=p.converted(-127,10750); TEST_ASSERT_TRUE(s.valid); TEST_ASSERT_FALSE(s.fresh);
    TEST_ASSERT_FALSE(p.snapshot(20751).valid);
    p.converted(-127,15750); TEST_ASSERT_FALSE(p.converted(-127,20750).valid);
    TEST_ASSERT_TRUE(p.converted(23,25750).valid);
    ProbeQuality wrap; wrap.converted(20,0xfffffff0u);
    TEST_ASSERT_TRUE(wrap.snapshot(2000).valid);
    TEST_ASSERT_FALSE(wrap.snapshot(20000).valid);
}
void config_constraints() {
    Config c; c.low_alarm_enabled=false; TEST_ASSERT_TRUE(c.valid()); c.start_hour=c.end_hour; TEST_ASSERT_FALSE(c.valid());
    c=Config{}; c.feed_max_temp=40; TEST_ASSERT_FALSE(c.valid());
    c=Config{}; c.score_cap=99; TEST_ASSERT_FALSE(c.valid());
}
void legacy_migration_is_always_valid() {
    // 实测场景：旧版报警上限 30，新字段 feed_max_temp 默认 31.5，曾导致整包拒收
    Config c=legacy_config(30,10,7);
    TEST_ASSERT_TRUE(c.valid()); TEST_ASSERT_EQUAL_FLOAT(30,c.feed_max_temp);
    TEST_ASSERT_EQUAL_FLOAT(30,c.temp_alarm_high); TEST_ASSERT_EQUAL_FLOAT(10,c.temp_alarm_low); TEST_ASSERT_EQUAL(7,c.start_hour);
    // 迁移后，只带旧三项的推送也能通过
    Config out; std::string error;
    TEST_ASSERT_TRUE(parse_config("{\"temp_alarm_high\":30,\"temp_alarm_low\":10,\"feed_start_hour\":7}",c,out,error));
    // 默认上限不受影响
    TEST_ASSERT_EQUAL_FLOAT(31.5f,legacy_config(32,18,7).feed_max_temp);
    // 旧值本身无法组成合法配置：退回默认报警阈值，保留整点
    c=legacy_config(15,10,8); TEST_ASSERT_TRUE(c.valid()); TEST_ASSERT_EQUAL(8,c.start_hour);
    TEST_ASSERT_EQUAL_FLOAT(32,c.temp_alarm_high);
    c=legacy_config(30,35,7); TEST_ASSERT_TRUE(c.valid());
    c=legacy_config(30,10,40); TEST_ASSERT_TRUE(c.valid()); TEST_ASSERT_EQUAL(7,c.start_hour);
}
void config_protocol_is_atomic_and_replay_stable() {
    Config old, out=old; std::string error;
    TEST_ASSERT_FALSE(parse_config("{\"temp_alarm_high\":35,\"feed_start_hour\":22}",old,out,error));
    TEST_ASSERT_EQUAL_FLOAT(old.temp_alarm_high,out.temp_alarm_high);
    TEST_ASSERT_FALSE(parse_config("{\"low_alarm_enabled\":1}",old,out,error));
    TEST_ASSERT_FALSE(parse_config("{\"feeding_mode\":\"unknown\"}",old,out,error));
    TEST_ASSERT_FALSE(parse_config("{\"feed_start_hour\":7.5}",old,out,error));
    TEST_ASSERT_FALSE(parse_config("[]",old,out,error));
    TEST_ASSERT_FALSE(parse_config(std::string(2048,' '),old,out,error));
    TEST_ASSERT_TRUE(parse_config("{\"feed_reset_hour\":9}",old,out,error));
    TEST_ASSERT_EQUAL(9,out.start_hour);
    auto replay=config_values(out); Config restored;
    TEST_ASSERT_TRUE(parse_config(replay,out,restored,error));
    TEST_ASSERT_TRUE(replay==config_values(restored));
    TEST_ASSERT_LESS_THAN(2048,replay.size());
    TEST_ASSERT_TRUE(parse_config("{\"feeding_mode\":\"temperature_accumulation\",\"low_alarm_enabled\":false}",old,out,error));
    TEST_ASSERT_TRUE(out.accumulation); TEST_ASSERT_FALSE(out.low_alarm_enabled);
}
void active_alarm_pause_and_low_alarm() {
    Config c; Feeding f; auto n=at(0); auto s=good(20); s.pause=Sample::Hot;
    f.tick(c,n,s); TEST_ASSERT_FALSE(f.state.due);
    f.sample(c,n,s); n=at(5); f.sample(c,n,s); TEST_ASSERT_EQUAL_FLOAT(0,f.state.score);
    TEST_ASSERT_EQUAL_STRING("hot_pause",f.status(c,n,s));
    s.pause=Sample::Fault; TEST_ASSERT_EQUAL_STRING("probe_fault",f.status(c,n,s));
    Alarms alarms;
    for(unsigned t=0;t<=10;t+=5) alarms.sample(c,at(t),good(17));
    TEST_ASSERT_EQUAL(Low,alarms.showing(at(10)));
    TEST_ASSERT_FALSE(f.allowed(c,good(17)));
    c.low_alarm_enabled=false; TEST_ASSERT_TRUE(f.allowed(c,good(17)));
}
#include "boot_health.h"
void ota_trial_requires_stability_and_live_main_loop() {
    maintenance::BootHealth health;
    health.loops=500; health.lastLoop=29999;
    TEST_ASSERT_FALSE(health.ready(29999));
    health.lastLoop=30000;
    TEST_ASSERT_TRUE(health.ready(30000));
    TEST_ASSERT_FALSE(health.ready(32000));
    health.loops=99; health.lastLoop=32000;
    TEST_ASSERT_FALSE(health.ready(32000));
    health.loops=0;
    TEST_ASSERT_EQUAL_STRING("",health.failure(119999));
    TEST_ASSERT_EQUAL_STRING("setup_incomplete",health.failure(120000));
    health.loops=200;
    TEST_ASSERT_EQUAL_STRING("main_loop_stalled",health.failure(120000));
    health.lastLoop=119999;
    TEST_ASSERT_EQUAL_STRING("confirmation_timeout",health.failure(120000));
    health.started=0xfffffff0u; health.lastLoop=30000-16;
    TEST_ASSERT_TRUE(health.ready(30000-16));
}
int main() {
    UNITY_BEGIN();
    RUN_TEST(cool_third_morning); RUN_TEST(warm_next_morning); RUN_TEST(skip_dates_and_auto_skip);
    RUN_TEST(undo_restores_progress_and_record); RUN_TEST(invalid_cache_gap_and_boundaries);
    RUN_TEST(alarm_hysteresis_silence_priority); RUN_TEST(temperature_window_and_gap);
    RUN_TEST(release_only_gestures_and_rollover); RUN_TEST(restart_year_and_clock_correction); RUN_TEST(config_constraints); RUN_TEST(legacy_migration_is_always_valid); RUN_TEST(probe_quality_cache_and_first_sample);
    RUN_TEST(config_protocol_is_atomic_and_replay_stable); RUN_TEST(active_alarm_pause_and_low_alarm);
    RUN_TEST(ota_trial_requires_stability_and_live_main_loop);
    return UNITY_END();
}
