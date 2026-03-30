#pragma once
#include "pico/lock_core.h"
#include "pico/time.h"

static inline void mutex_init(mutex_t *mtx) { (void)mtx; }
static inline void mutex_enter_blocking(mutex_t *mtx) { (void)mtx; }
static inline bool mutex_try_enter(mutex_t *mtx, uint32_t *owner_out) {
    (void)mtx;
    if (owner_out) *owner_out = 1;
    return true;
}
static inline void mutex_exit(mutex_t *mtx) { (void)mtx; }
static inline bool mutex_enter_timeout_ms(mutex_t *mtx, uint32_t timeout_ms) {
    (void)mtx; (void)timeout_ms; return true;
}
static inline bool mutex_enter_timeout_us(mutex_t *mtx, uint64_t timeout_us) {
    (void)mtx; (void)timeout_us; return true;
}
