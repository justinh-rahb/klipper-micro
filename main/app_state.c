#include "app_state.h"

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

static SemaphoreHandle_t s_lock;
static km_state_snapshot_t s_state;

static km_heater_state_t heater_state(float temperature, float target)
{
    if (target <= 0.0f) {
        return KM_HEATER_OFF;
    }
    if (target - temperature > 1.0f) {
        return KM_HEATER_HEATING;
    }
    if (temperature - target > 1.0f) {
        return KM_HEATER_OVERSHOOT;
    }
    return KM_HEATER_HOLDING;
}

void km_state_init(void)
{
    s_lock = xSemaphoreCreateMutex();
    s_state = (km_state_snapshot_t) {
        .temperature = 22.0f,
        .target = 0.0f,
        .fan = 0.0f,
        .mcu_connected = false,
        .wifi_connected = false,
        .heater_state = KM_HEATER_OFF,
    };
}

km_state_snapshot_t km_state_snapshot(void)
{
    km_state_snapshot_t copy;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    copy = s_state;
    xSemaphoreGive(s_lock);
    return copy;
}

void km_state_set_temperature(float value)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    s_state.temperature = value;
    s_state.heater_state = heater_state(s_state.temperature, s_state.target);
    xSemaphoreGive(s_lock);
}

void km_state_set_target(float value)
{
    if (value < 0.0f) value = 0.0f;
    if (value > 100.0f) value = 100.0f;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    s_state.target = value;
    s_state.heater_state = heater_state(s_state.temperature, s_state.target);
    xSemaphoreGive(s_lock);
}

void km_state_set_fan(float value)
{
    if (value < 0.0f) value = 0.0f;
    if (value > 1.0f) value = 1.0f;
    xSemaphoreTake(s_lock, portMAX_DELAY);
    s_state.fan = value;
    xSemaphoreGive(s_lock);
}

void km_state_set_mcu_connected(bool connected)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    s_state.mcu_connected = connected;
    xSemaphoreGive(s_lock);
}

void km_state_set_wifi_connected(bool connected)
{
    xSemaphoreTake(s_lock, portMAX_DELAY);
    s_state.wifi_connected = connected;
    xSemaphoreGive(s_lock);
}
