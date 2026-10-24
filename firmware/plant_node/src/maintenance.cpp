#include "maintenance.h"
#include <ArduinoJson.h>
#include <Update.h>
#include <esp_ota_ops.h>
#include <mbedtls/md.h>
#include <mbedtls/base64.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <esp_timer.h>
#include <Preferences.h>
#include "boot_health.h"
#include <atomic>

#if !CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE || !CONFIG_APP_ROLLBACK_ENABLE
#error "Dewy OTA requires a rollback-enabled SDK and bootloader; do not fake these sdkconfig flags"
#endif

#ifndef DEWY_NODE_ID
#define DEWY_NODE_ID "unknown"
#endif
#ifndef DEWY_BOARD
#define DEWY_BOARD "unknown"
#endif
#ifndef DEWY_BUILD_ID
#define DEWY_BUILD_ID "00000000000000000000000000000000"
#endif
#ifndef DEWY_MAINTENANCE_KEY
#define DEWY_MAINTENANCE_KEY ""
#endif
#ifndef MQTT_CONFIG_TOPIC
#define MQTT_CONFIG_TOPIC "device/aqua/config"
#endif

// Both markers must remain in the binary for the Pi's preflight target check.
static const char targetMarker[] = "DEWY_TARGET:" DEWY_NODE_ID ":" DEWY_BOARD;
static const char buildMarker[] = "DEWY_BUILD:" DEWY_BUILD_ID;
static const char otaMarker[] = "DEWY_OTA:2";
static const char key[] = DEWY_MAINTENANCE_KEY;
static char boot[33];
static String session, error, ack;
static size_t offset=0, total=0;
static bool updating=false, committed=false;
static uint32_t lastCommand=0, lastReport=0, rebootAt=0;
static MaintenancePublish transport=nullptr;
static esp_timer_handle_t trialTimer=nullptr;
static bool trial=false, bootConfirmed=false;
static std::atomic<uint32_t> lastLoop{0}, loopCount{0};
static String trialState="unavailable", trialFailure;
static String resultSession, resultBuild, resultStatus, resultCode;
static String resultSlot;
static Preferences otaPrefs;
static bool prefsReady=false;

// C linkage overrides Arduino's weak default. This runs BEFORE setup(), including
// before sensor/NVS initialization, so a hung setup cannot escape the deadline.
extern "C" bool verifyRollbackLater() {
    esp_ota_img_states_t state;
    const auto running=esp_ota_get_running_partition();
    if(running && esp_ota_get_state_partition(running,&state)==ESP_OK && state==ESP_OTA_IMG_PENDING_VERIFY) {
        trial=true;
        esp_timer_create_args_t args{};
        args.callback=[](void*) { esp_restart(); }; // Keep pending: bootloader rolls back on reset.
        args.name="ota-trial";
        if(esp_timer_create(&args,&trialTimer)!=ESP_OK ||
           esp_timer_start_once(trialTimer,uint64_t(maintenance::BootHealth::DeadlineMs)*1000)!=ESP_OK) {
            esp_restart(); // Fail closed rather than silently disable the trial deadline.
        }
    }
    return true;
}

void maintenance_loop_heartbeat() {
    lastLoop.store(millis());
    loopCount.fetch_add(1);
}
static maintenance::BootHealth healthSnapshot() {
    maintenance::BootHealth health;
    health.lastLoop=lastLoop.load(); health.loops=loopCount.load();
    return health;
}
static bool healthReady() { return healthSnapshot().ready(millis()); }
static bool saveResult(const String& id,const String& build,const char* status,const char* code) {
    resultSession=id; resultBuild=build; resultStatus=status; resultCode=code;
    if(!prefsReady) return false;
    // One NVS blob prevents a power loss from mixing fields from two updates.
    StaticJsonDocument<512> doc;
    doc["session"]=id; doc["build"]=build; doc["status"]=status; doc["code"]=code;
    doc["slot"]=resultSlot;
    String json; serializeJson(doc,json);
    return otaPrefs.putString("transaction",json)==json.length();
}
struct LogLine { char text[193]; };
static QueueHandle_t logs=nullptr;
static portMUX_TYPE logLock=portMUX_INITIALIZER_UNLOCKED;
static char line[193];
static size_t used=0;
static uint32_t dropped=0;
MaintenanceSerial RemoteSerial;

size_t MaintenanceSerial::write(uint8_t value) {
    Serial.write(value);
    portENTER_CRITICAL(&logLock);
    if(value!='\r') {
        if(value!='\n') line[used++]=char(value);
        if(value=='\n' || used==sizeof(line)-1) {
            line[used]=0;
            if(logs && used) {
                LogLine item{}; memcpy(item.text,line,used+1);
                if(xQueueSend(logs,&item,0)!=pdPASS) ++dropped;
            }
            used=0;
        }
    }
    portEXIT_CRITICAL(&logLock);
    return 1;
}
static String signature(const String& body) {
    unsigned char digest[32]; char hex[65];
    mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256),
                   reinterpret_cast<const unsigned char*>(key),strlen(key),
                   reinterpret_cast<const unsigned char*>(body.c_str()),body.length(),digest);
    for(int i=0;i<32;i++) snprintf(hex+2*i,3,"%02x",digest[i]);
    return String(hex);
}
static void report(const char* log=nullptr) {
    if(!transport || strlen(key)<32) return;
    StaticJsonDocument<1536> doc;
    doc["boot"]=boot; doc["board"]=DEWY_BOARD;
    doc["target"]=DEWY_NODE_ID; doc["image_target"]=targetMarker; doc["build"]=buildMarker+11;
    doc["uptime"]=millis()/1000; doc["free_heap"]=ESP.getFreeHeap();
    auto partition=esp_ota_get_next_update_partition(nullptr);
    auto running=esp_ota_get_running_partition();
    const bool hasBackup=partition && running && partition->address!=running->address && esp_ota_get_app_partition_count()>=2;
    doc["ota_max"]=hasBackup ? partition->size : 0;
    doc["session"]=session; doc["offset"]=offset; doc["ack"]=ack;
    doc["error"]=error; doc["dropped_logs"]=dropped;
    doc["rollback"]=prefsReady && hasBackup;
    doc["ota_protocol"]=otaMarker;
    doc["boot_state"]=trialState; doc["health_ready"]=trial && healthReady();
    auto result=doc.createNestedObject("update_result");
    result["session"]=resultSession; result["build"]=resultBuild;
    result["status"]=resultStatus; result["code"]=resultCode;
    if(log) doc["log"]=log;
    String body; serializeJson(doc,body);
    StaticJsonDocument<2048> envelope;
    envelope["body"]=body; envelope["mac"]=signature(body);
    String json; serializeJson(envelope,json);
    transport(MQTT_CONFIG_TOPIC "/maintenance/state",json.c_str(),false);
    lastReport=millis();
}
void maintenance_init() {
    for(int i=0;i<4;i++) snprintf(boot+8*i,9,"%08x",esp_random());
    logs=xQueueCreate(24,sizeof(LogLine));
    prefsReady=otaPrefs.begin("dewy_ota",false);
    if(prefsReady) {
        StaticJsonDocument<512> doc;
        if(!deserializeJson(doc,otaPrefs.getString("transaction","{}"))) {
            resultSession=doc["session"] | ""; resultBuild=doc["build"] | "";
            resultStatus=doc["status"] | ""; resultCode=doc["code"] | "";
            resultSlot=doc["slot"] | "";
        }
        if(resultStatus=="pending" && !trial) {
            esp_ota_img_states_t state;
            auto running=esp_ota_get_running_partition();
            if(running && resultSlot==running->label && resultBuild==DEWY_BUILD_ID &&
               esp_ota_get_state_partition(running,&state)==ESP_OK && state==ESP_OTA_IMG_VALID) {
                // Recover a power loss between marking VALID and journaling success.
                saveResult(resultSession,resultBuild,"succeeded","");
            } else {
                // Old slot recovered after a boot crash, trial timeout or commit interruption.
                saveResult(resultSession,resultBuild,"rolled_back",
                           resultCode.isEmpty() ? "boot_failed_or_interrupted" : resultCode.c_str());
            }
        }
    }
    bootConfirmed=!trial;
    trialState=trial ? "pending_verify" : "valid";
    if(trial && !prefsReady) { trialFailure="nvs_unavailable"; esp_restart(); }
    RemoteSerial.printf("Maintenance boot %s target %s build %s\n",boot,targetMarker,buildMarker);
}
void maintenance_set_transport(MaintenancePublish publish) { transport=publish; }
void maintenance_connected() { report(); }
void maintenance_command(const byte* payload,unsigned length) {
    if(strlen(key)<32 || length>2047) return;
    StaticJsonDocument<3072> envelope;
    if(deserializeJson(envelope,payload,length)) return;
    String body=envelope["body"] | "", mac=envelope["mac"] | "";
    String expected=signature(body);
    if(mac.length()!=64) return;
    unsigned diff=0; for(unsigned i=0;i<64;i++) diff|=mac[i]^expected[i];
    if(diff) return;
    StaticJsonDocument<2048> doc;
    if(deserializeJson(doc,body) || String(doc["boot"] | "")!=boot) return;
    String incoming=doc["session"] | "", op=doc["op"] | "";
    if(incoming.length()!=32) return;
    if(op=="confirm") {
        if(incoming!=resultSession || String(doc["build"] | "")!=DEWY_BUILD_ID) return;
        if(trial && healthReady()) {
            esp_err_t err=esp_ota_mark_app_valid_cancel_rollback();
            if(err==ESP_OK) {
                trial=false; bootConfirmed=true; trialState="valid";
                error="";
                if(trialTimer) esp_timer_stop(trialTimer);
                saveResult(resultSession,resultBuild,"succeeded","");
            } else { error="Failed to mark firmware valid"; }
        }
        report(); return;
    }
    if(op=="begin") {
        if(incoming==session) { report(); return; }
        if(updating || committed) return;
        session=incoming; offset=0; total=doc["size"] | 0; error=""; ack="";
        if(!prefsReady || !bootConfirmed) { error="Boot not confirmed or OTA NVS unavailable"; report(); return; }
        auto candidate=esp_ota_get_next_update_partition(nullptr);
        auto running=esp_ota_get_running_partition();
        if(!candidate || !running || candidate->address==running->address || esp_ota_get_app_partition_count()<2) {
            error="No separate backup OTA slot"; report(); return;
        }
        String md5=doc["md5"] | "";
        if(String(doc["target"] | "")!=DEWY_NODE_ID || String(doc["board"] | "")!=DEWY_BOARD ||
           total<256 || md5.length()!=32) error="Invalid target or image metadata";
        else if(!Update.begin(total,U_FLASH)) error=Update.errorString();
        else if(!Update.setMD5(md5.c_str())) { Update.abort(); error="Invalid MD5"; }
        else { updating=true; ack="begin"; lastCommand=millis(); }
        report(); return;
    }
    if(incoming!=session) return;
    lastCommand=millis();
    if(op=="abort" && !committed) {
        Update.abort(); updating=false; error="Transfer aborted"; report(); return;
    }
    if(op=="end" && committed) { report(); return; }
    if(!updating) { report(); return; }
    if(op=="chunk") {
        size_t at=doc["offset"] | size_t(-1), size=0;
        String encoded=doc["data"] | "";
        unsigned char chunk[768];
        int result=mbedtls_base64_decode(chunk,sizeof(chunk),&size,
                         reinterpret_cast<const unsigned char*>(encoded.c_str()),encoded.length());
        if(result || !size || at>offset || at+size>total || (at<offset && at+size!=offset)) {
            error="Invalid chunk or offset";
        } else if(at==offset) {
            if(Update.write(chunk,size)!=size) error=Update.errorString();
            else offset+=size;
        }
        if(error.isEmpty()) ack="chunk";
    } else if(op=="end") {
        if(offset!=total) error="Incomplete image";
        else if(String(doc["build"] | "").length()!=32) error="Missing candidate build identity";
        else {
            // Persist before selecting the candidate slot: old firmware can report
            // a crash/bootloader rollback even if the new app never reaches setup().
            auto candidate=esp_ota_get_next_update_partition(nullptr);
            resultSlot=candidate ? candidate->label : "";
            if(!saveResult(session,doc["build"].as<String>(),"pending","")) error="OTA journal write failed";
        }
        if(error.isEmpty()) {
            if(!Update.end()) { error=Update.errorString(); saveResult(session,resultBuild,"failed","image_commit_failed"); }
            else { committed=true; updating=false; ack="end"; rebootAt=millis(); }
        }
    }
    if(!error.isEmpty()) { Update.abort(); updating=false; }
    report();
}
void maintenance_tick(bool connected) {
    if(trial && millis()>115000 && trialFailure.isEmpty()) {
        trialFailure=healthSnapshot().failure(millis()+5000);
        saveResult(resultSession,resultBuild,"pending",trialFailure.c_str());
    }
    if(committed && uint32_t(millis()-rebootAt)>1500) ESP.restart();
    if(updating && uint32_t(millis()-lastCommand)>30000) {
        Update.abort(); updating=false; error="Transfer idle timeout"; report();
    }
    if(!connected) return;
    if(uint32_t(millis()-lastReport)>=5000) report();
    // At most one log each 100ms; never block sensor/LED/feeding tasks.
    static uint32_t lastLog=0;
    if(uint32_t(millis()-lastLog)>=100) {
        LogLine item{};
        if(logs && xQueueReceive(logs,&item,0)==pdPASS) report(item.text);
        lastLog=millis();
    }
}
