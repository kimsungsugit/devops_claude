#pragma once
#include "pico/types.h"
static inline void adc_init(void) {}
static inline void adc_gpio_init(uint gpio) { (void)gpio; }
static inline void adc_select_input(uint input) { (void)input; }
static inline uint16_t adc_read(void) { return 0; }
