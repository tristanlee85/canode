/*
 * uart.h - USART2 debug console (canode J4 header / Nucleo ST-LINK virtual COM).
 * Interrupt driven with RX and TX ring buffers; writes never block.
 */
#ifndef UART_H
#define UART_H

#include <stddef.h>
#include <stdint.h>

void   uart_init(void);
int    uart_getc(void);                       /* -1 if nothing received */
size_t uart_write(const char *s, size_t n);   /* returns bytes queued; drops the rest */
uint32_t uart_dropped(void);                  /* TX bytes dropped because the buffer was full */

#endif
