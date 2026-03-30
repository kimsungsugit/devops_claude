#pragma once
#include "pico/types.h"

static uint16_t __adc_stub_values[5] = {0};
static uint __adc_stub_selected_input = 0;

static inline void adc_stub_reset(void) {
    for (uint i = 0; i < 5; i++) __adc_stub_values[i] = 0;
    __adc_stub_selected_input = 0;
}

static inline void adc_stub_set_value(uint input, uint16_t value) {
    if (input < 5) __adc_stub_values[input] = value;
}

static inline void adc_init(void) {}
static inline void adc_gpio_init(uint gpio) { (void)gpio; }
static inline void adc_select_input(uint input) { __adc_stub_selected_input = input; }
static inline uint16_t adc_read(void) { return __adc_stub_values[__adc_stub_selected_input]; }
