/*
 * selftest.h - FDCAN self-tests at 125k / 250k / 500k / 1M.
 */
#ifndef SELFTEST_H
#define SELFTEST_H

#include "shell.h"

/* Internal loopback on both channels: never touches the bus. Returns failures. */
int selftest_internal(shell_t *sh);

/* CAN1 <-> CAN2 over the real transceivers (bench only: JP1+JP2 bridged and a
 * twisted pair between the two channels). TRANSMITS on both channels; only run
 * from the explicit "selftest ext can1 can2" command. Returns failures. */
int selftest_external(shell_t *sh);

#endif
