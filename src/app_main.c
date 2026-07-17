#include "app_state.h"
#include "board.h"
#include "esp_err.h"
#include "esp_log.h"
#include "klipper_client.h"
#include "nvs_flash.h"
#include "ui.h"

static const char *TAG = "app";

void app_main(void)
{
    esp_err_t result = nvs_flash_init();
    if (result == ESP_ERR_NVS_NO_FREE_PAGES
        || result == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        result = nvs_flash_init();
    }
    ESP_ERROR_CHECK(result);
    km_state_init();
    if (!km_board_display_init()) {
        ESP_LOGE(TAG, "display initialization failed");
        return;
    }
    km_ui_create();
    if (!km_board_display_start()) {
        ESP_LOGE(TAG, "LVGL task initialization failed");
        return;
    }
    if (!km_client_start()) {
        ESP_LOGE(TAG, "Klipper UART client initialization failed");
        return;
    }
    ESP_LOGI(TAG, "native ESP-IDF application started");
}
