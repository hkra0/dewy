#include <Arduino.h>
#include "config.h"
#include "sensors.h"
#include "led.h"
#include "feeding.h"
#include "network.h"
#include "temperature_alarm.h"
#include "maintenance.h"
static uint32_t lastRead=0, lastSend=0;
static SensorReadings readings{};
static String lastStatus;
void setup() {
    Serial.begin(115200);
    maintenance_init();
    config_init(); led_init(); feeding_init(); sensors_init(); network_init();
}
void loop() {
    // Network I/O runs on its own task. Hardware interaction never waits for a broker.
    network_loop();
    const uint32_t now=millis();
    auto water=sensors_water();
    if(uint32_t(now-lastRead)>=SENSOR_INTERVAL_MS) { readings=sensors_read(); lastRead=now; }
    readings.water_temp=water.value; readings.water_temp_ok=water.valid; readings.water_temp_age=water.age;
    temperature_alarm_update(water);
    auto policySample=water;
    if(temperature_alarms.events[aqua::Probe].active) policySample.pause=aqua::Sample::Fault;
    else if(temperature_alarms.events[aqua::High].active) policySample.pause=aqua::Sample::Hot;
    else if(temperature_alarms.events[aqua::Low].active) policySample.pause=aqua::Sample::Cold;
    feeding_update(policySample);
    auto f=feeding_get_state();
    led_update(!f.prompting,water.value,water.valid);
    String status=String(f.status)+"|"+f.fed_time+"|"+String(f.next_date);
    for(int i=0;i<aqua::AlarmCount;i++) {
        auto& e=temperature_alarms.events[i];
        status+=String(e.active)+String(e.acknowledged)+String(e.silenced)+String(e.id);
    }
    if(status!=lastStatus || uint32_t(now-lastSend)>=SENSOR_INTERVAL_MS) {
        // Copies data into a queue; the network task publishes the newest snapshot.
        network_publish_data(readings,f); lastSend=now; lastStatus=status;
    }
    maintenance_loop_heartbeat();
    delay(10);
}
