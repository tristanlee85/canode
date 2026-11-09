#include "test.h"
#include "power.h"

#define T  60000u   /* default timeout, ms */

/* A board that boots, sits on a quiet bus with nothing connected. */
static void fresh(power_t *p, uint32_t now)
{
    power_init(p, now, true, 60u);
    power_set_usb(p, false, now);
    power_set_channels(p, 3u, false, false);
}

static void test_basic_timeout(void)
{
    power_t p;
    fresh(&p, 1000u);
    CHECK_EQ(p.timeout_ms, T);

    /* Stays up for one full timeout after boot. */
    CHECK_EQ(power_check(&p, 1000u), POWER_INHIBIT_CONSOLE);
    CHECK_EQ(power_check(&p, 1000u + T - 1u), POWER_INHIBIT_CONSOLE);
    CHECK_EQ(power_ms_until_sleep(&p, 1000u + T - 1u), 1);
    CHECK_EQ(power_check(&p, 1000u + T), POWER_OK);
    CHECK_EQ(power_ms_until_sleep(&p, 1000u + T), 0);

    /* A frame on either channel restarts the bus timer. */
    fresh(&p, 0u);
    power_frame(&p, 1u, 50000u);
    CHECK_EQ(power_check(&p, 70000u), POWER_INHIBIT_BUS);
    CHECK_EQ(power_bus_idle_ms(&p, 70000u), 20000);
    CHECK_EQ(power_ms_until_sleep(&p, 70000u), 40000);
    CHECK_EQ(power_check(&p, 50000u + T), POWER_OK);
    power_frame(&p, 0u, 100000u);
    CHECK_EQ(power_check(&p, 100000u + T - 1u), POWER_INHIBIT_BUS);
    CHECK_EQ(power_check(&p, 100000u + T), POWER_OK);

    /* Out-of-range channel numbers are ignored. */
    power_frame(&p, 7u, 200000u);
    CHECK_EQ(power_check(&p, 200000u), POWER_OK);

    /* Console input holds it up too. */
    fresh(&p, 0u);
    power_console(&p, 90000u);
    CHECK_EQ(power_check(&p, 100000u), POWER_INHIBIT_CONSOLE);
    CHECK_EQ(power_check(&p, 90000u + T), POWER_OK);
}

static void test_inhibits(void)
{
    power_t p;
    uint32_t late = 10u * T;

    /* sleep off */
    fresh(&p, 0u);
    power_set_enabled(&p, false);
    CHECK_EQ(power_check(&p, late), POWER_INHIBIT_DISABLED);
    CHECK_EQ(power_ms_until_sleep(&p, late), UINT32_MAX);
    power_set_enabled(&p, true);
    CHECK_EQ(power_check(&p, late), POWER_OK);

    /* USB mounted: never sleeps; unplugging gives a full timeout. */
    fresh(&p, 0u);
    power_set_usb(&p, true, 1000u);
    CHECK_EQ(power_check(&p, late), POWER_INHIBIT_USB);
    power_set_usb(&p, true, late);   /* no change: does not touch the timer */
    power_set_usb(&p, false, late);
    CHECK_EQ(power_check(&p, late + 1u), POWER_INHIBIT_CONSOLE);
    CHECK_EQ(power_check(&p, late + T), POWER_OK);

    /* No channel listening. */
    fresh(&p, 0u);
    power_set_channels(&p, 0u, false, false);
    CHECK_EQ(power_check(&p, late), POWER_INHIBIT_NO_LISTENER);
    power_set_channels(&p, 2u, false, false);   /* one is enough */
    CHECK_EQ(power_check(&p, late), POWER_OK);

    /* Order: the more fundamental reason is reported first. */
    fresh(&p, 0u);
    power_set_usb(&p, true, 0u);
    power_set_channels(&p, 0u, true, false);
    power_set_enabled(&p, false);
    CHECK_EQ(power_check(&p, 0u), POWER_INHIBIT_DISABLED);
    power_set_enabled(&p, true);
    CHECK_EQ(power_check(&p, 0u), POWER_INHIBIT_TX_NOW);
}

static void test_tx_latch(void)
{
    power_t p;
    uint32_t late = 10u * T;

    /* TX-capable right now: no auto-sleep, and "sleep now" is refused. */
    fresh(&p, 0u);
    power_set_channels(&p, 1u, true, true);
    CHECK_EQ(power_check(&p, late), POWER_INHIBIT_TX_NOW);
    CHECK_EQ(power_check_now(&p), POWER_INHIBIT_TX_NOW);

    /* Back to monitor: the session latch still blocks auto-sleep... */
    power_set_channels(&p, 3u, false, true);
    CHECK_EQ(power_check(&p, late), POWER_INHIBIT_TX_SESSION);
    /* ...even if the driver's flag were somehow cleared... */
    power_set_channels(&p, 3u, false, false);
    CHECK_EQ(power_check(&p, late), POWER_INHIBIT_TX_SESSION);
    CHECK_EQ(power_ms_until_sleep(&p, late), UINT32_MAX);
    /* ...but an explicit "sleep now" is allowed once nothing can transmit. */
    CHECK_EQ(power_check_now(&p), POWER_OK);

    /* A transmit that started and ended between two polls (e.g. selftest ext)
     * is caught through the driver's tx_ever flag alone. */
    fresh(&p, 0u);
    power_set_channels(&p, 3u, false, true);
    CHECK_EQ(power_check(&p, late), POWER_INHIBIT_TX_SESSION);

    /* Only a reboot (power_init) clears the latch. */
    power_init(&p, 0u, true, 60u);
    CHECK(!p.tx_session);

    /* "sleep now" ignores the other inhibits. */
    fresh(&p, 0u);
    power_set_usb(&p, true, 0u);
    power_set_enabled(&p, false);
    CHECK_EQ(power_check_now(&p), POWER_OK);
}

static void test_wake_and_stats(void)
{
    power_t p;
    fresh(&p, 0u);
    CHECK(!p.have_woken);
    power_on_sleep(&p);
    power_on_wake(&p, POWER_WAKE_CAN2, 5u * T);
    CHECK_EQ(p.sleeps, 1);
    CHECK_EQ(p.wakes, 1);
    CHECK_EQ(p.last_wake, POWER_WAKE_CAN2);
    CHECK(p.have_woken);
    /* A wake counts as activity: awake for a full timeout even if the frame
     * that woke us was lost. */
    CHECK_EQ(power_check(&p, 5u * T + 1u), POWER_INHIBIT_CONSOLE);
    CHECK_EQ(power_check(&p, 6u * T), POWER_OK);

    power_on_abort(&p, 7u * T);
    CHECK_EQ(p.aborted, 1);
    CHECK(power_check(&p, 7u * T + 1u) != POWER_OK);
    CHECK_EQ(power_check(&p, 8u * T), POWER_OK);
}

static void test_timeout_setting(void)
{
    power_t p;
    fresh(&p, 0u);
    CHECK(!power_set_timeout_s(&p, 0u));
    CHECK(!power_set_timeout_s(&p, POWER_TIMEOUT_MIN_S - 1u));
    CHECK(!power_set_timeout_s(&p, POWER_TIMEOUT_MAX_S + 1u));
    CHECK_EQ(p.timeout_ms, T);   /* unchanged after a refusal */
    CHECK(power_set_timeout_s(&p, POWER_TIMEOUT_MIN_S));
    CHECK_EQ(p.timeout_ms, POWER_TIMEOUT_MIN_S * 1000u);
    CHECK(power_set_timeout_s(&p, POWER_TIMEOUT_MAX_S));
    CHECK_EQ(p.timeout_ms, POWER_TIMEOUT_MAX_S * 1000u);

    /* power_init clamps instead of refusing. */
    power_init(&p, 0u, true, 1u);
    CHECK_EQ(p.timeout_ms, POWER_TIMEOUT_MIN_S * 1000u);
    power_init(&p, 0u, true, 1000000u);
    CHECK_EQ(p.timeout_ms, POWER_TIMEOUT_MAX_S * 1000u);
    power_init(&p, 0u, false, 60u);
    CHECK(!p.enabled);
}

static void test_wrap(void)
{
    power_t p;
    /* Millisecond counter wraps (49.7 days) between events. */
    uint32_t t0 = 0xFFFFFFFFu - 10000u;
    fresh(&p, t0);
    power_frame(&p, 0u, t0 + 5000u);
    CHECK_EQ(power_check(&p, t0 + 5000u + T - 1u), POWER_INHIBIT_BUS);   /* past the wrap */
    CHECK_EQ(power_check(&p, t0 + 5000u + T), POWER_OK);

    /* Inhibited for 40+ days (USB connected) with power_tick running: old
     * timestamps saturate instead of wrapping round to look recent. */
    fresh(&p, 0u);
    power_set_usb(&p, true, 0u);
    uint32_t day = 86400000u;
    for (uint32_t t = 0; t <= 60u * day; t += day / 4u)
        power_tick(&p, t);
    uint32_t now = 60u * day;
    CHECK(power_bus_idle_ms(&p, now) >= T);
    CHECK(power_console_idle_ms(&p, now) >= T);
    p.usb_mounted = false;   /* bypass the unplug grace period for this check */
    CHECK_EQ(power_check(&p, now), POWER_OK);
}

static void test_strings(void)
{
    char buf[32];
    CHECK_EQ(power_wake_format(POWER_WAKE_CAN1, buf, sizeof(buf)), 4);
    CHECK_STR(buf, "can1");
    power_wake_format(POWER_WAKE_CAN2 | POWER_WAKE_UART, buf, sizeof(buf));
    CHECK_STR(buf, "can2+uart");
    power_wake_format(POWER_WAKE_CAN1 | POWER_WAKE_CAN2 | POWER_WAKE_UART, buf, sizeof(buf));
    CHECK_STR(buf, "can1+can2+uart");
    power_wake_format(0u, buf, sizeof(buf));
    CHECK_STR(buf, "unknown");
    /* Truncation stays NUL-terminated and drops whole names. */
    power_wake_format(POWER_WAKE_CAN1 | POWER_WAKE_CAN2, buf, 8u);
    CHECK_STR(buf, "can1");
    power_wake_format(0u, buf, 4u);
    CHECK_STR(buf, "unk");
    CHECK_EQ(power_wake_format(0u, buf, 0u), 0);

    CHECK_STR(power_inhibit_str(POWER_OK), "none");
    CHECK_STR(power_inhibit_str(POWER_INHIBIT_BUS), "bus active");
    CHECK(strstr(power_inhibit_str(POWER_INHIBIT_TX_SESSION), "reboot") != NULL);
}

void test_power(void)
{
    test_basic_timeout();
    test_inhibits();
    test_tx_latch();
    test_wake_and_stats();
    test_timeout_setting();
    test_wrap();
    test_strings();
}
