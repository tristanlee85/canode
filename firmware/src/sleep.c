/*
 * sleep.c - STM32G0 Stop 1 low-power mode: entry, wake-up, restore.
 *
 * WHEN to sleep is decided by lib/power.c (host-tested). This file only does
 * it. See firmware/README.md "Sleep" for the current budget and what is
 * untested.
 *
 * Entry (RM0444 "Stop 1 mode"):
 *   1. Tell the consoles, let the UART (and a USB reply to "sleep now") drain.
 *   2. Both FDCANs stopped, transceivers in standby (Rs high: driver off,
 *      receiver still on, so RXD still goes low on a dominant bus bit).
 *   3. USB detached and powered down; LEDs off.
 *   4. Wake-up sources armed:
 *        CAN1  PD0 (RXD1) as a GPIO input, EXTI line 0 (port D), falling edge.
 *        CAN2  PB0 (RXD2) cannot use EXTI line 0 too (EXTICR maps each line to
 *              ONE port), so it goes through COMP3: PB0 = COMP3_INP (IO1),
 *              compared against VREFINT (~1.2 V). COMP3 runs in Stop and its
 *              output is EXTI line 20, falling edge = RXD going dominant.
 *        UART  PA3 (USART2 RX) as a GPIO input, EXTI line 3, falling edge
 *              (any key on the J4 / ST-LINK console).
 *   5. Interrupts masked (PRIMASK), all NVIC lines disabled except the three
 *      wake-up IRQs, every armed EXTI pending bit cleared, then one last
 *      check: if a frame reached the RX ring or an RX line is low (dominant
 *      right now), abort instead of sleeping.
 *   6. SysTick off, LPMS = Stop 1, SLEEPDEEP, WFI. A pending enabled IRQ
 *      wakes the core even with PRIMASK set, so no handler runs: the wake
 *      source is read from EXTI->FPR1 afterwards.
 * Exit: the chip wakes on HSI16 with the PLL, HSE and HSI48 off. Restore the
 * tick, rerun system_clock_init() (HSE -> PLL 64 MHz, PLLQ 40 MHz FDCAN kernel
 * clock, HSI48 + CRS for USB), give PA3 back to the USART, restart each
 * channel in the mode it had through the normal configure path (Rs low only
 * after the controller runs), restart USB.
 *
 * Gateway: if the gateway is on (T's explicit "gw on", both channels in
 * normal mode), it is allowed to sleep. Both channels are armed for wake-up
 * and come back in normal mode, so the gateway resumes by itself. Without
 * the gateway, a normal-mode channel is never slept with (lib/power.c), and
 * as a backstop is restored as monitor here.
 *
 * The frame (or frames) that woke us are lost: the controller needs the
 * clock back (crystal start-up, ~ms) before it can receive. In gateway mode
 * that means they are not forwarded either; a sender alone on its segment
 * gets no ACK and keeps retrying until we are back. See the README.
 */
#include "sleep.h"

#include <inttypes.h>

#include "app.h"
#include "board.h"
#include "can_drv.h"
#include "console.h"
#include "power.h"
#include "stm32g0xx_hal.h"
#include "system.h"
#include "uart.h"
#include "usb.h"

/* A GPIO_PIN_n mask is also the bit of EXTI line n. */
#define EXTI_CAN1  ((uint32_t)BOARD_CAN1_RX_PIN)
#define EXTI_UART  ((uint32_t)BOARD_UART_RX_PIN)
#define EXTI_COMP3 EXTI_IMR1_IM20      /* COMP3 output (RM0444 EXTI line table) */

_Static_assert(BOARD_CAN1_RX_PIN != BOARD_UART_RX_PIN, "CAN1 RX and UART RX need different EXTI lines");
#if BOARD_WAKE_CAN2_COMP
/* COMP3 INPSEL=00 (IO1) is PB0. If CAN2 RX ever moves, this must change. */
_Static_assert(BOARD_CAN2_RX_PIN == GPIO_PIN_0, "COMP3_INP IO1 is PB0");
#endif

/* COMP3: medium-speed mode for lower supply current. A CAN frame always has
 * dominant runs of several bits (2 us each at 500k), so microsecond-class
 * propagation is enough. Bench check: does a 1 Mbit/s frame wake it? If not,
 * use COMP_CSR_PWRMODE high speed (0). */
#define COMP3_CSR_CFG ((0x3u << COMP_CSR_INMSEL_Pos) |   /* INM = VREFINT (~1.2 V) */ \
                       (0x0u << COMP_CSR_INPSEL_Pos) |   /* INP = IO1 = PB0 */ \
                       COMP_CSR_HYST_0 |                 /* low hysteresis */ \
                       COMP_CSR_PWRMODE_0)               /* medium speed */
#define COMP_SCALER_STAB_US 200u   /* HAL: COMP_DELAY_VOLTAGE_SCALER_STAB_US */
#define COMP_STARTUP_US     80u    /* LL:  LL_COMP_DELAY_STARTUP_US */

static IRQn_Type exti_irq(uint32_t line_bit)
{
    if (line_bit <= (1u << 1))
        return EXTI0_1_IRQn;
    if (line_bit <= (1u << 3))
        return EXTI2_3_IRQn;
    return EXTI4_15_IRQn;
}

static void led_off(GPIO_TypeDef *port, uint16_t pin)
{
    HAL_GPIO_WritePin(port, pin, BOARD_LED_ON == GPIO_PIN_SET ? GPIO_PIN_RESET : GPIO_PIN_SET);
}

static void leds_off(void)
{
    led_off(BOARD_LED1_PORT, BOARD_LED1_PIN);
#ifdef BOARD_LED2_PORT
    led_off(BOARD_LED2_PORT, BOARD_LED2_PIN);
#endif
}

/* GPIO input, pull-up, EXTI falling edge (HAL sets EXTICR, FTSR1, IMR1). */
static void arm_pin(GPIO_TypeDef *port, uint16_t pin)
{
    GPIO_InitTypeDef gpio = {0};
    gpio.Pin = pin;
    gpio.Mode = GPIO_MODE_IT_FALLING;
    gpio.Pull = GPIO_PULLUP;
    gpio.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(port, &gpio);
}

#if BOARD_WAKE_CAN2_COMP
static void delay_us(uint32_t us)
{
    uint64_t t0 = system_time_us();
    while (system_time_us() - t0 < us) {
    }
}

static void arm_comp3(void)
{
    GPIO_InitTypeDef gpio = {0};
    gpio.Pin = BOARD_CAN2_RX_PIN;
    gpio.Mode = GPIO_MODE_ANALOG;   /* required for a comparator input */
    gpio.Pull = GPIO_NOPULL;
    HAL_GPIO_Init(BOARD_CAN2_PORT, &gpio);

    /* The COMP registers sit in the SYSCFG block (clock enabled at boot). */
    COMP3->CSR = COMP3_CSR_CFG;
    delay_us(COMP_SCALER_STAB_US);
    COMP3->CSR = COMP3_CSR_CFG | COMP_CSR_EN;
    delay_us(COMP_STARTUP_US);

    EXTI->RTSR1 &= ~EXTI_COMP3;
    EXTI->FTSR1 |= EXTI_COMP3;
    EXTI->FPR1 = EXTI_COMP3;
    EXTI->IMR1 |= EXTI_COMP3;
}
#endif

/* Returns the EXTI lines armed. Only channels that were running (monitor, or
 * normal under the gateway) can wake us: waking for a channel that is
 * switched off would just loop. */
static uint32_t wake_arm(const can_sleep_state_t *saved)
{
    uint32_t lines = 0;
    if (saved->mode[0] != CAN_MODE_OFF) {
        arm_pin(BOARD_CAN1_PORT, BOARD_CAN1_RX_PIN);
        lines |= EXTI_CAN1;
    }
#if BOARD_WAKE_CAN2_COMP
    if (saved->mode[1] != CAN_MODE_OFF) {
        arm_comp3();
        lines |= EXTI_COMP3;
    }
#endif
    arm_pin(BOARD_UART_PORT, BOARD_UART_RX_PIN);
    lines |= EXTI_UART;
    return lines;
}

static void wake_disarm(uint32_t lines)
{
    EXTI->IMR1 &= ~lines;
    EXTI->FTSR1 &= ~lines;
    EXTI->RPR1 = lines;
    EXTI->FPR1 = lines;
#if BOARD_WAKE_CAN2_COMP
    if (lines & EXTI_COMP3)
        COMP3->CSR = 0;   /* off; can_sleep_exit() re-muxes PB0 to FDCAN2 */
#endif
}

/* Is any armed CAN input dominant (low) right now? Then a frame is under way. */
static bool can_line_busy(uint32_t lines)
{
    if ((lines & EXTI_CAN1) && HAL_GPIO_ReadPin(BOARD_CAN1_PORT, BOARD_CAN1_RX_PIN) == GPIO_PIN_RESET)
        return true;
#if BOARD_WAKE_CAN2_COMP
    if ((lines & EXTI_COMP3) && !(COMP3->CSR & COMP_CSR_VALUE))
        return true;
#endif
    return false;
}

static uint8_t wake_sources(uint32_t fired)
{
    uint8_t m = 0;
    if (fired & EXTI_CAN1)
        m |= POWER_WAKE_CAN1;
    if (fired & EXTI_COMP3)
        m |= POWER_WAKE_CAN2;
    if (fired & EXTI_UART)
        m |= POWER_WAKE_UART;
    return m;
}

void sleep_init(void)
{
#ifndef NDEBUG
    /* Debug builds only: keep the debug port alive in Stop so SWD stays
     * attached on the bench. It also keeps clocks running, so the current
     * draw is NOT representative. Release builds: attach with "connect under
     * reset" (J3 NRST) or press RESET. */
    __HAL_RCC_DBGMCU_CLK_ENABLE();
    HAL_DBGMCU_EnableDBGStopMode();
#endif
    /* Flash powered down in Stop: a little less current, a few us more
     * wake-up time (DS13560 tWUSTOP). */
    HAL_PWREx_EnableFlashPowerDown(PWR_FLASHPD_STOP);
}

void sleep_run(bool forced)
{
    power_t *pm = &g_app.power;
    char src[24];

    bool gw = g_app.gw_enabled;
    console_broadcast("\r\nsleep: %s, entering Stop 1. Wakes on CAN traffic or a key on the UART.%s\r\n"
                      "       USB will disconnect; press RESET (or a UART key) to get it back.\r\n",
                      forced ? "'sleep now'" : "buses idle",
                      gw ? " The gateway resumes on wake." : "");
    uint32_t t = system_millis();
    while (system_millis() - t < 50u)
        usb_poll();   /* lets a 'sleep now' reply reach a USB host */
    (void)uart_drain(500u);

    /* 1. Last look before touching anything. */
    if (can_rx_pending()) {
        power_on_abort(pm, system_millis());
        console_broadcast("sleep: aborted, CAN frames arrived\r\n");
        return;
    }

    /* 2-4. Quiet the board and arm the wake-ups. */
    can_sleep_state_t saved;
    can_sleep_enter(&saved);
    /* Only the gateway may come back TX-capable (the policy never sleeps
     * with a manual normal-mode channel; this is the backstop). */
    for (uint8_t ch = 0; ch < CAN_NUM_CHANNELS; ch++) {
        if (saved.mode[ch] == CAN_MODE_NORMAL && !gw)
            saved.mode[ch] = CAN_MODE_MONITOR;
    }
    usb_stop();
    leds_off();
    uint32_t lines = wake_arm(&saved);

    /* 5. Point of no return, with interrupts masked. */
    __disable_irq();
    uint32_t iser = NVIC->ISER[0];
    NVIC->ICER[0] = 0xFFFFFFFFu;
    EXTI->RPR1 = lines;
    EXTI->FPR1 = lines;
    const IRQn_Type irqs[] = {exti_irq(EXTI_CAN1), exti_irq(EXTI_UART), ADC1_COMP_IRQn};
    for (unsigned i = 0; i < sizeof(irqs) / sizeof(irqs[0]); i++) {
        NVIC_ClearPendingIRQ(irqs[i]);
        NVIC_EnableIRQ(irqs[i]);
    }

    bool aborted = can_rx_pending() || can_line_busy(lines) || (EXTI->FPR1 & lines) != 0u;
    uint32_t fired = 0;
    if (!aborted) {
        /* 6. SysTick would wake us at once; HCLK stops in Stop anyway. */
        HAL_SuspendTick();
        SCB->ICSR = SCB_ICSR_PENDSTCLR_Msk;
        power_on_sleep(pm);
        HAL_PWR_EnterSTOPMode(PWR_LOWPOWERREGULATOR_ON, PWR_STOPENTRY_WFI);
        /* --- asleep: running again on HSI16 --- */
        fired = EXTI->FPR1 & lines;
    }

    wake_disarm(lines);
    for (unsigned i = 0; i < sizeof(irqs) / sizeof(irqs[0]); i++) {
        NVIC_DisableIRQ(irqs[i]);
        NVIC_ClearPendingIRQ(irqs[i]);
    }
    NVIC->ISER[0] = iser;
    if (!aborted) {
        /* 1 ms tick at the current (HSI16) clock, so the HAL's start-up
         * timeouts in system_clock_init() work. */
        SystemCoreClockUpdate();
        (void)HAL_InitTick(TICK_INT_PRIORITY);
    }
    __enable_irq();

    /* Restore. system_clock_init() also reselects PLLQ as the FDCAN kernel
     * clock and HSI48 + CRS for USB, and reconfigures SysTick for 64 MHz. */
    if (!aborted)
        system_clock_init();
    uart_pins_wake();
    can_sleep_exit(&saved);   /* previous modes; Rs low only after start */
    usb_init();

    uint32_t now = system_millis();
    if (aborted) {
        power_on_abort(pm, now);
        console_broadcast("sleep: aborted, CAN traffic arrived during entry\r\n");
        return;
    }
    power_on_wake(pm, wake_sources(fired), now);
    power_wake_format(pm->last_wake, src, sizeof(src));
    console_broadcast("sleep: woke on %s (wake %" PRIu32 "). Clock %s. %s\r\n"
                      "       The first frame(s) were lost; uptime and log timestamps paused while asleep.\r\n",
                      src, pm->wakes, system_clock_source(),
                      gw ? "Gateway resumed (both channels in normal mode)."
                         : "Channels back in listen-only monitor mode.");
}

/* The wake-up IRQs are only ever enabled with PRIMASK set and are disabled
 * again before it is cleared, so these should never run. If one does, clear
 * the source so it cannot fire forever. */
static void exti_clear_all(void)
{
    EXTI->RPR1 = EXTI_CAN1 | EXTI_UART | EXTI_COMP3;
    EXTI->FPR1 = EXTI_CAN1 | EXTI_UART | EXTI_COMP3;
}

void EXTI0_1_IRQHandler(void)
{
    exti_clear_all();
}

void EXTI2_3_IRQHandler(void)
{
    exti_clear_all();
}

void EXTI4_15_IRQHandler(void)
{
    exti_clear_all();
}

void ADC1_COMP_IRQHandler(void)
{
    exti_clear_all();
}
