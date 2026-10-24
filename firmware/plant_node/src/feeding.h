#pragma once
#include <Arduino.h>
#include "aqua_model.h"
struct FeedingState {
    bool is_fed=false;
    String fed_time;
    const char* status="time_pending";
    float score=0;
    int next_date=0;
    bool prompting=false;
};
void feeding_init();
void feeding_update(const aqua::Sample& sample);
FeedingState feeding_get_state();
