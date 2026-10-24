#pragma once
#include <Arduino.h>

// Mirrors application Serial output; SDK/ROM boot output still requires USB/UART.
class MaintenanceSerial : public Print {
public:
    using Print::write;
    size_t write(uint8_t value) override;
};
extern MaintenanceSerial RemoteSerial;
void maintenance_init();
void maintenance_loop_heartbeat();
void maintenance_command(const byte* payload, unsigned length);
void maintenance_tick(bool connected);
void maintenance_connected();
using MaintenancePublish = bool (*)(const char*, const char*, bool);
void maintenance_set_transport(MaintenancePublish publish);
