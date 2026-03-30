#pragma once
#include "pico/types.h"
static inline void multicore_launch_core1(void (*entry)(void)) { (void)entry; }
static inline void multicore_reset_core1(void) {}
