/*
 * app.h - application state shared by the main loop and the shell commands.
 */
#ifndef APP_H
#define APP_H

#include <stdbool.h>
#include <stdint.h>

#include "console.h"
#include "gateway.h"
#include "shell.h"

#ifndef CANODE_FW_VERSION
#define CANODE_FW_VERSION "dev"
#endif

typedef struct {
    shell_t    shell[PORT_COUNT];
    uint8_t    log_mask[PORT_COUNT];  /* bit n set: stream frames from channel n to this port */
    uint64_t   epoch_offset_us;       /* added to uptime for candump timestamps ("time" command) */

    /* Gateway (milestone 5). Off at boot; needs both channels in NORMAL mode. */
    bool       gw_enabled;
    gw_table_t gw;
    uint32_t   gw_forwarded, gw_dropped, gw_tx_fail;
} app_t;

extern app_t g_app;

/* Set up both shells (commands.c). */
void commands_init(void);

/* Turn the gateway off and say why (to every port). */
void app_gateway_stop(const char *why);

#endif
