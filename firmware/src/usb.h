/*
 * usb.h - USB CDC-ACM virtual serial port (TinyUSB).
 */
#ifndef USB_H
#define USB_H

#include <stdbool.h>
#include <stddef.h>

void   usb_init(void);
void   usb_poll(void);              /* run TinyUSB's device task; call often */
bool   usb_connected(void);         /* a host program has the port open (DTR set) */
bool   usb_mounted(void);           /* a host has enumerated and configured us */
/* Before Stop mode: detach from the host and power the USB block down.
 * usb_init() brings it back (needs the HSI48 clock running again first). */
void   usb_stop(void);
bool   usb_take_open_event(void);   /* true once each time a host opens the port */
int    usb_getc(void);              /* -1 if nothing received */
size_t usb_write(const char *s, size_t n);

#endif
