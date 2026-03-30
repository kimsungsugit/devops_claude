#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "pico/platform.h"

#ifndef _UINT_DEFINED
#define _UINT_DEFINED
typedef unsigned int uint;
#endif

// HW Register access mocks
static inline void hw_clear_bits(volatile uint32_t *addr, uint32_t mask) { *addr &= ~mask; }
static inline void hw_set_bits(volatile uint32_t *addr, uint32_t mask) { *addr |= mask; }
static inline void hw_write_masked(volatile uint32_t *addr, uint32_t values, uint32_t write_mask) {
    *addr = (*addr & ~write_mask) | (values & write_mask);
}
