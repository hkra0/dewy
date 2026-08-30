#include "sensors.h"
#include "config.h"
#include <Wire.h>
#include <Adafruit_AHTX0.h>
#include <Adafruit_BMP280.h>
#include <OneWire.h>
#include <DallasTemperature.h>

static Adafruit_AHTX0 aht;
static Adafruit_BMP280 bmp;
static OneWire oneWire(DS18B20_PIN);
static DallasTemperature ds18b20(&oneWire);

static bool aht_online = false;
static bool bmp_online = false;
static bool ds_online = false;

static bool scan_i2c_bus(int sda, int scl) {
    Wire.end();
    Wire.begin(sda, scl);
    Wire.setClock(100000); // 100kHz 标准速率
    delay(50);

    Serial.printf("🔍 扫描 I2C (SDA=%d, SCL=%d): ", sda, scl);
    int count = 0;
    for (uint8_t addr = 1; addr < 127; addr++) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() == 0) {
            Serial.printf("[0x%02X] ", addr);
            count++;
        }
    }
    if (count == 0) {
        Serial.println("(无响应)");
        return false;
    } else {
        Serial.printf("共发现 %d 个设备\n", count);
        return true;
    }
}

void sensors_init() {
    Serial.println("📡 初始化传感器...");

    // 先尝试配置的 SDA=12, SCL=13
    bool found = scan_i2c_bus(SDA_PIN, SCL_PIN);
    if (!found) {
        // 若未找到，尝试引脚对调 SDA=13, SCL=12 (防线序反接容错)
        if (scan_i2c_bus(SCL_PIN, SDA_PIN)) {
            Serial.println("💡 提示: 检测到 I2C 引脚反接，已自动纠正并接管总线");
        }
    }

    // 1. 初始化 AHT20
    if (aht.begin()) {
        aht_online = true;
        Serial.println("✅ AHT20 初始化成功!");
    } else {
        aht_online = false;
        Serial.println("⚠️ 未找到 AHT20 传感器 (检查是否接线或地址)");
    }

    // 2. 初始化 BMP280 (尝试 0x77 与 0x76)
    if (bmp.begin(0x77) || bmp.begin(0x76)) {
        bmp_online = true;
        bmp.setSampling(Adafruit_BMP280::MODE_NORMAL,
                        Adafruit_BMP280::SAMPLING_X2,
                        Adafruit_BMP280::SAMPLING_X16,
                        Adafruit_BMP280::FILTER_X16,
                        Adafruit_BMP280::STANDBY_MS_500);
        Serial.println("✅ BMP280 初始化成功!");
    } else {
        bmp_online = false;
        Serial.println("⚠️ 未找到 BMP280 传感器 (检查是否接线或地址)");
    }

    // 3. 初始化 DS18B20
    ds18b20.begin();
    ds18b20.setWaitForConversion(false); // 非阻塞转换请求
    ds18b20.requestTemperatures();
    delay(100);
    float testTemp = ds18b20.getTempCByIndex(0);
    if (testTemp > -55.0f && testTemp < 125.0f && testTemp != 85.0f) {
        ds_online = true;
        Serial.printf("✅ DS18B20 初始化成功! 当前水温: %.2f ℃\n", testTemp);
    } else {
        ds_online = false;
        Serial.println("⚠️ 未检测到 DS18B20 探头 (可能未接线，继续运行)");
    }
}

SensorReadings sensors_read() {
    SensorReadings r = {};

    // 尝试重新检测未初始化的传感器 (热插拔容错)
    if (!aht_online) aht_online = aht.begin();
    if (!bmp_online) bmp_online = (bmp.begin(0x77) || bmp.begin(0x76));

    // 读取 AHT20
    if (aht_online) {
        sensors_event_t hum_ev, temp_ev;
        if (aht.getEvent(&hum_ev, &temp_ev)) {
            r.temperature = temp_ev.temperature;
            r.humidity = hum_ev.relative_humidity;
            r.temp_ok = true;
            r.hum_ok = true;
        } else {
            aht_online = false;
        }
    }

    // 读取 BMP280 (气压)
    if (bmp_online) {
        float pres = bmp.readPressure();
        if (!isnan(pres) && pres > 30000.0f && pres < 120000.0f) {
            r.pressure = pres / 100.0f; // 转换为 hPa
            r.press_ok = true;
        } else {
            bmp_online = false;
        }
    }

    // 读取 DS18B20
    ds18b20.requestTemperatures();
    float wt = ds18b20.getTempCByIndex(0);
    if (wt > -55.0f && wt < 125.0f && wt != 85.0f && wt != DEVICE_DISCONNECTED_C) {
        r.water_temp = wt;
        r.water_temp_ok = true;
        ds_online = true;
    } else {
        r.water_temp = 0.0f;
        r.water_temp_ok = false;
        ds_online = false;
    }

    return r;
}
