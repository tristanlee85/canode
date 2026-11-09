#include "console.h"

#include <stdarg.h>
#include <stdio.h>

#include "uart.h"
#include "usb.h"

void console_write(port_t p, const char *s, size_t n)
{
    if (p == PORT_USB)
        (void)usb_write(s, n);
    else
        (void)uart_write(s, n);
}

int console_getc(port_t p)
{
    return p == PORT_USB ? usb_getc() : uart_getc();
}

const char *console_name(port_t p)
{
    return p == PORT_USB ? "usb" : "uart";
}

void console_broadcast(const char *fmt, ...)
{
    char buf[160];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (n < 0)
        return;
    if ((size_t)n >= sizeof(buf))
        n = (int)sizeof(buf) - 1;
    for (int p = 0; p < PORT_COUNT; p++)
        console_write((port_t)p, buf, (size_t)n);
}
