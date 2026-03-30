#pragma once
#include "pico/types.h"
#include <stddef.h>

typedef struct {
    uint8_t index;
} uart_inst_t;

typedef struct {
    uint32_t dr;
    uint32_t rsr;
    uint32_t cr;
    uint32_t imsc;
    uint32_t icr;
} uart_hw_t;

#define UART_PARITY_NONE 0
#define UART_PARITY_EVEN 1
#define UART_PARITY_ODD  2
#define UART_UARTCR_RXE_BITS 0x00000200

static uart_inst_t uart0_inst = {0};
static uart_inst_t uart1_inst = {1};
#define uart0 (&uart0_inst)
#define uart1 (&uart1_inst)

static uart_hw_t mock_uart_hw;
static inline uart_hw_t *uart_get_hw(uart_inst_t *uart) { (void)uart; return &mock_uart_hw; }

// --- UART stub RX buffer helpers ---
#define UART_STUB_BUF_SIZE 256
static uint8_t __uart_stub_buf[UART_STUB_BUF_SIZE];
static int __uart_stub_head = 0;
static int __uart_stub_tail = 0;
static int __uart_stub_readable_after = 0;
static int __uart_stub_readable_calls = 0;

static inline void uart_stub_reset(void) {
    __uart_stub_head = 0;
    __uart_stub_tail = 0;
    __uart_stub_readable_after = 0;
    __uart_stub_readable_calls = 0;
}

static inline void uart_stub_set_readable_after(int n) {
    __uart_stub_readable_after = n;
    __uart_stub_readable_calls = 0;
}

static inline int uart_stub_available(void) {
    return (__uart_stub_head != __uart_stub_tail);
}

static inline void uart_stub_push_byte(uint8_t b) {
    __uart_stub_buf[__uart_stub_tail++] = b;
    if (__uart_stub_tail >= UART_STUB_BUF_SIZE) __uart_stub_tail = 0;
}

static inline void uart_stub_push_bytes(const uint8_t *data, size_t len) {
    if (!data || len == 0) return;
    for (size_t i = 0; i < len; i++) uart_stub_push_byte(data[i]);
}

static inline void uart_init(uart_inst_t *uart, uint baudrate) { (void)uart; (void)baudrate; }
static inline void uart_deinit(uart_inst_t *uart) { (void)uart; }
static inline void uart_set_hw_flow(uart_inst_t *uart, bool cts, bool rts) { (void)uart; (void)cts; (void)rts; }
static inline void uart_set_format(uart_inst_t *uart, uint data_bits, uint stop_bits, uint parity) {
    (void)uart; (void)data_bits; (void)stop_bits; (void)parity;
}
static inline void uart_set_fifo_enabled(uart_inst_t *uart, bool enabled) { (void)uart; (void)enabled; }
static inline bool uart_is_readable(uart_inst_t *uart) {
    (void)uart;
    if (__uart_stub_readable_after > 0 && __uart_stub_readable_calls++ < __uart_stub_readable_after) {
        return false;
    }
    return uart_stub_available();
}
static inline bool uart_is_writable(uart_inst_t *uart) { (void)uart; return true; }
static inline void uart_tx_wait_blocking(uart_inst_t *uart) { (void)uart; }
static inline void uart_putc_raw(uart_inst_t *uart, char c) { (void)uart; (void)c; }
static inline void uart_putc(uart_inst_t *uart, char c) { (void)uart; (void)c; }
static inline void uart_puts(uart_inst_t *uart, const char *s) { (void)uart; (void)s; }
static inline char uart_getc(uart_inst_t *uart) {
    (void)uart;
    if (!uart_stub_available()) return 0;
    uint8_t b = __uart_stub_buf[__uart_stub_head++];
    if (__uart_stub_head >= UART_STUB_BUF_SIZE) __uart_stub_head = 0;
    return (char)b;
}
static inline void uart_write_blocking(uart_inst_t *uart, const uint8_t *src, size_t len) {
    (void)uart; (void)src; (void)len;
}
static inline void uart_read_blocking(uart_inst_t *uart, uint8_t *dst, size_t len) {
    (void)uart; (void)dst; (void)len;
}
static inline bool uart_is_readable_within_us(uart_inst_t *uart, uint32_t us) { (void)uart; (void)us; return uart_is_readable(uart); }
static inline uint uart_set_baudrate(uart_inst_t *uart, uint baudrate) { (void)uart; return baudrate; }
static inline void uart_set_irq_enables(uart_inst_t *uart, bool rx_has_data, bool tx_needs_data) {
    (void)uart; (void)rx_has_data; (void)tx_needs_data;
}
