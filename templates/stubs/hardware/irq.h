#pragma once
#include "pico/types.h"
static inline void irq_set_enabled(uint num, bool enabled) { (void)num; (void)enabled; }
static inline void irq_set_exclusive_handler(uint num, void (*handler)(void)) { (void)num; (void)handler; }
