#include "selftest.h"

#include <string.h>

#include "app.h"
#include "can_drv.h"
#include "system.h"
#include "usb.h"

static const uint32_t k_rates[] = {125000u, 250000u, 500000u, 1000000u};
#define NRATES (sizeof(k_rates) / sizeof(k_rates[0]))
#define WAIT_MS 50u   /* a frame takes ~1 ms at 125k; generous margin */

typedef struct {
    can_mode_t mode;
    uint32_t   bitrate;
} saved_t;

static void save(saved_t s[CAN_NUM_CHANNELS])
{
    for (uint8_t ch = 0; ch < CAN_NUM_CHANNELS; ch++) {
        s[ch].mode = can_info(ch)->mode;
        s[ch].bitrate = can_info(ch)->bitrate;
    }
}

/* Safety rule 4: a self-test never leaves a channel able to transmit. A channel
 * that was off stays off; anything else comes back in listen-only monitor mode. */
static void restore(shell_t *sh, const saved_t s[CAN_NUM_CHANNELS])
{
    for (uint8_t ch = 0; ch < CAN_NUM_CHANNELS; ch++) {
        can_mode_t m = s[ch].mode == CAN_MODE_OFF ? CAN_MODE_OFF : CAN_MODE_MONITOR;
        (void)can_set_listen_mode(ch, m, s[ch].bitrate);
        if (s[ch].mode == CAN_MODE_NORMAL)
            shell_printf(sh, "note: %s was in normal (TX) mode; it is now monitor. "
                             "Re-enable TX explicitly if you need it.\r\n", can_chan_name(ch));
    }
    can_flush_rx();
}

static can_frame_t make_frame(uint8_t ch, unsigned rate_idx, bool ext)
{
    can_frame_t f;
    memset(&f, 0, sizeof(f));
    f.id = ext ? (0x18DAF100u | ch) : (0x5A0u | ch);
    f.flags = ext ? CAN_FLAG_EXT : 0u;
    f.len = 8;
    static const uint8_t pattern[8] = {0x00, 0xFF, 0x55, 0xAA, 0x01, 0x80, 0x00, 0x00};
    memcpy(f.data, pattern, 8);
    f.data[6] = ch;
    f.data[7] = (uint8_t)rate_idx;
    return f;
}

static bool same_frame(const can_frame_t *a, const can_frame_t *b)
{
    return a->id == b->id && a->flags == b->flags && a->len == b->len &&
           memcmp(a->data, b->data, a->len) == 0;
}

/* Wait for `want` to arrive on channel rx_ch. Keeps USB alive meanwhile. */
static bool wait_for(uint8_t rx_ch, const can_frame_t *want)
{
    uint32_t start = system_millis();
    while (system_millis() - start < WAIT_MS) {
        usb_poll();
        can_frame_t f;
        while (can_pop(&f)) {
            if (f.chan == rx_ch && same_frame(&f, want))
                return true;
        }
    }
    return false;
}

static bool send_and_expect(uint8_t tx_ch, uint8_t rx_ch, const can_frame_t *f)
{
    if (can_send(tx_ch, f) != CAN_OK)
        return false;
    return wait_for(rx_ch, f);
}

static const char *rate_str(uint32_t r)
{
    switch (r) {
    case 125000u:  return "125k";
    case 250000u:  return "250k";
    case 500000u:  return "500k";
    case 1000000u: return "1M";
    default:       return "?";
    }
}

int selftest_internal(shell_t *sh)
{
    saved_t saved[CAN_NUM_CHANNELS];
    save(saved);
    if (g_app.gw_enabled)
        app_gateway_stop("self-test");

    shell_puts(sh, "selftest int: FDCAN internal loopback (bus untouched, transceivers in standby)\r\n");
    int fails = 0;
    for (unsigned r = 0; r < NRATES; r++) {
        for (uint8_t ch = 0; ch < CAN_NUM_CHANNELS; ch++) {
            bool ok = can_set_loopback(ch, k_rates[r]) == CAN_OK;
            can_flush_rx();
            can_frame_t std = make_frame(ch, r, false);
            can_frame_t ext = make_frame(ch, r, true);
            ok = ok && send_and_expect(ch, ch, &std);
            ok = ok && send_and_expect(ch, ch, &ext);
            (void)can_set_listen_mode(ch, CAN_MODE_OFF, k_rates[r]);
            shell_printf(sh, "  %s %-4s %s\r\n", can_chan_name(ch), rate_str(k_rates[r]), ok ? "pass" : "FAIL");
            if (!ok)
                fails++;
        }
    }
    restore(sh, saved);
    shell_printf(sh, "selftest int: %s (%d failure%s)\r\n", fails ? "FAILED" : "passed", fails, fails == 1 ? "" : "s");
    return fails;
}

int selftest_external(shell_t *sh)
{
    saved_t saved[CAN_NUM_CHANNELS];
    save(saved);
    if (g_app.gw_enabled)
        app_gateway_stop("self-test");

    shell_puts(sh, "selftest ext: can1 <-> can2 through the transceivers. BOTH CHANNELS TRANSMIT.\r\n");
    int fails = 0;
    for (unsigned r = 0; r < NRATES; r++) {
        /* The user named both channels in the command: see safety rule 3. */
        bool cfg = can_enable_tx(0, k_rates[r]) == CAN_OK && can_enable_tx(1, k_rates[r]) == CAN_OK;
        can_flush_rx();
        can_frame_t a = make_frame(0, r, false);
        can_frame_t b = make_frame(1, r, true);
        bool ok12 = cfg && send_and_expect(0, 1, &a);
        bool ok21 = cfg && send_and_expect(1, 0, &b);
        shell_printf(sh, "  %-4s can1->can2 %s   can2->can1 %s\r\n", rate_str(k_rates[r]),
                     ok12 ? "pass" : "FAIL", ok21 ? "pass" : "FAIL");
        fails += !ok12 + !ok21;
    }
    restore(sh, saved);
    shell_printf(sh, "selftest ext: %s (%d failure%s)\r\n", fails ? "FAILED" : "passed", fails, fails == 1 ? "" : "s");
    if (fails)
        shell_puts(sh, "  check: JP1 and JP2 bridged? CAN1_H-CAN2_H and CAN1_L-CAN2_L wired? Crystal OK ('status')?\r\n");
    return fails;
}
