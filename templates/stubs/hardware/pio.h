#pragma once
#include "pico/types.h"

typedef struct pio_hw {
    uint32_t ctrl;
    uint32_t fdebug;
} pio_hw_t;

typedef pio_hw_t *PIO;
typedef uint pio_sm_t;

static pio_hw_t pio0_hw;
static pio_hw_t pio1_hw;
#define pio0 (&pio0_hw)
#define pio1 (&pio1_hw)

typedef struct {
    const uint16_t *instructions;
    uint8_t length;
    int8_t origin;
} pio_program_t;

static inline uint pio_add_program(PIO pio, const pio_program_t *program) { (void)pio; (void)program; return 0; }
static inline void pio_sm_put_blocking(PIO pio, uint sm, uint32_t data) { (void)pio; (void)sm; (void)data; }
static inline void pio_sm_get_blocking(PIO pio, uint sm, uint32_t *data) { (void)pio; (void)sm; if (data) *data = 0; }
static inline void pio_sm_set_enabled(PIO pio, uint sm, bool enabled) { (void)pio; (void)sm; (void)enabled; }
static inline void pio_sm_init(PIO pio, uint sm, uint offset, const void *config) { (void)pio; (void)sm; (void)offset; (void)config; }
static inline void pio_sm_set_consecutive_pindirs(PIO pio, uint sm, uint pin, uint count, bool is_out) {
    (void)pio; (void)sm; (void)pin; (void)count; (void)is_out;
}
static inline void pio_gpio_init(PIO pio, uint pin) { (void)pio; (void)pin; }
static inline void pio_sm_config_set_sideset_pins(void *c, uint bit) { (void)c; (void)bit; }
static inline void pio_sm_config_set_out_pins(void *c, uint bit, uint count) { (void)c; (void)bit; (void)count; }
static inline void pio_sm_config_set_fifo_join(void *c, int join) { (void)c; (void)join; }
static inline void pio_sm_config_set_clkdiv(void *c, float div) { (void)c; (void)div; }
static inline void pio_sm_clear_fifos(PIO pio, uint sm) { (void)pio; (void)sm; }
static inline void pio_sm_restart(PIO pio, uint sm) { (void)pio; (void)sm; }
