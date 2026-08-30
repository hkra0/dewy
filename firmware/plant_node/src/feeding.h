#pragma once
#include <Arduino.h>

struct FeedingState {
    bool is_fed;
    String fed_time; // 如 "08:35"，未喂食时为空串
};

void feeding_init();
void feeding_update(float water_temp, bool water_temp_ok);
FeedingState feeding_get_state();
