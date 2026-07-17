#include "ui.h"

#include <inttypes.h>
#include <stdio.h>

#include "app_state.h"
#include "klipper_client.h"
#include "lvgl.h"

#define COLOR_BG 0x121212
#define COLOR_PANEL 0x1e1e1e
#define COLOR_BORDER 0x2a2a2a
#define COLOR_TEXT 0xffffff
#define COLOR_DIM 0x9e9e9e
#define COLOR_ACCENT 0xffc107
#define COLOR_HEATING 0xff5722
#define COLOR_HOLDING 0x4caf50
#define COLOR_OVERSHOOT 0xff1744
#define COLOR_OFF 0x616161
#define COLOR_ERROR 0xf44336
#define COLOR_FAN 0x29b6f6

typedef struct {
    lv_obj_t *temperature;
    lv_obj_t *target;
    lv_obj_t *target_unit;
    lv_obj_t *heater_dot;
    lv_obj_t *heater_label;
    lv_obj_t *mcu_warning;
    lv_obj_t *wifi_label;
    lv_obj_t *fan_bar;
} ui_t;

static ui_t s_ui;

static void no_border(lv_obj_t *object)
{
    lv_obj_set_style_border_width(object, 0, 0);
    lv_obj_set_style_radius(object, 0, 0);
}

static void panel_style(lv_obj_t *panel)
{
    lv_obj_set_style_bg_color(panel, lv_color_hex(COLOR_PANEL), 0);
    lv_obj_set_style_bg_opa(panel, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(panel, lv_color_hex(COLOR_BORDER), 0);
    lv_obj_set_style_border_width(panel, 1, 0);
    lv_obj_set_style_radius(panel, 8, 0);
    lv_obj_set_style_pad_all(panel, 4, 0);
    lv_obj_remove_flag(panel, LV_OBJ_FLAG_SCROLLABLE);
}

static lv_obj_t *label(lv_obj_t *parent, const char *text, uint32_t color,
                       const lv_font_t *font)
{
    lv_obj_t *object = lv_label_create(parent);
    lv_label_set_text(object, text);
    lv_obj_set_style_text_color(object, lv_color_hex(color), 0);
    if (font) lv_obj_set_style_text_font(object, font, 0);
    return object;
}

static void set_target(lv_event_t *event)
{
    const intptr_t value = (intptr_t)lv_event_get_user_data(event);
    km_state_set_target((float)value);
}

static void cycle_fan(lv_event_t *event)
{
    (void)event;
    const float fan = km_state_snapshot().fan;
    km_state_set_fan(fan < 0.25f ? 0.5f : fan < 0.75f ? 1.0f : 0.0f);
}

static void off_clicked(lv_event_t *event)
{
    (void)event;
    km_state_set_target(0.0f);
}

static void emergency_stop(lv_event_t *event)
{
    (void)event;
    km_state_set_target(0.0f);
    km_state_set_fan(0.0f);
    km_client_emergency_stop();
}

static void make_quick_button(lv_obj_t *parent, int x, int y, int value)
{
    lv_obj_t *button = lv_button_create(parent);
    lv_obj_set_size(button, 49, 22);
    lv_obj_set_pos(button, x, y);
    lv_obj_set_style_pad_all(button, 0, 0);
    char text[8];
    snprintf(text, sizeof(text), "%d", value);
    lv_obj_t *caption = label(button, text, COLOR_TEXT, &lv_font_montserrat_14);
    lv_obj_center(caption);
    lv_obj_add_event_cb(button, set_target, LV_EVENT_CLICKED,
                        (void *)(intptr_t)value);
}

static uint32_t state_color(km_heater_state_t state)
{
    switch (state) {
    case KM_HEATER_HEATING: return COLOR_HEATING;
    case KM_HEATER_HOLDING: return COLOR_HOLDING;
    case KM_HEATER_OVERSHOOT: return COLOR_OVERSHOOT;
    default: return COLOR_OFF;
    }
}

static const char *state_name(km_heater_state_t state)
{
    switch (state) {
    case KM_HEATER_HEATING: return "heating";
    case KM_HEATER_HOLDING: return "holding";
    case KM_HEATER_OVERSHOOT: return "overshoot";
    default: return "off";
    }
}

static void refresh(lv_timer_t *timer)
{
    (void)timer;
    const km_state_snapshot_t state = km_state_snapshot();
    char text[24];
    snprintf(text, sizeof(text), "%.1f", state.temperature);
    lv_label_set_text(s_ui.temperature, text);
    if (state.target > 0.0f) {
        snprintf(text, sizeof(text), "%.0f", state.target);
        lv_label_set_text(s_ui.target, text);
        lv_obj_remove_flag(s_ui.target_unit, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_label_set_text(s_ui.target, "OFF");
        lv_obj_add_flag(s_ui.target_unit, LV_OBJ_FLAG_HIDDEN);
    }
    const lv_color_t heater_color = lv_color_hex(state_color(state.heater_state));
    lv_label_set_text(s_ui.heater_label, state_name(state.heater_state));
    lv_obj_set_style_text_color(s_ui.heater_label, heater_color, 0);
    lv_obj_set_style_bg_color(s_ui.heater_dot, heater_color, 0);
    lv_bar_set_value(s_ui.fan_bar, (int32_t)(state.fan * 100.0f), LV_ANIM_OFF);
    if (state.mcu_connected)
        lv_obj_add_flag(s_ui.mcu_warning, LV_OBJ_FLAG_HIDDEN);
    else
        lv_obj_remove_flag(s_ui.mcu_warning, LV_OBJ_FLAG_HIDDEN);
    lv_obj_set_style_text_color(s_ui.wifi_label,
        lv_color_hex(state.wifi_connected ? COLOR_HOLDING : COLOR_OFF), 0);
}

void km_ui_create(void)
{
    lv_obj_t *screen = lv_screen_active();
    lv_obj_set_style_bg_color(screen, lv_color_hex(COLOR_BG), 0);
    lv_obj_set_style_bg_opa(screen, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_all(screen, 0, 0);
    lv_obj_remove_flag(screen, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *bar = lv_obj_create(screen);
    lv_obj_set_size(bar, 320, 24);
    lv_obj_set_pos(bar, 0, 0);
    lv_obj_set_style_bg_color(bar, lv_color_hex(COLOR_PANEL), 0);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_all(bar, 2, 0);
    no_border(bar);
    lv_obj_remove_flag(bar, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_t *title = label(bar, "klipper-micro", COLOR_ACCENT,
                            &lv_font_montserrat_14);
    lv_obj_align(title, LV_ALIGN_LEFT_MID, 6, 0);
    s_ui.mcu_warning = label(bar, LV_SYMBOL_WARNING, COLOR_ERROR,
                             &lv_font_montserrat_14);
    lv_obj_align(s_ui.mcu_warning, LV_ALIGN_RIGHT_MID, -96, 0);
    s_ui.wifi_label = label(bar, LV_SYMBOL_WIFI, COLOR_OFF,
                            &lv_font_montserrat_14);
    lv_obj_align(s_ui.wifi_label, LV_ALIGN_RIGHT_MID, -56, 0);
    lv_obj_t *settings = label(bar, LV_SYMBOL_SETTINGS, COLOR_TEXT,
                               &lv_font_montserrat_14);
    lv_obj_align(settings, LV_ALIGN_RIGHT_MID, -18, 0);

    lv_obj_t *left = lv_obj_create(screen);
    lv_obj_set_size(left, 195, 212);
    lv_obj_set_pos(left, 4, 28);
    panel_style(left);
    s_ui.temperature = label(left, "--.-", COLOR_TEXT, &lv_font_montserrat_48);
    lv_obj_align(s_ui.temperature, LV_ALIGN_TOP_MID, 0, 4);
    lv_obj_t *unit = label(left, "C", COLOR_DIM, &lv_font_montserrat_20);
    lv_obj_align_to(unit, s_ui.temperature, LV_ALIGN_OUT_BOTTOM_MID, 0, -8);
    s_ui.heater_dot = lv_obj_create(left);
    lv_obj_set_size(s_ui.heater_dot, 10, 10);
    lv_obj_set_style_radius(s_ui.heater_dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(s_ui.heater_dot, lv_color_hex(COLOR_OFF), 0);
    lv_obj_set_style_bg_opa(s_ui.heater_dot, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_all(s_ui.heater_dot, 0, 0);
    no_border(s_ui.heater_dot);
    lv_obj_align(s_ui.heater_dot, LV_ALIGN_BOTTOM_LEFT, 6, -12);
    s_ui.heater_label = label(left, "off", COLOR_OFF, &lv_font_montserrat_16);
    lv_obj_align_to(s_ui.heater_label, s_ui.heater_dot,
                    LV_ALIGN_OUT_RIGHT_MID, 6, 0);

    lv_obj_t *right = lv_obj_create(screen);
    lv_obj_set_size(right, 113, 212);
    lv_obj_set_pos(right, 203, 28);
    panel_style(right);
    lv_obj_t *set_caption = label(right, "SET", COLOR_DIM,
                                  &lv_font_montserrat_12);
    lv_obj_set_pos(set_caption, 4, 2);
    s_ui.target = label(right, "OFF", COLOR_TEXT, &lv_font_montserrat_36);
    lv_obj_align(s_ui.target, LV_ALIGN_TOP_MID, 0, 20);
    s_ui.target_unit = label(right, "C", COLOR_DIM, &lv_font_montserrat_14);
    lv_obj_align_to(s_ui.target_unit, s_ui.target,
                    LV_ALIGN_OUT_BOTTOM_MID, 0, -4);

    make_quick_button(right, 0, 88, 45);
    make_quick_button(right, 53, 88, 50);
    make_quick_button(right, 0, 114, 55);
    make_quick_button(right, 53, 114, 60);

    lv_obj_t *off = lv_button_create(right);
    lv_obj_set_size(off, 102, 20);
    lv_obj_set_pos(off, 0, 140);
    lv_obj_set_style_pad_all(off, 0, 0);
    lv_obj_set_style_bg_color(off, lv_color_hex(COLOR_ERROR), 0);
    lv_obj_t *off_label = label(off, "OFF", COLOR_TEXT, &lv_font_montserrat_14);
    lv_obj_center(off_label);
    lv_obj_add_event_cb(off, off_clicked, LV_EVENT_CLICKED, NULL);
    lv_obj_add_event_cb(off, emergency_stop, LV_EVENT_LONG_PRESSED, NULL);

    lv_obj_t *fan_caption = label(right, "FAN", COLOR_DIM,
                                  &lv_font_montserrat_12);
    lv_obj_align(fan_caption, LV_ALIGN_BOTTOM_LEFT, 2, -26);
    s_ui.fan_bar = lv_bar_create(right);
    lv_obj_set_size(s_ui.fan_bar, 102, 16);
    lv_bar_set_range(s_ui.fan_bar, 0, 100);
    lv_obj_set_style_bg_color(s_ui.fan_bar, lv_color_hex(COLOR_BORDER), 0);
    lv_obj_set_style_bg_color(s_ui.fan_bar, lv_color_hex(COLOR_FAN),
                              LV_PART_INDICATOR);
    lv_obj_align(s_ui.fan_bar, LV_ALIGN_BOTTOM_MID, 0, -8);
    lv_obj_add_flag(s_ui.fan_bar, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_event_cb(s_ui.fan_bar, cycle_fan, LV_EVENT_CLICKED, NULL);

    refresh(NULL);
    lv_timer_create(refresh, 250, NULL);
}
