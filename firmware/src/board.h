/*
 * board.h - every difference between the supported boards lives here.
 *
 * Build defines exactly one of:
 *   BOARD_CANODE        canode rev A (STM32G0B1CEU6 UFQFPN-48, 2x SN65HVD230, 12 MHz crystal)
 *   BOARD_NUCLEO_G0B1RE ST NUCLEO-G0B1RE (MB1360) for testing before the PCB exists
 *
 * Pins that are the same on both boards (FDCAN, Rs, USART2) are defined once
 * at the bottom. On the Nucleo they are just morpho-header pins: there are no
 * transceivers, so only the internal-loopback self-test is meaningful there.
 * Pin map source of truth: firmware/README.md (checked by `make pins`).
 */
#ifndef BOARD_H
#define BOARD_H

#if defined(BOARD_CANODE)

#define BOARD_NAME           "canode-revA"
/* X1: 12 MHz crystal on PF0/PF1 (not an oscillator, so HSE is "on", not "bypass").
 * PLL M=3 gives the 4 MHz PLL input. */
#define BOARD_HSE_HZ         12000000u
#define BOARD_PLLM           RCC_PLLM_DIV3
#define BOARD_HAS_CAN_PHY    1    /* SN65HVD230 on both channels */

#define BOARD_LED1_PORT      GPIOA
#define BOARD_LED1_PIN       GPIO_PIN_5
#define BOARD_LED2_PORT      GPIOA
#define BOARD_LED2_PIN       GPIO_PIN_6
#define BOARD_LED_ON         GPIO_PIN_SET      /* active high */

#elif defined(BOARD_NUCLEO_G0B1RE)

#define BOARD_NAME           "nucleo-g0b1re"
/* The Nucleo's HSE input (PF0) only gets the ST-LINK's 8 MHz MCO if solder
 * bridge SB17 is closed, and X3 is not fitted. ST's own Zephyr and TinyUSB board
 * files run it from HSI16, so do we: HSI16 / M=4 = the same 4 MHz PLL input.
 * HSI16 is +-1 %, fine for internal loopback but too loose for a real bus. */
#define BOARD_HSE_HZ         0u          /* 0 = no HSE, use HSI16 */
#define BOARD_PLLM           RCC_PLLM_DIV4
#define BOARD_HAS_CAN_PHY    0           /* no transceivers on the Nucleo */

/* LD4 (green, user) on PA5 via a transistor, active high. Only one user LED. */
#define BOARD_LED1_PORT      GPIOA
#define BOARD_LED1_PIN       GPIO_PIN_5
#define BOARD_LED_ON         GPIO_PIN_SET
/* No LED2. */

#else
#error "Define BOARD_CANODE or BOARD_NUCLEO_G0B1RE"
#endif

/* HAL needs HSE_VALUE even if HSE is unused; 8 MHz = the Nucleo MCO value. */
#if BOARD_HSE_HZ
#define HSE_VALUE            BOARD_HSE_HZ
#else
#define HSE_VALUE            8000000u
#endif

/* ---- shared pin map (canode schematic; free morpho pins on the Nucleo) ---- */

/* FDCAN1 = CAN1 = car side. AF3 on PD0/PD1 (validated by `make pins`). */
#define BOARD_CAN1_PORT      GPIOD
#define BOARD_CAN1_RX_PIN    GPIO_PIN_0
#define BOARD_CAN1_TX_PIN    GPIO_PIN_1
#define BOARD_CAN1_AF        GPIO_AF3_FDCAN1
#define BOARD_CAN1_RS_PORT   GPIOD
#define BOARD_CAN1_RS_PIN    GPIO_PIN_2

/* FDCAN2 = CAN2 = module side. AF3 on PB0/PB1. */
#define BOARD_CAN2_PORT      GPIOB
#define BOARD_CAN2_RX_PIN    GPIO_PIN_0
#define BOARD_CAN2_TX_PIN    GPIO_PIN_1
#define BOARD_CAN2_AF        GPIO_AF3_FDCAN2
#define BOARD_CAN2_RS_PORT   GPIOB
#define BOARD_CAN2_RS_PIN    GPIO_PIN_2

/* USART2 on PA2 (TX) / PA3 (RX), AF1. canode: J4 header. Nucleo: ST-LINK VCP. */
#define BOARD_UART_PORT      GPIOA
#define BOARD_UART_TX_PIN    GPIO_PIN_2
#define BOARD_UART_RX_PIN    GPIO_PIN_3
#define BOARD_UART_AF        GPIO_AF1_USART2
#define BOARD_UART_BAUD      115200u

/* Power-on CAN defaults. Both channels come up in bus-monitoring (listen-only). */
#define BOARD_CAN_DEFAULT_BITRATE 500000u

/* Transceiver Rs state while monitoring (see can_rs_listen_t in can_drv.h):
 * CAN_RS_LISTEN_LOW  = transceiver active (current policy, CLAUDE.md)
 * CAN_RS_LISTEN_HIGH = transceiver standby: hardware TX-off, receiver on.
 * Stays LOW until the bring-up bench test (validation/README.md, bring-up
 * step 7) shows reception is reliable with Rs high at 125k-1M. Changing the
 * default is this one line; `rslisten` changes it at run time. */
#define BOARD_CAN_RS_LISTEN_DEFAULT CAN_RS_LISTEN_LOW

#endif
