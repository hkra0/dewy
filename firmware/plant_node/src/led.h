#pragma once
#include <Arduino.h>

void led_init();
void led_trigger_temp_flash(float water_temp, bool water_temp_ok);
void led_update(bool is_fed, float water_temp, bool water_temp_ok);
