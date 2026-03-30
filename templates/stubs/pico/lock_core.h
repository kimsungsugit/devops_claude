#pragma once
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
