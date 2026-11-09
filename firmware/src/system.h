/*
 * system.h - clocks, time base, reset/bootloader entry.
 */
#ifndef SYSTEM_H
#define SYSTEM_H

#include <stdbool.h>
#include <stdint.h>

#define FDCAN_KERNEL_HZ 40000000u   /* PLLQ: see system_clock_init() */

/* Call first thing in main(): jumps to the ROM DFU bootloader if requested. */
void system_early_init(void);

/* HSE (or HSI16) -> PLL -> 64 MHz SYSCLK, 40 MHz FDCAN, 48 MHz USB from HSI48+CRS. */
void system_clock_init(void);

/* Human-readable clock source, e.g. "HSE 12 MHz" or "HSI16 (HSE FAILED)". */
const char *system_clock_source(void);
bool system_clock_is_precise(void);   /* false = running on HSI16: CAN timing +-1 % */

/* Free-running microsecond counter (TIM2, 32-bit, extended to 64 bits in software).
 * Safe to call from interrupts and the main loop. */
void     system_timebase_init(void);
uint64_t system_time_us(void);
uint32_t system_millis(void);

/* Reset into ST's ROM USB DFU bootloader (for dfu-util), via a clean reset. */
void system_reboot_to_dfu(void) __attribute__((noreturn));
void system_reboot(void) __attribute__((noreturn));

/* 96-bit unique device ID as 24 hex chars (USB serial number). buf >= 25 bytes. */
void system_uid_string(char *buf);

#endif
