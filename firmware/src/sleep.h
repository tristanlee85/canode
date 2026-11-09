/*
 * sleep.h - STM32 Stop 1 low-power mode (policy: lib/power.h).
 */
#ifndef SLEEP_H
#define SLEEP_H

#include <stdbool.h>

/* Once at boot: debug-in-Stop for debug builds, flash power-down in Stop. */
void sleep_init(void);

/* Enter Stop 1 now and return after waking up, with clocks, both CAN channels
 * (listen-only, as before) and USB restored. Returns early, without sleeping,
 * if CAN traffic shows up during entry. forced = "sleep now" (for the message). */
void sleep_run(bool forced);

#endif
