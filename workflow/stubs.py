# /app/workflow/stubs.py
# Host 빌드 시 필요한 가짜 헤더 파일들을 생성 (Pico SDK Mocking)
# v30.13: Fix lock_core incomplete type, align host mutex_t with pthread, make mutex API field-agnostic

from pathlib import Path
from typing import Optional

from utils.log import get_logger

_logger = get_logger(__name__)

_TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "templates" / "stubs"
_ACTIVE_STUBS_ROOT: Optional[Path] = None


def _write_file(path: Path, content: str) -> None:
    try:
        # If a template exists, prefer it. If not, export current content to template.
        if _ACTIVE_STUBS_ROOT is not None:
            try:
                rel = path.resolve().relative_to(_ACTIVE_STUBS_ROOT.resolve())
                tpl = _TEMPLATE_ROOT / rel
                if tpl.exists():
                    content = tpl.read_text(encoding="utf-8", errors="ignore")
                else:
                    tpl.parent.mkdir(parents=True, exist_ok=True)
                    tpl.write_text(content, encoding="utf-8")
            except Exception:
                pass

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        _logger.info("Generated stub: %s", path.name)
    except OSError as e:
        _logger.warning("Failed to write %s: %s", path, e)


def ensure_stubs(stubs_root: Path) -> None:
    _logger.info("Ensuring robust stubs in: %s", stubs_root)
    global _ACTIVE_STUBS_ROOT
    _ACTIVE_STUBS_ROOT = Path(stubs_root)

    # 1. Base Config & Version
    _write_file(stubs_root / "pico/version.h", """#pragma once
#define PICO_SDK_VERSION_MAJOR 1
#define PICO_SDK_VERSION_MINOR 5
#define PICO_SDK_VERSION_REVISION 0
#define PICO_SDK_VERSION_STRING "1.5.0"
""")
    _write_file(stubs_root / "pico/config.h", "#pragma once\n")

    # 2. Platform & Types
    _write_file(stubs_root / "pico/platform.h", """#pragma once
#ifndef __not_in_flash_func
#define __not_in_flash_func(x) x
#endif
#ifndef __packed
#define __packed __attribute__((packed))
#endif
#ifndef weak
#define weak __attribute__((weak))
#endif
#ifndef __unused
#define __unused __attribute__((unused))
#endif
""")

    _write_file(stubs_root / "pico/types.h", """#pragma once
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
""")

    # 3. pico/lock_core.h
    # - struct lock_core를 상단에 독립 정의해 incomplete type 문제 제거
    # - HOST(Linux) 환경에서 mutex_t를 pthread_mutex_t로 alias 처리
    _write_file(stubs_root / "pico/lock_core.h", """#pragma once
#include "pico/types.h"

typedef struct lock_core {
    int spin_lock;
} lock_core_t;

#if defined(__linux__) || defined(__APPLE__) || defined(__unix__)
#include <pthread.h>
typedef pthread_mutex_t mutex_t;
#else
typedef struct {
    lock_core_t core;
    int owner;
    int enter_count;
} mutex_t;
#endif

typedef struct {
    lock_core_t core;
    int16_t permits;
    int16_t max_permits;
} semaphore_t;

typedef struct {
    lock_core_t core;
    uint32_t save;
} critical_section_t;
""")

    # 4. pico/time.h
    _write_file(stubs_root / "pico/time.h", """#pragma once
#include <stdint.h>
#include <stdbool.h>
#include "pico/types.h"

/*
Host stub time model
- 헤더 단독으로 동작하도록 static 상태 사용
- sleep_us/busy_wait_us 호출 시 가상 시간 증가
- get_absolute_time 호출 시에도 최소 1us 증가하여 무한루프 방지
*/

typedef uint64_t absolute_time_t;

static uint64_t __stub_time_us = 0;

static inline absolute_time_t get_absolute_time(void) {
    // 호출만 반복되는 루프에서도 시간 진행 보장
    return __stub_time_us++;
}

static inline absolute_time_t make_timeout_time_ms(uint32_t ms) {
    return __stub_time_us + ((uint64_t)ms * 1000ULL);
}

static inline int64_t absolute_time_diff_us(absolute_time_t from, absolute_time_t to) {
    return (int64_t)(to - from);
}

static inline void sleep_ms(uint32_t ms) {
    __stub_time_us += ((uint64_t)ms * 1000ULL);
}

static inline void sleep_us(uint64_t us) {
    __stub_time_us += us;
}

static inline void busy_wait_us(uint64_t us) {
    __stub_time_us += us;
}

static inline void busy_wait_ms(uint32_t ms) {
    __stub_time_us += ((uint64_t)ms * 1000ULL);
}
""")

    # 5. pico/mutex.h
    # - mutex_t가 pthread_mutex_t로 alias될 수 있으므로 구조체 필드 접근 제거
    _write_file(stubs_root / "pico/mutex.h", """#pragma once
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
""")

    # 6. pico/sem.h
    _write_file(stubs_root / "pico/sem.h", """#pragma once
#include "pico/lock_core.h"
#include "pico/time.h"

static inline void sem_init(semaphore_t *sem, int16_t initial_permits, int16_t max_permits) {
    sem->permits = initial_permits;
    sem->max_permits = max_permits;
}
static inline int sem_available(const semaphore_t *sem) { return sem->permits; }
static inline void sem_acquire_blocking(semaphore_t *sem) { sem->permits--; }
static inline bool sem_try_acquire(semaphore_t *sem) { sem->permits--; return true; }
static inline void sem_release(semaphore_t *sem) { sem->permits++; }
""")

    # 7. pico/critical_section.h
    _write_file(stubs_root / "pico/critical_section.h", """#pragma once
#include "pico/lock_core.h"
static inline void critical_section_init(critical_section_t *crit) { (void)crit; }
static inline void critical_section_enter_blocking(critical_section_t *crit) { (void)crit; }
static inline void critical_section_exit(critical_section_t *crit) { (void)crit; }
""")

    # 8. pico/sync.h
    _write_file(stubs_root / "pico/sync.h", """#pragma once
#include "pico/lock_core.h"
#include "pico/sem.h"
#include "pico/mutex.h"
#include "pico/critical_section.h"
""")

    # 9. hardware/gpio.h
    _write_file(stubs_root / "hardware/gpio.h", """#pragma once
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
""")

    # 10. hardware/uart.h
    _write_file(stubs_root / "hardware/uart.h", """#pragma once
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
""")

    # 11. hardware/pio.h
    _write_file(stubs_root / "hardware/pio.h", """#pragma once
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
""")

    # 12. pico/multicore.h
    _write_file(stubs_root / "pico/multicore.h", """#pragma once
#include "pico/types.h"
static inline void multicore_launch_core1(void (*entry)(void)) { (void)entry; }
static inline void multicore_reset_core1(void) {}
""")

    # 13. hardware/sync.h, irq.h, adc.h
    _write_file(stubs_root / "hardware/sync.h", """#pragma once
#include "pico/types.h"
static inline uint32_t save_and_disable_interrupts(void) { return 0; }
static inline void restore_interrupts(uint32_t status) { (void)status; }
""")

    _write_file(stubs_root / "hardware/irq.h", """#pragma once
#include "pico/types.h"
static inline void irq_set_enabled(uint num, bool enabled) { (void)num; (void)enabled; }
static inline void irq_set_exclusive_handler(uint num, void (*handler)(void)) { (void)num; (void)handler; }
""")

    _write_file(stubs_root / "hardware/adc.h", """#pragma once
#include "pico/types.h"
static inline void adc_init(void) {}
static inline void adc_gpio_init(uint gpio) { (void)gpio; }
static inline void adc_select_input(uint input) { (void)input; }
static inline uint16_t adc_read(void) { return 0; }
""")

    # 14. pico/stdlib.h (Main Aggregator)
    _write_file(stubs_root / "pico/stdlib.h", """#pragma once
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
""")

    # 15. hardware/regs/uart.h
    _write_file(stubs_root / "hardware/regs/uart.h", """#pragma once
#include "hardware/uart.h"
""")

    # 16. ws2812.pio.h
    _write_file(stubs_root / "ws2812.pio.h", """#pragma once
#include "hardware/pio.h"

static const pio_program_t ws2812_program = {
    .instructions = NULL,
    .length = 0,
    .origin = -1,
};

static inline void ws2812_program_init(PIO pio, uint sm, uint offset, uint pin, float freq, bool rgbw) {
    (void)pio; (void)sm; (void)offset; (void)pin; (void)freq; (void)rgbw;
}
""")

    # 17. Other headers
    other_headers = [
        "pico/binary_info.h", "pico/bootrom.h",
        "hardware/timer.h", "hardware/clocks.h", "hardware/i2c.h", "hardware/spi.h",
        "hardware/watchdog.h", "hardware/flash.h", "hardware/dma.h",
        "hardware/structs/systick.h", "hardware/address_mapped.h"
    ]
    for h in other_headers:
        _write_file(stubs_root / h, "#pragma once\n// Mock\n#include \"pico/types.h\"\n")

    # 18. hardware/watchdog.h (Better Stub for host timing/deadlock triage)
    _write_file(stubs_root / "hardware/watchdog.h", """#pragma once
#include <stdint.h>
#include <stdbool.h>

/*
Host watchdog stub
- 임베디드 코드에서 watchdog API 호출 시 빌드 에러 방지
- 테스트/동적분석에서 "kick" 호출 존재 여부 로깅용으로 확장 가능
*/

static inline void watchdog_enable(uint32_t delay_ms, bool pause_on_debug) { (void)delay_ms; (void)pause_on_debug; }
static inline void watchdog_update(void) {}
static inline bool watchdog_caused_reboot(void) { return false; }
static inline void watchdog_reboot(uint32_t pc, uint32_t sp, uint32_t delay_ms) { (void)pc; (void)sp; (void)delay_ms; }
""")

    _logger.info("All stubs generated successfully.")
