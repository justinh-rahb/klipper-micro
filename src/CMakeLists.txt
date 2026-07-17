idf_component_register(
    SRCS
        "app_main.c"
        "board.c"
        "app_state.c"
        "heater_control.c"
        "ui.c"
        "klipper_protocol.c"
        "klipper_dictionary.c"
        "klipper_clocksync.c"
        "klipper_client.c"
    INCLUDE_DIRS "."
    REQUIRES driver esp_lcd esp_lcd_ili9341 esp_lcd_touch_xpt2046 esp_timer
        nvs_flash zlib lvgl
)
