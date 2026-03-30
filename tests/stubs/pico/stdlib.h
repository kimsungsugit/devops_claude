#pragma once
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "pico/types.h"
#include "pico/time.h"
#include "pico/sync.h"
#include "pico/multicore.h"
#include "hardware/gpio.h"
#include "hardware/uart.h"
#include "hardware/pio.h"
#include "hardware/adc.h"
#include "hardware/sync.h"
#include "hardware/irq.h"

// Standard Mock Functions
static inline void stdio_init_all(void) {}
static inline void tight_loop_contents(void) {}
