#pragma once
#include "aqua_model.h"
extern aqua::Alarms temperature_alarms;
aqua::Time local_time_now();
void temperature_alarm_init();
void temperature_alarm_update(const aqua::Sample& sample);
void temperature_alarm_save();
