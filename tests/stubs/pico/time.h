#pragma once
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
