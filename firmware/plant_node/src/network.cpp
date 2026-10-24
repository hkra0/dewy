#include "network.h"
#include "config.h"
#include <WiFi.h>
#include <ESPmDNS.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "maintenance.h"

#ifndef WIFI_SSID
#define WIFI_SSID "YOUR_WIFI_SSID"
#endif

#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
#endif

#ifndef MQTT_HOST
#define MQTT_HOST "robin"
#endif

#ifndef MQTT_CLIENT_ID
#define MQTT_CLIENT_ID "ESP32_Aqua_Node"
#endif

#ifndef MQTT_DATA_TOPIC
#define MQTT_DATA_TOPIC "sensor/esp32/aqua_data"
#endif

#ifndef MQTT_CONFIG_TOPIC
#define MQTT_CONFIG_TOPIC "device/aqua/config"
#endif

#include "temperature_alarm.h"
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>
class BudgetWiFiClient : public WiFiClient {
public:
    int connect(IPAddress ip,uint16_t port) override { return WiFiClient::connect(ip,port,250); }
};
static BudgetWiFiClient espClient;
static PubSubClient client(espClient);
struct Message { char text[2048]; };
static QueueHandle_t configIn, configOut, dataOut;
static bool enqueue(QueueHandle_t q,const String& text) {
    if(text.length()>=sizeof(Message::text)) { RemoteSerial.println("MQTT JSON too large"); return false; }
    Message m{}; text.toCharArray(m.text,sizeof(m.text)); return xQueueOverwrite(q,&m)==pdPASS;
}
void network_publish_config_state() { enqueue(configOut,config_to_json()); }
static void callback(char* topic,byte* payload,unsigned length) {
    if(String(topic)==String(MQTT_CONFIG_TOPIC)+"/maintenance/set") {
        maintenance_command(payload,length); return;
    }
    if(length>=sizeof(Message::text)) return;
    Message m{}; memcpy(m.text,payload,length); xQueueOverwrite(configIn,&m);
}
static bool publish(const char* topic,const char* json,bool retain=false) {
    // 4096 bytes includes MQTT header, topic and JSON, not just document capacity.
    if(strlen(topic)+strlen(json)+9>4096) return false;
    bool ok=client.publish(topic,json,retain);
    if(!ok) RemoteSerial.println("MQTT publish failed; snapshot retained for reconnect");
    return ok;
}
static void network_task(void*) {
    WiFi.mode(WIFI_STA); WiFi.begin(WIFI_SSID,WIFI_PASSWORD);
    client.setSocketTimeout(1);
    client.setCallback(callback); client.setBufferSize(4096);
    bool wasWifi=false; uint32_t retry=0, wifiRetry=millis(), backoff=1000;
    Message latest{}, cfg{}; bool dataPending=false, configPending=false;
    for(;;) {
        if(xQueueReceive(dataOut,&latest,0)==pdPASS) dataPending=true;
        if(xQueueReceive(configOut,&cfg,0)==pdPASS) configPending=true;
        uint32_t now=millis(); bool wifi=WiFi.status()==WL_CONNECTED;
        if(!wifi) {
            wasWifi=false;
            if(uint32_t(now-wifiRetry)>=30000) { WiFi.reconnect(); wifiRetry=now; }
        } else {
            if(!wasWifi) {
                MDNS.begin(MQTT_CLIENT_ID);
                configTzTime("CST-8","ntp.aliyun.com","pool.ntp.org"); wasWifi=true;
            }
            if(!client.connected() && uint32_t(now-retry)>=backoff) {
                retry=now; IPAddress ip;
                bool found=ip.fromString(MQTT_HOST);
                if(!found) { ip=MDNS.queryHost(MQTT_HOST,250); found=ip!=IPAddress(0,0,0,0); }
                if(found) {
                    client.setServer(ip,1883);
                    if(client.connect(MQTT_CLIENT_ID)) {
                        client.subscribe((String(MQTT_CONFIG_TOPIC)+"/set").c_str());
                        client.subscribe((String(MQTT_CONFIG_TOPIC)+"/maintenance/set").c_str(),1);
                        maintenance_connected();
                        Message request{}; xQueueOverwrite(configIn,&request);
                        dataPending=latest.text[0]; configPending=cfg.text[0]; backoff=1000;
                    } else backoff=std::min(backoff*2,30000u);
                } else backoff=std::min(backoff*2,30000u);
            }
            if(client.connected()) {
                client.loop();
                if(configPending && publish((String(MQTT_CONFIG_TOPIC)+"/state").c_str(),cfg.text,true)) configPending=false;
                if(dataPending && publish(MQTT_DATA_TOPIC,latest.text)) dataPending=false;
            }
        }
        maintenance_tick(client.connected());
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}
void network_init() {
    maintenance_set_transport([](const char* topic,const char* text,bool retain) {
        return client.publish(topic,text,retain);
    });
    configIn=xQueueCreate(1,sizeof(Message)); configOut=xQueueCreate(1,sizeof(Message)); dataOut=xQueueCreate(1,sizeof(Message));
    network_publish_config_state();
    // OTA command verification + chunk decoding + signed ACK have nested frames.
    xTaskCreate(network_task,"mqtt",16384,nullptr,1,nullptr);
}
void network_loop() {
    Message m{};
    if(xQueueReceive(configIn,&m,0)==pdPASS) {
        if(m.text[0]) config_apply(m.text);
        network_publish_config_state();
    }
}
bool network_publish_data(const SensorReadings& s,const FeedingState& f) {
    StaticJsonDocument<3072> doc;
    doc["data_version"]=2;
    if(s.temp_ok) doc["temperature"]=s.temperature; else doc["temperature"]=nullptr;
    if(s.hum_ok) doc["humidity"]=s.humidity; else doc["humidity"]=nullptr;
    if(s.press_ok) doc["pressure"]=s.pressure; else doc["pressure"]=nullptr;
    if(s.water_temp_ok) doc["water_temp"]=s.water_temp; else doc["water_temp"]=nullptr;
    doc["water_temp_valid"]=s.water_temp_ok; doc["water_temp_age"]=s.water_temp_age/1000;
    doc["fed"]=f.is_fed ? 1 : 0;
    if(f.fed_time.length()) doc["fed_time"]=f.fed_time; else doc["fed_time"]=nullptr;
    doc["feeding_state"]=f.status; doc["feeding_score"]=f.score;
    if(f.next_date) doc["next_prompt_date"]=f.next_date; else doc["next_prompt_date"]=nullptr;
    doc["time_valid"]=bool(local_time_now().date);
    auto alarms=doc.createNestedArray("alarms");
    const char* names[]={"probe","high","low","change"};
    for(int i=0;i<aqua::AlarmCount;i++) {
        const auto& e=temperature_alarms.events[i]; if(!e.active) continue;
        auto a=alarms.createNestedObject(); a["kind"]=names[i]; a["event_id"]=e.id;
        a["triggered_at"]=e.triggered_utc;
        a["acknowledged"]=e.acknowledged; a["silenced"]=e.silenced; a["silent_until"]=e.silent_until;
        if(i==aqua::Change) a["direction"]=temperature_alarms.direction;
    }
    if(doc.overflowed()) { RemoteSerial.println("MQTT document overflow"); return false; }
    String json; serializeJson(doc,json); return enqueue(dataOut,json);
}
