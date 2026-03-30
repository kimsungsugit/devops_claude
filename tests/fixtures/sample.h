/**
 * @file sample.h
 * @brief Header for sample communication module
 */

#ifndef SAMPLE_H
#define SAMPLE_H

#include <stdint.h>
#include <string.h>

typedef struct {
    uint8_t mode;
    uint16_t timeout_ms;
} comm_config_t;

extern int g_comm_init(const comm_config_t *config);
extern uint16_t g_process_frame(const uint8_t *data, uint16_t length);
extern void g_comm_reset(void);

#endif /* SAMPLE_H */
