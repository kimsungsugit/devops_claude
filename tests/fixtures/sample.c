/**
 * @file sample.c
 * @brief Sample C source for testing UDS generation pipeline
 * @requirement REQ-SW-001
 * @asil ASIL-B
 */

#include "sample.h"

#define MAX_BUFFER_SIZE  256
#define VERSION_MAJOR    1
#define VERSION_MINOR    7

/* Global variables */
static uint8_t g_buffer[MAX_BUFFER_SIZE];
static uint16_t g_counter = 0;

/**
 * @brief Initialize the communication module
 * @param[in] config Pointer to configuration struct
 * @return 0 on success, -1 on failure
 * @related SwFn_Init_001
 * @asil ASIL-B
 */
int g_comm_init(const comm_config_t *config)
{
    if (config == NULL) {
        return -1;
    }
    g_counter = 0;
    memset(g_buffer, 0, sizeof(g_buffer));
    return 0;
}

/**
 * @brief Process incoming data frame
 * @param[in] data Pointer to data buffer
 * @param[in] length Length of data buffer
 * @return Number of bytes processed
 * @related SwFn_Process_002
 * @precondition Module must be initialized
 */
uint16_t g_process_frame(const uint8_t *data, uint16_t length)
{
    uint16_t processed = 0;

    if (data == NULL || length == 0) {
        return 0;
    }

    for (uint16_t i = 0; i < length && i < MAX_BUFFER_SIZE; i++) {
        g_buffer[i] = data[i];
        processed++;
    }
    g_counter += processed;
    return processed;
}

/**
 * @brief Get current counter value (internal helper)
 * @return Current counter value
 */
static uint16_t s_get_counter(void)
{
    return g_counter;
}

/**
 * @brief Reset the module to initial state
 * @related SwFn_Reset_003
 */
void g_comm_reset(void)
{
    g_counter = 0;
    memset(g_buffer, 0, sizeof(g_buffer));
}
