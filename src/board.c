// SPDX-License-Identifier: GPL-3.0-or-later

#include "board.h"

#include <stdint.h>

#include "driver/gpio.h"
#include "driver/ledc.h"
#include "driver/spi_master.h"
#include "esp_heap_caps.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_vendor.h"
#include "esp_lcd_touch.h"
#include "esp_lcd_touch_xpt2046.h"
#include "esp_lcd_ili9341.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lvgl.h"

#define LCD_HOST SPI2_HOST
#define LCD_MOSI 13
#define LCD_MISO 12
#define LCD_SCLK 14
#define LCD_DC 2
#define LCD_CS 15
#define LCD_BACKLIGHT 21
#define LCD_WIDTH 320
#define LCD_HEIGHT 240
#define LCD_DRAW_LINES 20

#define TOUCH_HOST SPI3_HOST
#define TOUCH_MOSI 32
#define TOUCH_MISO 39
#define TOUCH_SCLK 25
#define TOUCH_CS 33

static const char *TAG = "board";
static esp_lcd_panel_handle_t s_panel;
static esp_lcd_touch_handle_t s_touch;
static lv_display_t *s_display;

static bool color_done(esp_lcd_panel_io_handle_t io,
                       esp_lcd_panel_io_event_data_t *event, void *context)
{
    (void)io;
    (void)event;
    (void)context;
    if (s_display) lv_display_flush_ready(s_display);
    return false;
}

static void flush_display(lv_display_t *display, const lv_area_t *area,
                          uint8_t *pixels)
{
    esp_lcd_panel_draw_bitmap(s_panel, area->x1, area->y1,
                              area->x2 + 1, area->y2 + 1, pixels);
}

static uint16_t map_touch_axis(uint16_t value, uint16_t input_min,
                               uint16_t input_max, uint16_t output_max)
{
    if (value <= input_min) return 0;
    if (value >= input_max) return output_max;
    return (uint16_t)(((uint32_t)(value - input_min) * output_max)
                      / (input_max - input_min));
}

static void calibrate_touch(esp_lcd_touch_handle_t touch, uint16_t *x,
                            uint16_t *y, uint16_t *strength,
                            uint8_t *point_count, uint8_t max_points)
{
    (void)touch;
    (void)strength;
    const uint8_t count = *point_count < max_points
        ? *point_count : max_points;
    for (uint8_t i = 0; i < count; ++i) {
        /* Raw CYD panel range is approximately 250..3850.  The component has
           already scaled that into the portrait 240x320 axes here. */
        x[i] = map_touch_axis(x[i], 15, 226, LCD_HEIGHT - 1);
        y[i] = map_touch_axis(y[i], 20, 301, LCD_WIDTH - 1);
    }
}

static void read_touch(lv_indev_t *input, lv_indev_data_t *data)
{
    (void)input;
    data->continue_reading = false;
    data->state = LV_INDEV_STATE_RELEASED;
    if (esp_lcd_touch_read_data(s_touch) != ESP_OK) return;
    esp_lcd_touch_point_data_t point;
    uint8_t count = 0;
    if (esp_lcd_touch_get_data(s_touch, &point, &count, 1) != ESP_OK
        || count == 0) {
        data->state = LV_INDEV_STATE_RELEASED;
        return;
    }
    data->point.x = point.x;
    data->point.y = point.y;
    data->state = LV_INDEV_STATE_PRESSED;
}

static void tick_lvgl(void *unused)
{
    (void)unused;
    lv_tick_inc(2);
}

static void lvgl_task(void *unused)
{
    (void)unused;
    for (;;) {
        uint32_t wait_ms = lv_timer_handler();
        if (wait_ms < 2) wait_ms = 2;
        if (wait_ms > 20) wait_ms = 20;
        vTaskDelay(pdMS_TO_TICKS(wait_ms));
    }
}

static bool init_backlight(void)
{
    const ledc_timer_config_t timer = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .duty_resolution = LEDC_TIMER_10_BIT,
        .timer_num = LEDC_TIMER_0,
        .freq_hz = 5000,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    const ledc_channel_config_t channel = {
        .gpio_num = LCD_BACKLIGHT,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = LEDC_CHANNEL_0,
        .intr_type = LEDC_INTR_DISABLE,
        .timer_sel = LEDC_TIMER_0,
        .duty = 820,
        .hpoint = 0,
    };
    return ledc_timer_config(&timer) == ESP_OK
        && ledc_channel_config(&channel) == ESP_OK;
}

bool km_board_display_init(void)
{
    const spi_bus_config_t lcd_bus = {
        .mosi_io_num = LCD_MOSI,
        .miso_io_num = LCD_MISO,
        .sclk_io_num = LCD_SCLK,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = LCD_WIDTH * LCD_DRAW_LINES * 2,
    };
    if (spi_bus_initialize(LCD_HOST, &lcd_bus, SPI_DMA_CH_AUTO) != ESP_OK)
        return false;

    esp_lcd_panel_io_handle_t panel_io = NULL;
    const esp_lcd_panel_io_spi_config_t io_config = {
        .dc_gpio_num = LCD_DC,
        .cs_gpio_num = LCD_CS,
        .pclk_hz = 24000000,
        .lcd_cmd_bits = 8,
        .lcd_param_bits = 8,
        .spi_mode = 0,
        .trans_queue_depth = 10,
        .on_color_trans_done = color_done,
    };
    if (esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)LCD_HOST,
                                 &io_config, &panel_io) != ESP_OK) return false;
    const esp_lcd_panel_dev_config_t panel_config = {
        .reset_gpio_num = -1,
        .rgb_endian = LCD_RGB_ENDIAN_BGR,
        .bits_per_pixel = 16,
    };
    if (esp_lcd_new_panel_ili9341(panel_io, &panel_config, &s_panel) != ESP_OK)
        return false;
    esp_lcd_panel_reset(s_panel);
    esp_lcd_panel_init(s_panel);
    /* Match the CYD's known-good MADCTL value (MV only).  Setting MX after
       swapping axes mirrors the landscape image top-to-bottom. */
    esp_lcd_panel_swap_xy(s_panel, true);
    esp_lcd_panel_mirror(s_panel, false, false);
    esp_lcd_panel_disp_on_off(s_panel, true);

    const spi_bus_config_t touch_bus = {
        .mosi_io_num = TOUCH_MOSI,
        .miso_io_num = TOUCH_MISO,
        .sclk_io_num = TOUCH_SCLK,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = 3,
    };
    if (spi_bus_initialize(TOUCH_HOST, &touch_bus, SPI_DMA_CH_AUTO) != ESP_OK)
        return false;
    esp_lcd_panel_io_handle_t touch_io = NULL;
    const esp_lcd_panel_io_spi_config_t touch_io_config =
        ESP_LCD_TOUCH_IO_SPI_XPT2046_CONFIG(TOUCH_CS);
    const esp_lcd_touch_config_t touch_config = {
        /* The driver scales in the panel's portrait axes, then applies the
           software mirror and XY swap below. */
        .x_max = LCD_HEIGHT,
        .y_max = LCD_WIDTH,
        .rst_gpio_num = GPIO_NUM_NC,
        /* Poll pressure through SPI.  PENIRQ varies across CYD revisions. */
        .int_gpio_num = GPIO_NUM_NC,
        .levels = {
            .reset = 0,
            .interrupt = 0,
        },
        .process_coordinates = calibrate_touch,
        .flags = {
            .swap_xy = true,
            .mirror_x = false,
            .mirror_y = false,
        },
    };
    if (esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)TOUCH_HOST,
                                 &touch_io_config, &touch_io) != ESP_OK
        || esp_lcd_touch_new_spi_xpt2046(touch_io, &touch_config,
                                         &s_touch) != ESP_OK)
        return false;

    lv_init();
    s_display = lv_display_create(LCD_WIDTH, LCD_HEIGHT);
    if (!s_display) return false;
    /* SPI panels consume RGB565 most-significant byte first.  LVGL's native
       RGB565 buffer is little-endian on ESP32, so render it byte-swapped. */
    lv_display_set_color_format(s_display, LV_COLOR_FORMAT_RGB565_SWAPPED);
    lv_display_set_flush_cb(s_display, flush_display);
    void *draw_buffer = heap_caps_malloc(LCD_WIDTH * LCD_DRAW_LINES * 2,
                                         MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
    if (!draw_buffer) return false;
    lv_display_set_buffers(s_display, draw_buffer, NULL,
                           LCD_WIDTH * LCD_DRAW_LINES * 2,
                           LV_DISPLAY_RENDER_MODE_PARTIAL);

    lv_indev_t *input = lv_indev_create();
    lv_indev_set_type(input, LV_INDEV_TYPE_POINTER);
    lv_indev_set_display(input, s_display);
    lv_indev_set_read_cb(input, read_touch);

    const esp_timer_create_args_t timer_args = {
        .callback = tick_lvgl,
        .name = "lv_tick",
    };
    esp_timer_handle_t tick_timer;
    if (esp_timer_create(&timer_args, &tick_timer) != ESP_OK
        || esp_timer_start_periodic(tick_timer, 2000) != ESP_OK
        || !init_backlight()) return false;
    ESP_LOGI(TAG, "ILI9341 + XPT2046 online, DMA buffer=%u bytes",
             LCD_WIDTH * LCD_DRAW_LINES * 2);
    return true;
}

bool km_board_display_start(void)
{
    return xTaskCreate(lvgl_task, "lvgl", 6144, NULL, 5, NULL) == pdPASS;
}
