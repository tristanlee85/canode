/*
 * commands.c - the shell command set. Hardware access goes through can_drv,
 * parsing through lib/ (host-tested).
 *
 * Safety (see can_drv.c): the ONLY commands that make a channel TX-capable are
 * "mode <canN> normal" (one named channel) and "selftest ext can1 can2" (both
 * named). Both print a warning. Everything else is listen-only.
 */
#include <inttypes.h>
#include <stdint.h>
#include <string.h>

#include "app.h"
#include "board.h"
#include "can_drv.h"
#include "candump.h"
#include "parse.h"
#include "power.h"
#include "selftest.h"
#include "stm32g0xx_hal.h"
#include "system.h"
#include "uart.h"
#include "usb.h"

app_t g_app;

static port_t port_of(const shell_t *sh)
{
    return (port_t)(uintptr_t)sh->ctx;
}

static const char *const k_lec_names[8] = {"none", "stuff", "form", "ack", "bit1", "bit0", "crc", "-"};

static void print_err(shell_t *sh, int rc)
{
    switch (rc) {
    case CAN_ERR_BITRATE: shell_puts(sh, "error: no valid bit timing for that bitrate\r\n"); break;
    case CAN_ERR_HAL:     shell_puts(sh, "error: FDCAN did not respond\r\n"); break;
    case CAN_ERR_MODE:    shell_puts(sh, "error: not allowed in this mode\r\n"); break;
    case CAN_ERR_FULL:    shell_puts(sh, "error: TX FIFO full\r\n"); break;
    default:              shell_puts(sh, "error: bad argument\r\n"); break;
    }
}

static void print_timing(shell_t *sh, uint8_t ch)
{
    const can_bittiming_t *bt = &can_info(ch)->bt;
    shell_printf(sh, "%s: %" PRIu32 " bit/s  (BRP %u, %u tq: TSEG1 %u, TSEG2 %u, SJW %u, sample point %u.%u%%)\r\n",
                 can_chan_name(ch), bt->bitrate, bt->brp, bt->tq_per_bit, bt->tseg1, bt->tseg2, bt->sjw,
                 bt->sp_permille / 10u, bt->sp_permille % 10u);
}

static void tx_warning(shell_t *sh, const char *chan)
{
    shell_printf(sh,
                 "WARNING: %s is now TX-CAPABLE (FDCAN normal mode). It ACKs every frame, sends error\r\n"
                 "         frames, and can transmit. Do not leave it like this on a vehicle bus.\r\n"
                 "         'mode %s monitor' returns to listen-only.\r\n",
                 chan, chan);
}

/* ---- help / status ------------------------------------------------------- */

static int cmd_help(shell_t *sh, int argc, char **argv)
{
    (void)argc;
    (void)argv;
    shell_puts(sh, "canode " CANODE_FW_VERSION " (" BOARD_NAME "). Channels are named can1 (car side) and can2 (module side).\r\n");
    shell_print_help(sh);
    return 0;
}

static void print_u64(shell_t *sh, uint64_t v)
{
    char buf[21];
    buf[fmt_u64(buf, v)] = '\0';
    shell_puts(sh, buf);
}

static int cmd_status(shell_t *sh, int argc, char **argv)
{
    (void)argc;
    (void)argv;
    uint64_t up = system_time_us();
    shell_printf(sh, "canode %s  board %s  clock %s  sysclk %" PRIu32 " MHz  fdcan %" PRIu32 " MHz\r\n",
                 CANODE_FW_VERSION, BOARD_NAME, system_clock_source(),
                 HAL_RCC_GetSysClockFreq() / 1000000u, (uint32_t)(FDCAN_KERNEL_HZ / 1000000u));
    shell_puts(sh, "uptime ");
    print_u64(sh, up / 1000000u);
    shell_printf(sh, ".%03" PRIu32 " s   time offset ", (uint32_t)(up % 1000000u) / 1000u);
    print_u64(sh, g_app.epoch_offset_us / 1000000u);
    shell_puts(sh, " s\r\n");
    if (!system_clock_is_precise())
        shell_puts(sh, "note: no crystal clock; CAN bit timing is only +-1 % accurate\r\n");

    for (uint8_t ch = 0; ch < CAN_NUM_CHANNELS; ch++) {
        const can_chan_info_t *ci = can_info(ch);
        can_bus_state_t bs;
        can_bus_state(ch, &bs);
        const char *state = ci->mode == CAN_MODE_OFF ? "-" : bs.bus_off ? "BUS-OFF"
                          : bs.error_passive ? "error-passive" : bs.warning ? "warning" : "error-active";
        shell_printf(sh, "%s: %-10s %7" PRIu32 " bit/s  %s  TEC %u REC %u  last-err %s\r\n",
                     can_chan_name(ch), can_mode_name(ci->mode), ci->bitrate, state,
                     bs.tec, bs.rec, k_lec_names[bs.last_error & 7u]);
        shell_printf(sh, "      Rs in monitor mode: %s\r\n",
                     ci->rs_listen == CAN_RS_LISTEN_HIGH ? "high (transceiver standby, hardware TX-off)"
                                                         : "low (transceiver active)");
        shell_printf(sh, "      rx %" PRIu32 "  tx %" PRIu32 "  tx-full %" PRIu32 "  hw-lost %" PRIu32 "  bus-off %" PRIu32 "\r\n",
                     ci->rx, ci->tx, ci->tx_full, ci->hw_lost, ci->bus_off);
    }
    shell_printf(sh, "rx ring dropped %" PRIu32 "   uart tx dropped %" PRIu32 "\r\n",
                 can_ring_dropped(), uart_dropped());
    shell_printf(sh, "gateway %s  rules %u  forwarded %" PRIu32 "  dropped %" PRIu32 "  tx-fail %" PRIu32 "\r\n",
                 g_app.gw_enabled ? "ON" : "off", gw_rule_count(&g_app.gw),
                 g_app.gw_forwarded, g_app.gw_dropped, g_app.gw_tx_fail);
    for (int p = 0; p < PORT_COUNT; p++) {
        uint8_t m = g_app.log_mask[p];
        shell_printf(sh, "log %-4s %s%s%s\r\n", console_name((port_t)p), m ? "" : "off",
                     (m & 1u) ? "can1 " : "", (m & 2u) ? "can2" : "");
    }
    power_inhibit_t why = power_check(&g_app.power, system_millis());
    shell_printf(sh, "sleep %s  wakes %" PRIu32 "  %s%s\r\n", g_app.power.enabled ? "on" : "off",
                 g_app.power.wakes, why == POWER_OK ? "about to sleep" : "awake: ",
                 why == POWER_OK ? "" : power_inhibit_str(why));
    return 0;
}

/* ---- sleep ------------------------------------------------------------------ */

/* "12.3 s" (ms, one decimal; "-" for "never"). */
static void print_secs(shell_t *sh, uint32_t ms)
{
    if (ms == UINT32_MAX)
        shell_puts(sh, "-");
    else
        shell_printf(sh, "%" PRIu32 ".%" PRIu32 " s", ms / 1000u, (ms % 1000u) / 100u);
}

static void sleep_status(shell_t *sh)
{
    const power_t *pm = &g_app.power;
    uint32_t now = system_millis();
    power_inhibit_t why = power_check(pm, now);

    shell_printf(sh, "sleep %s   timeout %" PRIu32 " s   bus idle ", pm->enabled ? "on" : "off", pm->timeout_ms / 1000u);
    print_secs(sh, power_bus_idle_ms(pm, now));
    shell_puts(sh, "   console idle ");
    print_secs(sh, power_console_idle_ms(pm, now));
    shell_puts(sh, "\r\n");
    if (why == POWER_OK) {
        shell_puts(sh, "      about to sleep\r\n");
    } else {
        shell_printf(sh, "      awake: %s", power_inhibit_str(why));
        uint32_t left = power_ms_until_sleep(pm, now);
        if (left != UINT32_MAX) {
            shell_puts(sh, " (sleeps in ");
            print_secs(sh, left);
            shell_puts(sh, " if it stays quiet)");
        }
        shell_puts(sh, "\r\n");
    }
    if (pm->gateway)
        shell_puts(sh, "      gateway on: it sleeps with the board and resumes on wake\r\n");
    char src[24];
    power_wake_format(pm->last_wake, src, sizeof(src));
    shell_printf(sh, "      sleeps %" PRIu32 "  wakes %" PRIu32 "  aborted %" PRIu32 "  last wake %s\r\n",
                 pm->sleeps, pm->wakes, pm->aborted, pm->have_woken ? src : "-");
    shell_printf(sh, "      wake sources: can1 (PD0, EXTI0)%s, uart key (PA3, EXTI3); RESET always works\r\n",
                 BOARD_WAKE_CAN2_COMP ? ", can2 (PB0 via COMP3)" : "");
}

static int cmd_sleep(shell_t *sh, int argc, char **argv)
{
    power_t *pm = &g_app.power;
    if (argc == 1) {
        sleep_status(sh);
        return 0;
    }
    if (argc == 2 && (strcmp(argv[1], "on") == 0 || strcmp(argv[1], "off") == 0)) {
        power_set_enabled(pm, strcmp(argv[1], "on") == 0);
        shell_printf(sh, "auto-sleep %s\r\n", argv[1]);
        return 0;
    }
    if (argc == 3 && strcmp(argv[1], "timeout") == 0) {
        uint32_t s;
        if (!parse_u32(argv[2], &s) || !power_set_timeout_s(pm, s)) {
            shell_printf(sh, "error: timeout must be %u..%u seconds\r\n", POWER_TIMEOUT_MIN_S, POWER_TIMEOUT_MAX_S);
            return -1;
        }
        shell_printf(sh, "sleep timeout %" PRIu32 " s\r\n", s);
        return 0;
    }
    if (argc == 2 && strcmp(argv[1], "now") == 0) {
        power_inhibit_t why = power_check_now(pm);
        if (why != POWER_OK) {
            shell_printf(sh, "error: not sleeping: %s.\r\n"
                             "       'mode <can1|can2> monitor' first (a running gateway may sleep).\r\n",
                         power_inhibit_str(why));
            return -1;
        }
        g_app.sleep_request = true;   /* the main loop sleeps once this reply is out */
        return 0;
    }
    shell_puts(sh, "usage: sleep                 status: idle times, why awake, wake count\r\n"
                   "       sleep on|off          auto-sleep when both buses are idle (default on)\r\n"
                   "       sleep timeout <s>     bus/console idle time before sleeping (default 60)\r\n"
                   "       sleep now             sleep immediately (refused during manual transmit)\r\n"
                   "       A running gateway sleeps too, and resumes on wake.\r\n");
    return -1;
}

/* ---- channel configuration ------------------------------------------------ */

static int cmd_mode(shell_t *sh, int argc, char **argv)
{
    if (argc != 3) {
        shell_puts(sh, "usage: mode <can1|can2|all> <off|monitor>   or   mode <can1|can2> normal\r\n");
        return -1;
    }
    if (strcmp(argv[2], "normal") == 0) {
        /* TX-capable: one explicitly named channel only, never "all". */
        uint8_t ch;
        if (!parse_channel(argv[1], &ch)) {
            shell_puts(sh, "error: normal (TX) mode needs one named channel: can1 or can2\r\n");
            return -1;
        }
        int rc = can_enable_tx(ch, can_info(ch)->bitrate);
        if (rc != CAN_OK) {
            print_err(sh, rc);
            return -1;
        }
        tx_warning(sh, can_chan_name(ch));
        if (!BOARD_HAS_CAN_PHY)
            shell_puts(sh, "note: this board has no CAN transceivers\r\n");
        return 0;
    }

    can_mode_t mode;
    if (strcmp(argv[2], "off") == 0) {
        mode = CAN_MODE_OFF;
    } else if (strcmp(argv[2], "monitor") == 0) {
        mode = CAN_MODE_MONITOR;
    } else {
        shell_puts(sh, "error: mode must be off, monitor or normal\r\n");
        return -1;
    }
    uint8_t mask;
    if (!parse_channel_mask(argv[1], &mask)) {
        shell_puts(sh, "error: channel must be can1, can2 or all\r\n");
        return -1;
    }
    for (uint8_t ch = 0; ch < CAN_NUM_CHANNELS; ch++) {
        if (!(mask & (1u << ch)))
            continue;
        int rc = can_set_listen_mode(ch, mode, can_info(ch)->bitrate);
        if (rc != CAN_OK) {
            print_err(sh, rc);
            return -1;
        }
        shell_printf(sh, "%s: %s\r\n", can_chan_name(ch), can_mode_name(mode));
    }
    return 0;
}

static int cmd_bitrate(shell_t *sh, int argc, char **argv)
{
    uint8_t mask;
    uint32_t rate;
    if (argc == 1) {
        for (uint8_t ch = 0; ch < CAN_NUM_CHANNELS; ch++)
            print_timing(sh, ch);
        return 0;
    }
    if (argc != 3 || !parse_channel_mask(argv[1], &mask) || !parse_bitrate(argv[2], &rate)) {
        shell_puts(sh, "usage: bitrate [<can1|can2|all> <rate>]   e.g. bitrate can1 500k\r\n");
        return -1;
    }
    for (uint8_t ch = 0; ch < CAN_NUM_CHANNELS; ch++) {
        if (!(mask & (1u << ch)))
            continue;
        can_mode_t prev = can_info(ch)->mode;
        /* Safety rule 4: a bitrate change never leaves the channel TX-capable. */
        can_mode_t next = prev == CAN_MODE_OFF ? CAN_MODE_OFF : CAN_MODE_MONITOR;
        int rc = can_set_listen_mode(ch, next, rate);
        if (rc != CAN_OK) {
            print_err(sh, rc);
            return -1;
        }
        print_timing(sh, ch);
        if (prev == CAN_MODE_NORMAL)
            shell_printf(sh, "note: %s is back in monitor (listen-only) mode\r\n", can_chan_name(ch));
    }
    return 0;
}

static int cmd_rslisten(shell_t *sh, int argc, char **argv)
{
    uint8_t mask;
    can_rs_listen_t v;
    if (argc == 3 && parse_channel_mask(argv[1], &mask) &&
        (strcmp(argv[2], "high") == 0 || strcmp(argv[2], "low") == 0)) {
        v = strcmp(argv[2], "high") == 0 ? CAN_RS_LISTEN_HIGH : CAN_RS_LISTEN_LOW;
        for (uint8_t ch = 0; ch < CAN_NUM_CHANNELS; ch++) {
            if (!(mask & (1u << ch)))
                continue;
            (void)can_set_rs_listen(ch, v);
            shell_printf(sh, "%s: Rs %s while monitoring%s\r\n", can_chan_name(ch), argv[2],
                         can_info(ch)->mode == CAN_MODE_NORMAL ? " (now in normal mode: Rs stays low)" : "");
        }
        if (v == CAN_RS_LISTEN_HIGH)
            shell_puts(sh, "note: Rs-high reception is not bench-verified yet; check rx/hw-lost in 'status'\r\n");
        return 0;
    }
    shell_puts(sh, "usage: rslisten <can1|can2|all> <high|low>\r\n"
                   "       high = transceiver standby while monitoring (hardware TX-off)\r\n"
                   "       low  = transceiver active while monitoring (default)\r\n");
    return -1;
}

/* ---- capture -------------------------------------------------------------- */

static int cmd_log(shell_t *sh, int argc, char **argv)
{
    port_t p = port_of(sh);
    uint8_t mask = 3u;
    if (argc == 3 && !parse_channel_mask(argv[2], &mask))
        argc = 0;   /* force the usage message */
    if (argc >= 2 && strcmp(argv[1], "on") == 0) {
        g_app.log_mask[p] = mask;
        return 0;   /* no reply: the next line on this port is candump data */
    }
    if (argc == 2 && strcmp(argv[1], "off") == 0) {
        g_app.log_mask[p] = 0;
        return 0;
    }
    shell_puts(sh, "usage: log <on [can1|can2|all] | off>   (streams candump lines to this port)\r\n");
    return -1;
}

static int cmd_time(shell_t *sh, int argc, char **argv)
{
    uint64_t epoch;
    if (argc == 2 && parse_epoch_us(argv[1], &epoch)) {
        g_app.epoch_offset_us = epoch - system_time_us();
        return 0;
    }
    if (argc == 1) {
        shell_puts(sh, "time ");
        uint64_t now = system_time_us() + g_app.epoch_offset_us;
        print_u64(sh, now / 1000000u);
        shell_printf(sh, ".%06" PRIu32 "\r\n", (uint32_t)(now % 1000000u));
        return 0;
    }
    shell_puts(sh, "usage: time [unix_seconds[.fraction]]   e.g. time 1700000000.5 (from: date +%s)\r\n");
    return -1;
}

static int cmd_echo(shell_t *sh, int argc, char **argv)
{
    if (argc == 2 && (strcmp(argv[1], "on") == 0 || strcmp(argv[1], "off") == 0)) {
        sh->echo = strcmp(argv[1], "on") == 0;
        return 0;
    }
    shell_puts(sh, "usage: echo <on|off>   (off = no echo, no prompt: for scripts)\r\n");
    return -1;
}

/* ---- transmit ------------------------------------------------------------- */

static int cmd_send(shell_t *sh, int argc, char **argv)
{
    uint8_t ch;
    can_frame_t f;
    if (argc != 3 || !parse_channel(argv[1], &ch) || !candump_parse_frame(argv[2], &f)) {
        shell_puts(sh, "usage: send <can1|can2> <id>#<data>   e.g. send can2 123#DEADBEEF, 18DAF110#0211, 7DF#R\r\n");
        return -1;
    }
    if (can_info(ch)->mode != CAN_MODE_NORMAL) {
        shell_printf(sh, "error: %s is listen-only. Use 'mode %s normal' first (bench/explicit use only).\r\n",
                     can_chan_name(ch), can_chan_name(ch));
        return -1;
    }
    int rc = can_send(ch, &f);
    if (rc != CAN_OK) {
        print_err(sh, rc);
        return -1;
    }
    return 0;
}

static int cmd_selftest(shell_t *sh, int argc, char **argv)
{
    if (argc == 1 || (argc == 2 && strcmp(argv[1], "int") == 0))
        return selftest_internal(sh) ? -1 : 0;

    if (argc == 4 && strcmp(argv[1], "ext") == 0 && strcmp(argv[2], "can1") == 0 && strcmp(argv[3], "can2") == 0) {
        if (!BOARD_HAS_CAN_PHY) {
            shell_puts(sh, "error: this board has no CAN transceivers; use 'selftest int'\r\n");
            return -1;
        }
        shell_puts(sh, "WARNING: external self-test TRANSMITS on can1 and can2. Bench only: JP1 and JP2\r\n"
                       "         bridged, can1 wired to can2, NOT connected to a vehicle.\r\n");
        return selftest_external(sh) ? -1 : 0;
    }
    shell_puts(sh, "usage: selftest [int]            internal loopback, bus untouched\r\n"
                   "       selftest ext can1 can2    bench wire test, TRANSMITS on both channels\r\n");
    return -1;
}

/* ---- gateway -------------------------------------------------------------- */

void app_gateway_stop(const char *why)
{
    if (!g_app.gw_enabled)
        return;
    g_app.gw_enabled = false;
    console_broadcast("gateway: OFF (%s)\r\n", why);
}

static void gw_list(shell_t *sh)
{
    unsigned n = gw_rule_count(&g_app.gw);
    if (n == 0)
        shell_puts(sh, "no rules: every frame is forwarded unchanged\r\n");
    for (unsigned i = 0; i < n; i++) {
        char buf[80];
        gw_rule_format(&g_app.gw.rules[i], buf, sizeof(buf));
        shell_printf(sh, "%2u: %-48s hits %" PRIu32 "\r\n", i, buf, g_app.gw.rules[i].hits);
    }
}

static int cmd_gw(shell_t *sh, int argc, char **argv)
{
    const char *sub = argc >= 2 ? argv[1] : "status";

    if (strcmp(sub, "status") == 0 || strcmp(sub, "list") == 0) {
        shell_printf(sh, "gateway %s\r\n", g_app.gw_enabled ? "ON" : "off");
        gw_list(sh);
        return 0;
    }
    if (strcmp(sub, "on") == 0) {
        /* Forwarding transmits, so both channels must already be in normal mode,
         * which the user can only do with one explicit command per channel. */
        if (can_info(0)->mode != CAN_MODE_NORMAL || can_info(1)->mode != CAN_MODE_NORMAL) {
            shell_puts(sh, "error: the gateway transmits, so both channels must be in normal mode first:\r\n"
                           "       'mode can1 normal' and 'mode can2 normal'\r\n");
            return -1;
        }
        g_app.gw_enabled = true;
        shell_puts(sh, "WARNING: gateway ON: frames from can1 are re-transmitted on can2 and vice versa.\r\n");
        return 0;
    }
    if (strcmp(sub, "off") == 0) {
        g_app.gw_enabled = false;
        shell_puts(sh, "gateway off\r\n");
        return 0;
    }
    if (strcmp(sub, "add") == 0) {
        gw_rule_t r;
        const char *err = "?";
        if (!gw_rule_parse(argc - 2, argv + 2, &r, &err)) {
            shell_printf(sh, "error: %s\r\n", err);
            return -1;
        }
        int idx = gw_rule_add(&g_app.gw, &r);
        if (idx < 0) {
            shell_puts(sh, "error: rule table full\r\n");
            return -1;
        }
        shell_printf(sh, "rule %d added\r\n", idx);
        return 0;
    }
    if (strcmp(sub, "del") == 0) {
        uint32_t idx;
        if (argc != 3 || !parse_u32(argv[2], &idx) || !gw_rule_del(&g_app.gw, idx)) {
            shell_puts(sh, "usage: gw del <rule number>   (see 'gw list')\r\n");
            return -1;
        }
        return 0;
    }
    if (strcmp(sub, "clear") == 0) {
        gw_init(&g_app.gw);
        return 0;
    }
    shell_puts(sh, "usage: gw [status|on|off|list|clear|del <n>|add <from> <match> <action> [id=..] [data=..]]\r\n"
                   "       e.g. gw add can1 3B3 rewrite data=....0.   gw add any 7DF drop\r\n");
    return -1;
}

/* ---- system --------------------------------------------------------------- */

static int cmd_reset(shell_t *sh, int argc, char **argv)
{
    (void)sh;
    (void)argc;
    (void)argv;
    system_reboot();
}

static int cmd_dfu(shell_t *sh, int argc, char **argv)
{
    (void)argc;
    (void)argv;
    shell_puts(sh, "rebooting into the ROM USB DFU bootloader (dfu-util -l should list it)\r\n");
    uint32_t t = system_millis();
    while (system_millis() - t < 100u)
        usb_poll();   /* let the message drain (it spans two USB packets) */
    system_reboot_to_dfu();
}

static const shell_cmd_t k_cmds[] = {
    {"help",     "",                                   "this list", cmd_help},
    {"status",   "",                                   "firmware, clocks, channel modes, counters, bus errors", cmd_status},
    {"mode",     "<can1|can2|all> <off|monitor>",      "off, or listen-only bus monitoring (the default)", cmd_mode},
    {"mode",     "<can1|can2> normal",                 "TX-CAPABLE: ACKs and transmits. One named channel only", cmd_mode},
    {"bitrate",  "[<can1|can2|all> <rate>]",           "show or set bitrate (125k 250k 500k 1M ...); drops TX mode", cmd_bitrate},
    {"rslisten", "<can1|can2|all> <high|low>",       "transceiver Rs while monitoring: high = hardware TX-off", cmd_rslisten},
    {"log",      "<on [can1|can2|all] | off>",         "stream received frames to this port in candump format", cmd_log},
    {"time",     "[unix_seconds[.frac]]",              "show or set the wall clock used for log timestamps", cmd_time},
    {"send",     "<can1|can2> <id>#<data>",            "transmit one frame (channel must be in normal mode)", cmd_send},
    {"selftest", "[int | ext can1 can2]",              "loopback tests at 125k-1M; 'ext' TRANSMITS (bench only)", cmd_selftest},
    {"gw",       "[on|off|list|add ...|del n|clear]",  "can1<->can2 gateway rules (off by default)", cmd_gw},
    {"sleep",    "[on|off|timeout <s>|now]",           "low-power Stop mode when the buses go quiet; wakes on CAN", cmd_sleep},
    {"echo",     "<on|off>",                           "local echo and prompt (off for scripts)", cmd_echo},
    {"reset",    "",                                   "reboot", cmd_reset},
    {"dfu",      "",                                   "reboot into the ROM USB DFU bootloader", cmd_dfu},
};

/* No prompt while streaming, so candump lines always start at column 0. */
static bool prompt_ok(shell_t *sh)
{
    return g_app.log_mask[port_of(sh)] == 0;
}

static void shell_write(void *ctx, const char *s, size_t n)
{
    console_write((port_t)(uintptr_t)ctx, s, n);
}

void commands_init(void)
{
    gw_init(&g_app.gw);
    for (int p = 0; p < PORT_COUNT; p++) {
        shell_init(&g_app.shell[p], k_cmds, sizeof(k_cmds) / sizeof(k_cmds[0]), shell_write, (void *)(uintptr_t)p);
        g_app.shell[p].prompt_ok = prompt_ok;
    }
}
