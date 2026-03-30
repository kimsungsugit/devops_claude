#pragma once
#include "hardware/pio.h"

static const pio_program_t ws2812_program = {
    .instructions = NULL,
    .length = 0,
    .origin = -1,
};

static inline void ws2812_program_init(PIO pio, uint sm, uint offset, uint pin, float freq, bool rgbw) {
    (void)pio; (void)sm; (void)offset; (void)pin; (void)freq; (void)rgbw;
}
