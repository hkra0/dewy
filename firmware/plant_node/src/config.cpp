#include "config.h"
#include "config_protocol.h"
#include <Preferences.h>
RuntimeConfig rtConfig;
static std::string configError;
bool config_apply(const char* json) {
    RuntimeConfig candidate;
    if(!aqua::parse_config(json,rtConfig,candidate,configError)) return false;
    auto next=aqua::config_values(candidate);
    if(next!=aqua::config_values(rtConfig)) {
        Preferences p; p.begin("aqua_cfg",false);
        if(p.getString("v2", "")!=next.c_str()) p.putString("v2",next.c_str());
        p.end();
    }
    rtConfig=candidate; return true;
}
void config_init() {
    Preferences p; p.begin("aqua_cfg",true);
    String saved=p.getString("v2","");
    // 旧版只存了这三个键，迁移规则见 aqua::legacy_config。有 v2 记录时下面会整份覆盖。
    rtConfig=aqua::legacy_config(p.getFloat("t_high",32),p.getFloat("t_low",18),p.getInt("feed_hr",7)); p.end();
    if(saved.length()) config_apply(saved.c_str());
}
String config_to_json() {
    JsonDocument doc;
    deserializeJson(doc,aqua::config_values(rtConfig));
    doc["config_version"]=2;
    doc["config_error"]=configError;
    String out; serializeJson(doc,out); return out;
}
