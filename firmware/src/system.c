#include "system.h"

#include "board.h"
#include "stm32g0xx_hal.h"

/*
 * Clock plan (firmware/README.md):
 *
 *   HSE 12 MHz / M=3 = 4 MHz  --x N=80-->  VCO 320 MHz
 *       PLLR /5 = 64 MHz  SYSCLK (G0 maximum), AHB = APB = 64 MHz
 *       PLLQ /8 = 40 MHz  FDCAN kernel clock (exact divisor of 125k/250k/500k/1M)
 *       PLLP /5 = 64 MHz  unused (must still be a legal value)
 *   HSI48 = USB clock, trimmed by the CRS to the host's 1 kHz start-of-frame.
 *
 * Why a crystal: CAN needs better than ~0.5 % clock accuracy across all nodes;
 * HSI16 is only +-1 %. If the crystal fails to start (bad load caps, cracked
 * part), we fall back to HSI16 with the same PLL output frequencies and report
 * it in `status`, so the board is still reachable over USB.
 */

static const char *s_clock_source = "?";
static bool s_clock_precise;

static bool pll_config(uint32_t source, uint32_t pllm)
{
    RCC_OscInitTypeDef osc = {0};
    if (source == RCC_PLLSOURCE_HSE) {
        osc.OscillatorType = RCC_OSCILLATORTYPE_HSE;
        osc.HSEState = RCC_HSE_ON;
    } else {
        osc.OscillatorType = RCC_OSCILLATORTYPE_HSI;
        osc.HSIState = RCC_HSI_ON;
        osc.HSIDiv = RCC_HSI_DIV1;
        osc.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
    }
    osc.PLL.PLLState = RCC_PLL_ON;
    osc.PLL.PLLSource = source;
    osc.PLL.PLLM = pllm;
    osc.PLL.PLLN = 80;
    osc.PLL.PLLP = RCC_PLLP_DIV5;
    osc.PLL.PLLQ = RCC_PLLQ_DIV8;
    osc.PLL.PLLR = RCC_PLLR_DIV5;
    return HAL_RCC_OscConfig(&osc) == HAL_OK;
}

void system_clock_init(void)
{
    /* Range 1 regulator is required above 16 MHz. */
    __HAL_RCC_PWR_CLK_ENABLE();
    __HAL_RCC_SYSCFG_CLK_ENABLE();
    HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE1);

    bool ok = false;
#if BOARD_HSE_HZ
    ok = pll_config(RCC_PLLSOURCE_HSE, BOARD_PLLM);
    if (ok) {
        s_clock_source = "HSE crystal";
        s_clock_precise = true;
    } else {
        /* Turn the dead HSE off again, then use HSI16 / 4 = 4 MHz instead. */
        RCC_OscInitTypeDef off = {0};
        off.OscillatorType = RCC_OSCILLATORTYPE_HSE;
        off.HSEState = RCC_HSE_OFF;
        off.PLL.PLLState = RCC_PLL_NONE;
        (void)HAL_RCC_OscConfig(&off);
    }
#endif
    if (!ok) {
        ok = pll_config(RCC_PLLSOURCE_HSI, RCC_PLLM_DIV4);
        s_clock_source = BOARD_HSE_HZ ? "HSI16 (HSE FAILED to start)" : "HSI16";
        s_clock_precise = false;
    }
    if (!ok) {
        /* Should be impossible (HSI always runs); stay on HSI16 without the PLL. */
        s_clock_source = "HSI16 no PLL (clock setup FAILED)";
        return;
    }

    RCC_ClkInitTypeDef clk = {0};
    clk.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_PCLK1;
    clk.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
    clk.AHBCLKDivider = RCC_SYSCLK_DIV1;
    clk.APB1CLKDivider = RCC_HCLK_DIV1;
    /* 64 MHz in range 1 needs 2 flash wait states (RM0444 table 9). */
    (void)HAL_RCC_ClockConfig(&clk, FLASH_LATENCY_2);

    /* HSI48 for USB, kept accurate by the CRS locking onto USB SOF packets. */
    RCC_OscInitTypeDef hsi48 = {0};
    hsi48.OscillatorType = RCC_OSCILLATORTYPE_HSI48;
    hsi48.HSI48State = RCC_HSI48_ON;
    hsi48.PLL.PLLState = RCC_PLL_NONE;
    (void)HAL_RCC_OscConfig(&hsi48);

    RCC_PeriphCLKInitTypeDef periph = {0};
    periph.PeriphClockSelection = RCC_PERIPHCLK_USB | RCC_PERIPHCLK_FDCAN | RCC_PERIPHCLK_USART2;
    periph.UsbClockSelection = RCC_USBCLKSOURCE_HSI48;
    periph.FdcanClockSelection = RCC_FDCANCLKSOURCE_PLL;      /* PLLQ = 40 MHz */
    periph.Usart2ClockSelection = RCC_USART2CLKSOURCE_PCLK1;  /* 64 MHz */
    (void)HAL_RCCEx_PeriphCLKConfig(&periph);

    __HAL_RCC_CRS_CLK_ENABLE();
    RCC_CRSInitTypeDef crs = {0};
    crs.Prescaler = RCC_CRS_SYNC_DIV1;
    crs.Source = RCC_CRS_SYNC_SOURCE_USB;
    crs.Polarity = RCC_CRS_SYNC_POLARITY_RISING;
    crs.ReloadValue = __HAL_RCC_CRS_RELOADVALUE_CALCULATE(48000000u, 1000u);
    crs.ErrorLimitValue = RCC_CRS_ERRORLIMIT_DEFAULT;
    crs.HSI48CalibrationValue = RCC_CRS_HSI48CALIBRATION_DEFAULT;
    HAL_RCCEx_CRSConfig(&crs);
}

const char *system_clock_source(void)
{
    return s_clock_source;
}

bool system_clock_is_precise(void)
{
    return s_clock_precise;
}

/* ---- time base ---------------------------------------------------------- */

static uint32_t s_tim_last;
static uint64_t s_tim_high;

void system_timebase_init(void)
{
    /* TIM2 is the G0's only 32-bit timer: 1 MHz tick, wraps every ~71 minutes.
     * The software extension below only needs to be called once per wrap,
     * which the main loop does thousands of times a second. */
    __HAL_RCC_TIM2_CLK_ENABLE();
    TIM2->CR1 = 0;
    TIM2->PSC = (HAL_RCC_GetPCLK1Freq() / 1000000u) - 1u;
    TIM2->ARR = 0xFFFFFFFFu;
    TIM2->EGR = TIM_EGR_UG;   /* load PSC now */
    TIM2->CR1 = TIM_CR1_CEN;
}

uint64_t system_time_us(void)
{
    uint32_t primask = __get_PRIMASK();
    __disable_irq();
    uint32_t now = TIM2->CNT;
    if (now < s_tim_last)
        s_tim_high += 1ull << 32;
    s_tim_last = now;
    uint64_t t = s_tim_high | now;
    __set_PRIMASK(primask);
    return t;
}

uint32_t system_millis(void)
{
    return HAL_GetTick();
}

/* ---- reset / bootloader --------------------------------------------------- */

/* Survives a software reset: .noinit is not zeroed by the startup code. */
#define DFU_MAGIC 0xDF00B007u
static volatile uint32_t s_boot_request __attribute__((section(".noinit")));

#define SYSMEM_BASE 0x1FFF0000u   /* G0B1 ROM bootloader (AN2606) */

void system_early_init(void)
{
    /* .noinit RAM holds garbage after power-on; also require that the last
     * reset was a software reset (NVIC_SystemReset) before trusting it. */
    bool requested = s_boot_request == DFU_MAGIC && (RCC->CSR & RCC_CSR_SFTRSTF) != 0u;
    s_boot_request = 0;
    if (!requested)
        return;
    RCC->CSR |= RCC_CSR_RMVF;   /* clear reset flags so the next reset is judged fresh */

    /* We get here straight after a reset, so every peripheral is in its reset
     * state: the Rs pins are inputs and the 10k pull-ups hold both transceivers
     * in standby. Note: the ROM bootloader also probes FDCAN1 (PD0/PD1), but with
     * the transceiver in standby it cannot drive the bus. */
    __HAL_RCC_SYSCFG_CLK_ENABLE();
    __HAL_SYSCFG_REMAPMEMORY_SYSTEMFLASH();   /* map ROM at 0x0 like a BOOT0 start */
    const uint32_t *vectors = (const uint32_t *)SYSMEM_BASE;
    __set_MSP(vectors[0]);
    ((void (*)(void))vectors[1])();
    for (;;) {
    }
}

void system_reboot_to_dfu(void)
{
    s_boot_request = DFU_MAGIC;
    NVIC_SystemReset();
}

void system_reboot(void)
{
    s_boot_request = 0;
    NVIC_SystemReset();
}

void system_uid_string(char *buf)
{
    static const char hex[] = "0123456789ABCDEF";
    const uint8_t *uid = (const uint8_t *)UID_BASE;
    for (int i = 0; i < 12; i++) {
        buf[2 * i] = hex[uid[i] >> 4];
        buf[2 * i + 1] = hex[uid[i] & 0xF];
    }
    buf[24] = '\0';
}

/* We link with -nostartfiles (the ST startup file replaces newlib's crt0), so
 * crti.o is absent; __libc_init_array still calls _init(). Nothing to do. */
void _init(void);
void _init(void)
{
}

/* ---- core exception handlers ------------------------------------------------ */

void SysTick_Handler(void)
{
    HAL_IncTick();
}

void NMI_Handler(void)
{
    for (;;) {
    }
}

/* A crash must leave the bus alone. Put both transceivers back in standby by
 * driving Rs high directly (no HAL: the fault may be anywhere), then reset. */
void HardFault_Handler(void)
{
    BOARD_CAN1_RS_PORT->BSRR = BOARD_CAN1_RS_PIN;
    BOARD_CAN2_RS_PORT->BSRR = BOARD_CAN2_RS_PIN;
    NVIC_SystemReset();
}
