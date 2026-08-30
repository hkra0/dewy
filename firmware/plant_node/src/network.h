#pragma once
#include <Arduino.h>
#include "sensors.h"
#include "feeding.h"

void network_init();
void network_loop();
bool network_publish_data(const SensorReadings& sensors, const FeedingState& feeding);
void network_publish_config_state();
