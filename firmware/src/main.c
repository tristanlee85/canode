/*
 * main.c - canode firmware entry point and main loop.
 *
 * Bare metal, no RTOS: interrupts only move bytes/frames into buffers, and
 * this loop does everything else (USB stack, shells, logging, gateway, LEDs).
 */
#include <stdint.h>

#include "app.h"
#include "board.h"
#include "can_drv.h"
#include "candump.h"
#include "console.h"
#include "sleep.h"
#include "stm32g0xx_hal.h"
#include "system.h"
#include "uart.h"
#include "usb.h"

static void leds_init(void)
{
    __HAL_RCC_GPIOA_CLK_ENABLE();
    GPIO_InitTypeDef gpio = {0};
    gpio.Mode = GPIO_MODE_OUTPUT_PP;
    gpio.Pull = GPIO_NOPULL;
    gpio.Speed = GPIO_SPEED_FREQ_LOW;
    gpio.Pin = BOARD_LED1_PIN;
    HAL_GPIO_Init(BOARD_LED1_PORT, &gpio);
#ifdef BOARD_LED2_PORT
    gpio.Pin = BOARD_LED2_PIN;
    HAL_GPIO_Init(BOARD_LED2_PORT, &gpio);
#endif
}

static void led_set(GPIO_TypeDef *port, uint16_t pin, bool on)
{
    HAL_GPIO_WritePin(port, pin, on ? BOARD_LED_ON : (BOARD_LED_ON == GPIO_PIN_SET ? GPIO_PIN_RESET : GPIO_PIN_SET));
}

/* LED1: heartbeat (slow blink, or fast when a TX-capable mode is active).
 * LED2: flickers on received CAN traffic. */
static void leds_update(bool traffic)
{
    static uint32_t last_rx_ms;
    uint32_t now = system_millis();
    bool tx_mode = can_info(0)->mode == CAN_MODE_NORMAL || can_info(1)->mode == CAN_MODE_NORMAL;
    uint32_t period = tx_mode ? 200u : 1000u;
    led_set(BOARD_LED1_PORT, BOARD_LED1_PIN, (now % period) < period / 2u);
#ifdef BOARD_LED2_PORT
    if (traffic)
        last_rx_ms = now;
    led_set(BOARD_LED2_PORT, BOARD_LED2_PIN, now - last_rx_ms < 30u);
#else
    (void)traffic;
    (void)last_rx_ms;
#endif
}

static void print_banner(port_t p)
{
    shell_t *sh = &g_app.shell[p];
    shell_puts(sh, "\r\ncanode " CANODE_FW_VERSION " (" BOARD_NAME ") - type 'help'\r\n");
    shell_printf(sh, "clock: %s. can1/can2: listen-only monitor mode. Nothing is transmitted unless you ask.\r\n",
                 system_clock_source());
    shell_prompt(sh);
}

/* One received frame: stream it to every port that asked, then gateway it. */
static void handle_frame(can_frame_t *f)
{
    char line[CANDUMP_LINE_MAX];
    size_t n = 0;
    for (int p = 0; p < PORT_COUNT; p++) {
        if (!(g_app.log_mask[p] & (1u << f->chan)))
            continue;
        if (n == 0)
            n = candump_format(line, sizeof(line), f, g_app.epoch_offset_us);
        console_write((port_t)p, line, n);
    }

    if (!g_app.gw_enabled)
        return;
    uint8_t out = f->chan ^ 1u;
    if (!gw_process(&g_app.gw, f)) {
        g_app.gw_dropped++;
        return;
    }
    if (can_send(out, f) == CAN_OK)
        g_app.gw_forwarded++;
    else
        g_app.gw_tx_fail++;
}

/* Feed the sleep policy (lib/power.h) and sleep if it says so. */
static void power_update(void)
{
    uint32_t now = system_millis();
    uint8_t wake = 0;
    bool gw = g_app.gw_enabled;
    bool tx_manual = false;
    for (uint8_t ch = 0; ch < CAN_NUM_CHANNELS; ch++) {
        can_mode_t m = can_info(ch)->mode;
        /* A gateway channel (normal mode) can wake the board and resumes
         * after the wake; normal mode without the gateway is a manual
         * transmit session and keeps the board awake. */
        if (m == CAN_MODE_MONITOR || (gw && m == CAN_MODE_NORMAL))
            wake |= (uint8_t)(1u << ch);
        if (m == CAN_MODE_NORMAL && !gw)
            tx_manual = true;
    }
    power_set_usb(&g_app.power, usb_mounted(), now);
    power_set_channels(&g_app.power, wake, tx_manual, gw);
    power_tick(&g_app.power, now);

    if (g_app.sleep_request) {
        g_app.sleep_request = false;
        /* Re-check: the command already refused this, but state can change. */
        if (power_check_now(&g_app.power) == POWER_OK)
            sleep_run(true);
        return;
    }
    if (power_check(&g_app.power, now) == POWER_OK)
        sleep_run(false);
}

int main(void)
{
    system_early_init();      /* may jump to the ROM bootloader; nothing is set up yet */
    HAL_Init();               /* SysTick 1 ms, flash prefetch */
    system_clock_init();
    system_timebase_init();
    leds_init();
    can_init();               /* Rs -> standby first, then both channels -> monitor */
    uart_init();
    commands_init();
    usb_init();
    sleep_init();
    power_init(&g_app.power, system_millis(), BOARD_SLEEP_DEFAULT_ENABLED, BOARD_SLEEP_DEFAULT_TIMEOUT_S);

    print_banner(PORT_UART);

    for (;;) {
        usb_poll();
        if (usb_take_open_event())
            print_banner(PORT_USB);

        for (int p = 0; p < PORT_COUNT; p++) {
            int c;
            /* Bounded per pass so a pasted script can't starve CAN processing. */
            for (int i = 0; i < 64 && (c = console_getc((port_t)p)) >= 0; i++) {
                shell_input(&g_app.shell[p], (char)c);
                power_console(&g_app.power, system_millis());
            }
        }

        uint8_t bus_off = can_poll();
        for (uint8_t ch = 0; ch < CAN_NUM_CHANNELS; ch++) {
            if (bus_off & (1u << ch))
                console_broadcast("\r\nWARNING: %s went BUS-OFF; it is now in monitor (listen-only) mode.\r\n",
                                  can_chan_name(ch));
        }
        /* Gateway needs both sides able to transmit; anything else turns it off. */
        if (g_app.gw_enabled && (can_info(0)->mode != CAN_MODE_NORMAL || can_info(1)->mode != CAN_MODE_NORMAL))
            app_gateway_stop("a channel left normal mode");

        bool traffic = false;
        can_frame_t f;
        for (int i = 0; i < 32 && can_pop(&f); i++) {
            power_frame(&g_app.power, f.chan, system_millis());
            handle_frame(&f);
            traffic = true;
        }

        (void)system_time_us();   /* keeps the 64-bit time extension current */
        leds_update(traffic);
        power_update();
    }
}
