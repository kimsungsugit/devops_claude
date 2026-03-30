#pragma once
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
