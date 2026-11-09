#include "power.h"

#include <string.h>

/* Ages saturate here (~12.4 days): far above the longest timeout (1 day) and
 * far below the 49.7-day uint32_t wrap. */
#define AGE_MAX_MS 0x40000000u

static uint32_t age(uint32_t now, uint32_t then)
{
    return now - then;
}

static void touch_all(power_t *p, uint32_t now_ms)
{
    for (unsigned ch = 0; ch < POWER_NUM_CHANNELS; ch++)
        p->last_rx_ms[ch] = now_ms;
    p->last_console_ms = now_ms;
}

static uint32_t clamp_timeout_s(uint32_t s)
{
    if (s < POWER_TIMEOUT_MIN_S)
        return POWER_TIMEOUT_MIN_S;
    if (s > POWER_TIMEOUT_MAX_S)
        return POWER_TIMEOUT_MAX_S;
    return s;
}

void power_init(power_t *p, uint32_t now_ms, bool enabled, uint32_t timeout_s)
{
    memset(p, 0, sizeof(*p));
    p->enabled = enabled;
    p->timeout_ms = clamp_timeout_s(timeout_s) * 1000u;
    p->listen_mask = (uint8_t)((1u << POWER_NUM_CHANNELS) - 1u);
    touch_all(p, now_ms);
}

void power_frame(power_t *p, uint8_t chan, uint32_t now_ms)
{
    if (chan < POWER_NUM_CHANNELS)
        p->last_rx_ms[chan] = now_ms;
}

void power_console(power_t *p, uint32_t now_ms)
{
    p->last_console_ms = now_ms;
}

void power_set_usb(power_t *p, bool mounted, uint32_t now_ms)
{
    if (mounted != p->usb_mounted)
        p->last_console_ms = now_ms;
    p->usb_mounted = mounted;
}

void power_set_channels(power_t *p, uint8_t listen_mask, bool tx_now, bool tx_ever)
{
    p->listen_mask = listen_mask;
    p->tx_now = tx_now;
    if (tx_now || tx_ever)
        p->tx_session = true;
}

void power_tick(power_t *p, uint32_t now_ms)
{
    for (unsigned ch = 0; ch < POWER_NUM_CHANNELS; ch++) {
        if (age(now_ms, p->last_rx_ms[ch]) > AGE_MAX_MS)
            p->last_rx_ms[ch] = now_ms - AGE_MAX_MS;
    }
    if (age(now_ms, p->last_console_ms) > AGE_MAX_MS)
        p->last_console_ms = now_ms - AGE_MAX_MS;
}

uint32_t power_bus_idle_ms(const power_t *p, uint32_t now_ms)
{
    uint32_t idle = UINT32_MAX;
    for (unsigned ch = 0; ch < POWER_NUM_CHANNELS; ch++) {
        uint32_t a = age(now_ms, p->last_rx_ms[ch]);
        if (a < idle)
            idle = a;
    }
    return idle;
}

uint32_t power_console_idle_ms(const power_t *p, uint32_t now_ms)
{
    return age(now_ms, p->last_console_ms);
}

/* Everything except the two idle timers. */
static power_inhibit_t check_static(const power_t *p)
{
    if (!p->enabled)
        return POWER_INHIBIT_DISABLED;
    if (p->tx_now)
        return POWER_INHIBIT_TX_NOW;
    if (p->tx_session)
        return POWER_INHIBIT_TX_SESSION;
    if (p->usb_mounted)
        return POWER_INHIBIT_USB;
    if (p->listen_mask == 0u)
        return POWER_INHIBIT_NO_LISTENER;
    return POWER_OK;
}

power_inhibit_t power_check(const power_t *p, uint32_t now_ms)
{
    power_inhibit_t r = check_static(p);
    if (r != POWER_OK)
        return r;
    if (power_console_idle_ms(p, now_ms) < p->timeout_ms)
        return POWER_INHIBIT_CONSOLE;
    if (power_bus_idle_ms(p, now_ms) < p->timeout_ms)
        return POWER_INHIBIT_BUS;
    return POWER_OK;
}

power_inhibit_t power_check_now(const power_t *p)
{
    return p->tx_now ? POWER_INHIBIT_TX_NOW : POWER_OK;
}

uint32_t power_ms_until_sleep(const power_t *p, uint32_t now_ms)
{
    if (check_static(p) != POWER_OK)
        return UINT32_MAX;
    uint32_t idle = power_bus_idle_ms(p, now_ms);
    uint32_t con = power_console_idle_ms(p, now_ms);
    if (con < idle)
        idle = con;
    return idle >= p->timeout_ms ? 0u : p->timeout_ms - idle;
}

void power_set_enabled(power_t *p, bool on)
{
    p->enabled = on;
}

bool power_set_timeout_s(power_t *p, uint32_t s)
{
    if (s < POWER_TIMEOUT_MIN_S || s > POWER_TIMEOUT_MAX_S)
        return false;
    p->timeout_ms = s * 1000u;
    return true;
}

void power_on_sleep(power_t *p)
{
    p->sleeps++;
}

void power_on_wake(power_t *p, uint8_t wake_mask, uint32_t now_ms)
{
    p->wakes++;
    p->last_wake = wake_mask;
    p->have_woken = true;
    touch_all(p, now_ms);
}

void power_on_abort(power_t *p, uint32_t now_ms)
{
    p->aborted++;
    touch_all(p, now_ms);
}

const char *power_inhibit_str(power_inhibit_t r)
{
    switch (r) {
    case POWER_OK:                  return "none";
    case POWER_INHIBIT_DISABLED:    return "sleep is off";
    case POWER_INHIBIT_TX_NOW:      return "a channel is transmit-enabled (normal mode or gateway)";
    case POWER_INHIBIT_TX_SESSION:  return "transmit was enabled since boot (reboot to re-arm auto-sleep)";
    case POWER_INHIBIT_USB:         return "USB host connected";
    case POWER_INHIBIT_NO_LISTENER: return "no channel is in monitor mode";
    case POWER_INHIBIT_CONSOLE:     return "console in use";
    case POWER_INHIBIT_BUS:         return "bus active";
    default:                        return "?";
    }
}

size_t power_wake_format(uint8_t wake_mask, char *buf, size_t cap)
{
    static const char *const names[] = {"can1", "can2", "uart"};
    size_t n = 0;
    if (cap == 0)
        return 0;
    buf[0] = '\0';
    for (unsigned i = 0; i < sizeof(names) / sizeof(names[0]); i++) {
        if (!(wake_mask & (1u << i)))
            continue;
        const char *s = names[i];
        size_t len = strlen(s);
        if (n + (n ? 1u : 0u) + len >= cap)
            break;
        if (n)
            buf[n++] = '+';
        memcpy(buf + n, s, len);
        n += len;
        buf[n] = '\0';
    }
    if (n == 0) {
        static const char unk[] = "unknown";
        n = sizeof(unk) - 1u < cap - 1u ? sizeof(unk) - 1u : cap - 1u;
        memcpy(buf, unk, n);
        buf[n] = '\0';
    }
    return n;
}
