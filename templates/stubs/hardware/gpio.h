#pragma once
#include "pico/types.h"

#define GPIO_IN 0
#define GPIO_OUT 1

#define GPIO_FUNC_XIP 0
#define GPIO_FUNC_SPI 1
#define GPIO_FUNC_UART 2
#define GPIO_FUNC_I2C 3
#define GPIO_FUNC_PWM 4
#define GPIO_FUNC_SIO 5
#define GPIO_FUNC_PIO0 6
#define GPIO_FUNC_PIO1 7
#define GPIO_FUNC_GPCK 8
#define GPIO_FUNC_USB 9
#define GPIO_FUNC_NULL 0xf

#define GPIO_IRQ_EDGE_FALL 0x4
#define GPIO_IRQ_EDGE_RISE 0x8
#define GPIO_IRQ_LEVEL_LOW 0x1
#define GPIO_IRQ_LEVEL_HIGH 0x2

typedef void (*gpio_irq_callback_t)(uint gpio, uint32_t events);

static inline void gpio_init(uint gpio) { (void)gpio; }
static inline void gpio_set_dir(uint gpio, bool out) { (void)gpio; (void)out; }
static inline void gpio_put(uint gpio, bool value) { (void)gpio; (void)value; }
static inline bool gpio_get(uint gpio) { (void)gpio; return 0; }
static inline void gpio_set_function(uint gpio, int fn) { (void)gpio; (void)fn; }
static inline void gpio_pull_up(uint gpio) { (void)gpio; }
static inline void gpio_pull_down(uint gpio) { (void)gpio; }
static inline void gpio_disable_pulls(uint gpio) { (void)gpio; }
static inline void gpio_set_irq_enabled(uint gpio, uint32_t events, bool enabled) { (void)gpio; (void)events; (void)enabled; }
static inline void gpio_set_irq_enabled_with_callback(uint gpio, uint32_t events, bool enabled, gpio_irq_callback_t callback) {
    (void)gpio; (void)events; (void)enabled; (void)callback;
}
static inline void gpio_acknowledge_irq(uint gpio, uint32_t events) { (void)gpio; (void)events; }
