#pragma once

#include <stdbool.h>

#include "heater_control.h"

typedef enum {
    KM_HEATER_OFF,
    KM_HEATER_HEATING,
    KM_HEATER_HOLDING,
    KM_HEATER_OVERSHOOT,
    KM_HEATER_FAULT,
} km_heater_state_t;

typedef struct {
    float temperature;
    float target;
    float fan;
    bool mcu_connected;
    bool wifi_connected;
    bool control_ready;
    float heater_power;
    km_control_fault_t fault;
    km_heater_state_t heater_state;
} km_state_snapshot_t;

void km_state_init(void);
km_state_snapshot_t km_state_snapshot(void);
void km_state_set_temperature(float value);
void km_state_set_target(float value);
void km_state_set_fan(float value);
void km_state_set_mcu_connected(bool connected);
void km_state_set_wifi_connected(bool connected);
void km_state_set_control(bool ready, float temperature, float power,
                          km_control_fault_t fault);
