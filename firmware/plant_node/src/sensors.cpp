#include "maintenance.h"
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
static aqua::Sample water;
static aqua::ProbeQuality probe;
static bool converting=true;
static uint32_t conversion_started=0;

static bool scan_i2c_bus(int sda, int scl) {
    Wire.end();
    Wire.begin(sda, scl);
    Wire.setClock(100000); // 100kHz 标准速率
    delay(50);

    RemoteSerial.printf("🔍 扫描 I2C (SDA=%d, SCL=%d): ", sda, scl);
    int count = 0;
    for (uint8_t addr = 1; addr < 127; addr++) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() == 0) {
            RemoteSerial.printf("[0x%02X] ", addr);
            count++;
        }
    }
    if (count == 0) {
        RemoteSerial.println("(无响应)");
        return false;
    } else {
        RemoteSerial.printf("共发现 %d 个设备\n", count);
        return true;
    }
}

void sensors_init() {
    RemoteSerial.println("📡 初始化传感器...");

    // 先尝试配置的 SDA=12, SCL=13
    bool found = scan_i2c_bus(SDA_PIN, SCL_PIN);
    if (!found) {
        // 若未找到，尝试引脚对调 SDA=13, SCL=12 (防线序反接容错)
        if (scan_i2c_bus(SCL_PIN, SDA_PIN)) {
            RemoteSerial.println("💡 提示: 检测到 I2C 引脚反接，已自动纠正并接管总线");
        }
    }

    // 1. 初始化 AHT20
    if (aht.begin()) {
        aht_online = true;
        RemoteSerial.println("✅ AHT20 初始化成功!");
    } else {
        aht_online = false;
        RemoteSerial.println("⚠️ 未找到 AHT20 传感器 (检查是否接线或地址)");
    }

    // 2. 初始化 BMP280 (尝试 0x77 与 0x76)
    if (bmp.begin(0x77) || bmp.begin(0x76)) {
        bmp_online = true;
        bmp.setSampling(Adafruit_BMP280::MODE_NORMAL,
                        Adafruit_BMP280::SAMPLING_X2,
                        Adafruit_BMP280::SAMPLING_X16,
                        Adafruit_BMP280::FILTER_X16,
                        Adafruit_BMP280::STANDBY_MS_500);
        RemoteSerial.println("✅ BMP280 初始化成功!");
    } else {
        bmp_online = false;
        RemoteSerial.println("⚠️ 未找到 BMP280 传感器 (检查是否接线或地址)");
    }

    // 3. 初始化 DS18B20
    ds18b20.begin();
    ds18b20.setWaitForConversion(false); // 非阻塞转换请求
    ds18b20.setResolution(12);
    ds18b20.requestTemperatures();
    conversion_started=millis();
}

#include <algorithm>

aqua::Sample sensors_water() {
    const uint32_t now=millis();
    water=probe.snapshot(now);
    if(converting && uint32_t(now-conversion_started)>=750) {
        // Completed 12-bit conversion (750 ms); 85 C indicates a possible reset.
        water=probe.converted(ds18b20.getTempCByIndex(0),now);
        converting=false;
    }
    if(!converting && uint32_t(now-conversion_started)>=SENSOR_INTERVAL_MS) {
        ds18b20.requestTemperatures(); conversion_started=now; converting=true;
    }
    return water;
}

SensorReadings sensors_read() {
    SensorReadings r = {};

    // 尝试重新检测未初始化的传感器 (热插拔容错)
    if (!aht_online) aht_online = aht.begin();
    if (!bmp_online) bmp_online = (bmp.begin(0x77) || bmp.begin(0x76));

    // 1. 读取 AHT20 (5 次微采样修剪均值滤波)
    if (aht_online) {
        float temps[5];
        float hums[5];
        int valid_count = 0;

        for (int i = 0; i < 5; i++) {
            sensors_event_t hum_ev, temp_ev;
            if (aht.getEvent(&hum_ev, &temp_ev)) {
                // 物理合理性初步检查
                if (temp_ev.temperature > -40.0f && temp_ev.temperature < 85.0f &&
                    hum_ev.relative_humidity >= 0.0f && hum_ev.relative_humidity <= 100.0f) {
                    temps[valid_count] = temp_ev.temperature;
                    hums[valid_count] = hum_ev.relative_humidity;
                    valid_count++;
                }
            }
            if (i < 4) delay(25); // 25ms 间隔，总耗时 ~100ms
        }

        if (valid_count >= 3) {
            std::sort(temps, temps + valid_count);
            std::sort(hums, hums + valid_count);
            // 掐头去尾：剔除最小与最大值各 1 个，取中间均值
            float sum_t = 0.0f, sum_h = 0.0f;
            for (int i = 1; i < valid_count - 1; i++) {
                sum_t += temps[i];
                sum_h += hums[i];
            }
            int trimmed_count = valid_count - 2;
            r.temperature = sum_t / trimmed_count;
            r.humidity = sum_h / trimmed_count;
            r.temp_ok = true;
            r.hum_ok = true;
        } else if (valid_count > 0) {
            // 样本不足 3 个时优雅降级为简单均值
            float sum_t = 0.0f, sum_h = 0.0f;
            for (int i = 0; i < valid_count; i++) {
                sum_t += temps[i];
                sum_h += hums[i];
            }
            r.temperature = sum_t / valid_count;
            r.humidity = sum_h / valid_count;
            r.temp_ok = true;
            r.hum_ok = true;
        } else {
            aht_online = false;
        }
    }

    // 2. 读取 BMP280 气压 (3 次采样中位数滤波)
    if (bmp_online) {
        float p_samples[3];
        int p_count = 0;
        for (int i = 0; i < 3; i++) {
            float pres = bmp.readPressure();
            if (!isnan(pres) && pres > 30000.0f && pres < 120000.0f) {
                p_samples[p_count++] = pres / 100.0f; // 转换为 hPa
            }
            if (i < 2) delay(20);
        }

        if (p_count >= 3) {
            std::sort(p_samples, p_samples + p_count);
            r.pressure = p_samples[1]; // 中位数
            r.press_ok = true;
        } else if (p_count > 0) {
            r.pressure = p_samples[0];
            r.press_ok = true;
        } else {
            bmp_online = false;
        }
    }

    r.water_temp=water.value;
    r.water_temp_ok=water.valid;
    r.water_temp_age=water.age;
    return r;
}
