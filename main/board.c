#include "board.h"

#include <stdint.h>

#include "driver/gpio.h"
#include "driver/ledc.h"
#include "driver/spi_master.h"
#include "esp_heap_caps.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_vendor.h"
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
static spi_device_handle_t s_touch;
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

static uint16_t touch_sample(uint8_t command)
{
    spi_transaction_t transaction = {
        .flags = SPI_TRANS_USE_TXDATA | SPI_TRANS_USE_RXDATA,
        .length = 24,
    };
    transaction.tx_data[0] = command;
    if (spi_device_transmit(s_touch, &transaction) != ESP_OK) return 0;
    return (uint16_t)((transaction.rx_data[1] << 8)
                      | transaction.rx_data[2]) >> 3;
}

static int32_t map_clamped(int32_t value, int32_t in_min, int32_t in_max,
                           int32_t out_max)
{
    if (value < in_min) value = in_min;
    if (value > in_max) value = in_max;
    return (value - in_min) * out_max / (in_max - in_min);
}

static void read_touch(lv_indev_t *input, lv_indev_data_t *data)
{
    (void)input;
    const uint16_t pressure = touch_sample(0xb0);
    if (pressure < 120) {
        data->state = LV_INDEV_STATE_RELEASED;
        return;
    }
    uint32_t raw_x = 0;
    uint32_t raw_y = 0;
    for (unsigned i = 0; i < 4; ++i) {
        raw_x += touch_sample(0xd0);
        raw_y += touch_sample(0x90);
    }
    raw_x /= 4;
    raw_y /= 4;
    /* CYD landscape calibration. Keep these constants in one place until
       NVS-backed four-point calibration is added. */
    data->point.x = LCD_WIDTH - 1
        - map_clamped(raw_y, 250, 3850, LCD_WIDTH - 1);
    data->point.y = map_clamped(raw_x, 250, 3850, LCD_HEIGHT - 1);
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
    esp_lcd_panel_swap_xy(s_panel, true);
    esp_lcd_panel_mirror(s_panel, true, false);
    esp_lcd_panel_disp_on_off(s_panel, true);

    const spi_bus_config_t touch_bus = {
        .mosi_io_num = TOUCH_MOSI,
        .miso_io_num = TOUCH_MISO,
        .sclk_io_num = TOUCH_SCLK,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = 3,
    };
    const spi_device_interface_config_t touch_device = {
        .clock_speed_hz = 2000000,
        .mode = 0,
        .spics_io_num = TOUCH_CS,
        .queue_size = 1,
    };
    if (spi_bus_initialize(TOUCH_HOST, &touch_bus, SPI_DMA_CH_AUTO) != ESP_OK
        || spi_bus_add_device(TOUCH_HOST, &touch_device, &s_touch) != ESP_OK)
        return false;

    lv_init();
    s_display = lv_display_create(LCD_WIDTH, LCD_HEIGHT);
    if (!s_display) return false;
    lv_display_set_color_format(s_display, LV_COLOR_FORMAT_RGB565);
    lv_display_set_flush_cb(s_display, flush_display);
    void *draw_buffer = heap_caps_malloc(LCD_WIDTH * LCD_DRAW_LINES * 2,
                                         MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
    if (!draw_buffer) return false;
    lv_display_set_buffers(s_display, draw_buffer, NULL,
                           LCD_WIDTH * LCD_DRAW_LINES * 2,
                           LV_DISPLAY_RENDER_MODE_PARTIAL);

    lv_indev_t *input = lv_indev_create();
    lv_indev_set_type(input, LV_INDEV_TYPE_POINTER);
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
