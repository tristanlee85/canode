/*
 * stm32g0xx_hal_conf.h - which ST HAL modules we use (trimmed from ST's template).
 *
 * We use the HAL for clocks, GPIO and FDCAN (its message-RAM handling is fiddly
 * to redo by hand). USART2 and TIM2 are simple enough to drive by register, and
 * USB is TinyUSB, so their HAL modules are left out.
 */
#ifndef STM32G0XX_HAL_CONF_H
#define STM32G0XX_HAL_CONF_H

#ifdef __cplusplus
extern "C" {
#endif

#include "board.h"   /* provides HSE_VALUE */

#define HAL_MODULE_ENABLED
#define HAL_CORTEX_MODULE_ENABLED
#define HAL_FDCAN_MODULE_ENABLED
#define HAL_FLASH_MODULE_ENABLED   /* header only: flash wait-state macros used by RCC */
#define HAL_GPIO_MODULE_ENABLED
#define HAL_PWR_MODULE_ENABLED
#define HAL_RCC_MODULE_ENABLED

#define USE_HAL_FDCAN_REGISTER_CALLBACKS 0u   /* use the weak HAL_FDCAN_*Callback functions */

#if !defined(HSE_STARTUP_TIMEOUT)
#define HSE_STARTUP_TIMEOUT 100UL     /* ms */
#endif
#define HSI_VALUE           16000000UL
#define HSI48_VALUE         48000000UL
#define LSI_VALUE           32000UL
#define LSE_VALUE           32768UL
#define LSE_STARTUP_TIMEOUT 5000UL
#define EXTERNAL_I2S1_CLOCK_VALUE 48000UL
#define EXTERNAL_I2S2_CLOCK_VALUE 48000UL

#define VDD_VALUE                  3300UL
#define TICK_INT_PRIORITY          ((1UL << __NVIC_PRIO_BITS) - 1UL)   /* lowest */
#define USE_RTOS                   0U
#define PREFETCH_ENABLE            1U
#define INSTRUCTION_CACHE_ENABLE   1U

#include "stm32g0xx_hal_rcc.h"
#include "stm32g0xx_hal_gpio.h"
#include "stm32g0xx_hal_cortex.h"
#include "stm32g0xx_hal_fdcan.h"
#include "stm32g0xx_hal_flash.h"
#include "stm32g0xx_hal_pwr.h"

#define assert_param(expr) ((void)0U)

#ifdef __cplusplus
}
#endif

#endif
