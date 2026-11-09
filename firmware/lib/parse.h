/*
 * parse.h - argument parsers shared by the shell commands.
 */
#ifndef PARSE_H
#define PARSE_H

#include <stdbool.h>
#include <stdint.h>

/* Decimal, or hex with a 0x prefix. Whole string must be consumed. */
bool parse_u32(const char *s, uint32_t *out);

/* Plain hex digits, no prefix (CAN IDs, masks). At most 8 digits. */
bool parse_hex_u32(const char *s, uint32_t *out);

/* "500000", "500k", "1M", "83.333k". Result in bit/s, must be 1..1000000. */
bool parse_bitrate(const char *s, uint32_t *out);

/* "can1" -> 0, "can2" -> 1. Bare numbers are rejected on purpose: commands
 * that enable transmit must name the channel the same way the board does. */
bool parse_channel(const char *s, uint8_t *chan);

/* Like parse_channel, but "all" sets *mask to both channels. *mask is a bitmask. */
bool parse_channel_mask(const char *s, uint8_t *mask);

/* "1699999999" or "1699999999.25" -> microseconds since the Unix epoch. */
bool parse_epoch_us(const char *s, uint64_t *out);

#endif
