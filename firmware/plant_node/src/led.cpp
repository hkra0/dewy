#include "led.h"
#include "config.h"
#include <FastLED.h>

static CRGB leds[NUM_LEDS];
static CRGB current_color = CRGB::Black;

static unsigned long flash_start = 0;
static unsigned long flash_until = 0;
#define FLASH_DURATION_MS 800UL
static CRGB base_flash_color = CRGB::Black;

void led_init() {
    FastLED.addLeds<WS2812B, WS2812B_PIN, GRB>(leds, NUM_LEDS);
    FastLED.setBrightness(255); // 保持完整 8 位色彩精度，避免二次量化截断
    FastLED.setDither(BINARY_DITHER); // 启用硬件时间抖动平滑低亮度阶梯
    leds[0] = CRGB::Black;
    current_color = CRGB::Black;
    FastLED.show();
    Serial.println("💡 WS2812B RGB 灯初始化成功 (已启用动态低亮度色温补偿模式)");
}

void led_trigger_temp_flash(float water_temp, bool water_temp_ok) {
    flash_start = millis();
    flash_until = flash_start + FLASH_DURATION_MS;

    if (water_temp_ok) {
        float low = rtConfig.temp_alarm_low;
        float high = rtConfig.temp_alarm_high;
        float ratio = 0.5f;
        if (high > low) {
            ratio = (water_temp - low) / (high - low);
            if (ratio < 0.0f) ratio = 0.0f;
            if (ratio > 1.0f) ratio = 1.0f;
        }
        // 基于 HSV 色相空间平滑映射：
        // 低温 (ratio=0) -> 色相 96 (翠绿)
        // 中温 (ratio=0.5) -> 色相 60 (暖黄)
        // 高温 (ratio=1.0) -> 色相 20 (暖金橙)
        uint8_t hue = (uint8_t)(96.0f - ratio * 76.0f);
        base_flash_color = CHSV(hue, 225, 255);
    } else {
        base_flash_color = CRGB(60, 80, 70); // 传感器未就绪时显示柔和暖白微光
    }
}

// 计算带有“低亮度动态绿光补偿”的暖金琥珀呼吸灯颜色
// 仅在亮度降低时动态提升绿光比例，高亮时保持纯正暖橙金，避免发绿
static CRGB get_dynamic_amber_breath(uint8_t brightness_scale) {
    // 归一化亮度因子：0.0 (谷底 16) ~ 1.0 (峰值 80)
    float norm = (float)(brightness_scale - 16) / (float)(80 - 16);
    if (norm < 0.0f) norm = 0.0f;
    if (norm > 1.0f) norm = 1.0f;

    uint8_t r = brightness_scale;
    // 动态绿光比例：高亮度时取 0.48 (纯正暖金橙，绝无绿感)；暗处动态提升至 0.62 (抵消红光晶圆过亮优势)
    float g_ratio = 0.62f - norm * 0.14f; 
    uint8_t g = (uint8_t)(brightness_scale * g_ratio);
    uint8_t b = (uint8_t)(brightness_scale * 0.04f);

    return CRGB(r, g, b);
}

void led_update(bool is_fed, float water_temp, bool water_temp_ok) {
    unsigned long now = millis();
    CRGB target_color = CRGB::Black;

    // 1. 最高优先级：水温超限警报 (500ms 纯色闪烁)
    if (water_temp_ok) {
        if (water_temp > rtConfig.temp_alarm_high) {
            // 高温警报：纯红闪烁
            bool blink_on = ((now / 250) % 2) == 0;
            target_color = blink_on ? CRGB(220, 0, 0) : CRGB::Black;
            leds[0] = target_color;
            current_color = target_color;
            FastLED.show();
            return;
        } else if (water_temp < rtConfig.temp_alarm_low) {
            // 低温警报：纯蓝闪烁
            bool blink_on = ((now / 250) % 2) == 0;
            target_color = blink_on ? CRGB(0, 0, 220) : CRGB::Black;
            leds[0] = target_color;
            current_color = target_color;
            FastLED.show();
            return;
        }
    }

    // 2. 次高优先级：触摸触发的水温平滑微光指示 (带正弦钟形曲线淡入淡出)
    if (now < flash_until) {
        unsigned long elapsed = now - flash_start;
        float progress = (float)elapsed / (float)FLASH_DURATION_MS; // 0.0 -> 1.0
        float envelope = sin(progress * PI); // 0.0 -> 1.0 -> 0.0
        
        target_color = base_flash_color;
        // 峰值缩放至 55 (柔和微光，不刺眼)
        target_color.nscale8_video((uint8_t)(envelope * 55.0f));
    }
    // 3. 正常未喂食状态：动态色温补偿暖金微光呼吸 (3.2秒周期，亮度 16 ~ 80)
    else if (!is_fed) {
        float sine_val = (sin((now % 3200) * 2.0f * PI / 3200.0f) + 1.0f) * 0.5f; // 0.0 -> 1.0
        float smooth_sine = sine_val * sine_val;
        uint8_t brightness_scale = (uint8_t)(16 + smooth_sine * 64); // 16 ~ 80

        target_color = get_dynamic_amber_breath(brightness_scale);
    }
    // 4. 正常已喂食状态：平滑熄灭
    else {
        target_color = CRGB::Black;
    }

    // 每帧高精度插值平滑逼近目标颜色 (消除跳变与闪烁)
    current_color = blend(current_color, target_color, 24);
    leds[0] = current_color;
    FastLED.show();
}
