/*
 * power.h - when may the board go to sleep (STM32 Stop 1)? Pure policy, no HAL.
 *
 * The main loop feeds this module with events (frame received, console input,
 * USB mounted, channel modes) and asks power_check() whether to sleep. The
 * target code in src/sleep.c does the actual Stop 1 entry and wake-up.
 *
 * Auto-sleep is allowed only when ALL of these hold:
 *   - sleep is enabled ("sleep on", the default),
 *   - no channel is in normal (TX-capable) mode for manual transmit, i.e.
 *     normal mode WITHOUT the gateway. A running gateway may sleep: the wake-up
 *     restores both channels to normal mode and the gateway carries on,
 *   - USB is not mounted by a host,
 *   - at least one channel can wake the board (monitor mode, or normal mode
 *     under the gateway); otherwise nothing but the UART could wake it,
 *   - no console input for timeout_ms,
 *   - no frame received on either channel for timeout_ms.
 *
 * Times are uint32_t milliseconds (HAL tick); differences are wrap-safe as long
 * as power_tick() runs at least once every few weeks, which the main loop does
 * thousands of times a second.
 */
#ifndef POWER_H
#define POWER_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define POWER_NUM_CHANNELS     2u
#define POWER_TIMEOUT_MIN_S    5u
#define POWER_TIMEOUT_MAX_S    86400u   /* one day */

/* Why the board is not going to sleep (POWER_OK = it may). Listed in the
 * order power_check() tests them. */
typedef enum {
    POWER_OK = 0,
    POWER_INHIBIT_DISABLED,     /* "sleep off" */
    POWER_INHIBIT_TX_NOW,       /* a channel is in normal mode without the gateway (manual TX) */
    POWER_INHIBIT_USB,          /* a USB host has the device mounted */
    POWER_INHIBIT_NO_LISTENER,  /* no channel that could wake the board */
    POWER_INHIBIT_CONSOLE,      /* console input within the timeout */
    POWER_INHIBIT_BUS,          /* a frame was received within the timeout */
} power_inhibit_t;

/* Wake sources, as a bitmask (several can fire together). 0 = unknown. */
enum {
    POWER_WAKE_CAN1 = 1u << 0,
    POWER_WAKE_CAN2 = 1u << 1,
    POWER_WAKE_UART = 1u << 2,
};

typedef struct {
    bool     enabled;
    uint32_t timeout_ms;

    /* Inputs (latest values). */
    uint32_t last_rx_ms[POWER_NUM_CHANNELS];
    uint32_t last_console_ms;
    bool     usb_mounted;
    bool     tx_now;            /* manual TX: a channel in normal mode, gateway off */
    bool     gateway;           /* gateway running (sleeps, and resumes on wake) */
    uint8_t  listen_mask;       /* bit n: channel n can wake the board (monitor, or normal under the gateway) */

    /* Statistics. */
    uint32_t sleeps;            /* Stop 1 entries */
    uint32_t wakes;             /* returns from Stop 1 */
    uint32_t aborted;           /* entries abandoned because something arrived */
    uint8_t  last_wake;         /* POWER_WAKE_* mask of the last wake-up (0 = unknown) */
    bool     have_woken;        /* last_wake is meaningful */
} power_t;

/* All activity timers start at now_ms, so the board stays up for at least one
 * timeout after boot. timeout_s is clamped to the allowed range. */
void power_init(power_t *p, uint32_t now_ms, bool enabled, uint32_t timeout_s);

/* Events. */
void power_frame(power_t *p, uint8_t chan, uint32_t now_ms);
void power_console(power_t *p, uint32_t now_ms);
/* A change of USB state (plugged in or unplugged) also counts as console
 * activity, so unplugging the laptop gives a full timeout before sleeping. */
void power_set_usb(power_t *p, bool mounted, uint32_t now_ms);
/* listen_mask: channels that can wake the board. tx_now: a channel is in
 * normal mode for manual transmit (gateway off). gateway: the gateway is on. */
void power_set_channels(power_t *p, uint8_t listen_mask, bool tx_now, bool gateway);

/* Call every main-loop pass: keeps old timestamps from wrapping round to
 * look recent (ages saturate at about 12 days). */
void power_tick(power_t *p, uint32_t now_ms);

/* Auto-sleep decision: POWER_OK, or the first reason it is inhibited. */
power_inhibit_t power_check(const power_t *p, uint32_t now_ms);

/* "sleep now": only refused during manual transmit (POWER_INHIBIT_TX_NOW).
 * Everything else (USB, timers, "sleep off") is overridden by the explicit
 * command. A running gateway is allowed. */
power_inhibit_t power_check_now(const power_t *p);

/* Milliseconds since the last frame on either channel (the smaller age). */
uint32_t power_bus_idle_ms(const power_t *p, uint32_t now_ms);
uint32_t power_console_idle_ms(const power_t *p, uint32_t now_ms);

/* If only the idle timers are holding sleep off, how long until it sleeps
 * (0 = would sleep now). Returns UINT32_MAX if something else inhibits it. */
uint32_t power_ms_until_sleep(const power_t *p, uint32_t now_ms);

void power_set_enabled(power_t *p, bool on);
/* Returns false (and changes nothing) outside POWER_TIMEOUT_MIN_S..MAX_S. */
bool power_set_timeout_s(power_t *p, uint32_t s);

/* Bookkeeping from the sleep code. A wake or an abort counts as activity on
 * every input, so the board stays up for a full timeout afterwards even if
 * the frame that woke it was lost. */
void power_on_sleep(power_t *p);
void power_on_wake(power_t *p, uint8_t wake_mask, uint32_t now_ms);
void power_on_abort(power_t *p, uint32_t now_ms);

const char *power_inhibit_str(power_inhibit_t r);

/* "can1", "can2+uart", "unknown", ... Always NUL-terminated; returns length. */
size_t power_wake_format(uint8_t wake_mask, char *buf, size_t cap);

#endif
