/*
 * console.h - the two places a human or a logger can talk to us.
 * Each has its own shell; command replies and the candump stream go to the
 * port that asked for them.
 */
#ifndef CONSOLE_H
#define CONSOLE_H

#include <stddef.h>
#include <stdint.h>

typedef enum { PORT_USB = 0, PORT_UART = 1, PORT_COUNT } port_t;

void   console_write(port_t p, const char *s, size_t n);
int    console_getc(port_t p);
const char *console_name(port_t p);

/* printf to every port (for asynchronous warnings such as bus-off). */
void   console_broadcast(const char *fmt, ...) __attribute__((format(printf, 1, 2)));

#endif
