# Firmware (not started)

Suggested stack: STM32CubeG0 HAL/LL with arm-none-eabi-gcc + CMake. Zephyr is an alternative: it has FDCAN and USB-CDC drivers for G0B1. A Nucleo-G0B1RE dev board can run the same firmware before the PCB arrives.

## Pin map (validated by `make pins` against ST's pin data)
| Function | Pin | AF / mode |
|---|---|---|
| FDCAN1 RX / TX | PD0 / PD1 | AF3 |
| CAN1 transceiver Rs | PD2 | GPIO out; LOW = active, HIGH/float = standby (10k pull-up) |
| FDCAN2 RX / TX | PB0 / PB1 | AF3 |
| CAN2 transceiver Rs | PB2 | GPIO out, same as above |
| USB DM / DP | PA11 / PA12 | USB (HSI48 + CRS, no crystal needed) |
| HSE | PF0 / PF1 | 12 MHz crystal |
| VBAT sense | PA0 | ADC1_IN0, V = raw × 3.3 / 4095 × 11 |
| AUX_IN sense | PA1 | ADC1_IN1, same scaling |
| AUX_OUT gate | PA8 | GPIO or TIM1_CH1 (AF2) |
| LED1 / LED2 | PA5 / PA6 | GPIO, active high |
| Debug UART | PA2 TX / PA3 RX | USART2 (AF1) |
| Spare | PB6 / PB7 / PB8 / PB9 | PB6/PB7 = I2C1 (AF6) or USART1 |
| SWD | PA13 / PA14 | default after reset; PA14 is also BOOT0 |

## Clock plan (example)
HSE 12 MHz, PLL M=3, so 4 MHz into the PLL, N=80 for a 320 MHz VCO.
- PLLR /5 = 64 MHz SYSCLK.
- PLLQ /8 = 40 MHz FDCAN kernel clock (divides cleanly into 125k/250k/500k/1M).
- USB from HSI48 with CRS synced to USB SOF.

## First milestones
1. Blink LEDs and print over the UART.
2. USB CDC (virtual serial) and a command shell.
3. FDCAN internal loopback, then external CAN1↔CAN2 loopback.
4. Bus-monitoring (listen-only) capture, streamed over USB in candump format so `tools/canlog` and SavvyCAN can read it.
5. Gateway mode: forward CAN1↔CAN2 with per-ID filter and rewrite rules.
