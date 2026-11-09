/*
 * candump.h - Linux can-utils "candump -l" log format, one frame per line:
 *
 *     (1699999999.123456) can1 123#DEADBEEF
 *     (1699999999.123789) can2 18DAF110#0211
 *     (1699999999.124001) can1 7DF#R
 *
 * Standard IDs are always 3 hex digits and extended IDs always 8: readers
 * (tools/canlog/canlog.py, SavvyCAN, can-utils) tell them apart by length.
 * Data is uppercase hex. A remote frame is "#R", followed by its DLC if nonzero.
 */
#ifndef CANDUMP_H
#define CANDUMP_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "can_frame.h"

/* Longest line: "(" + 20 + "." + 6 + ") " + iface + " " + 8 + "#" + 16 + "\n" */
#define CANDUMP_LINE_MAX 72u

/*
 * Format one frame as a log line (with trailing '\n') using f->ts_us plus
 * epoch_offset_us as the timestamp and can_chan_name(f->chan) as the interface.
 * Returns the line length, or 0 if buf is too small.
 */
size_t candump_format(char *buf, size_t cap, const can_frame_t *f, uint64_t epoch_offset_us);

/*
 * Parse the "ID#DATA" part (as accepted by can-utils cansend): "123#11223344",
 * "1ABCDEF0#", "123#R", "123#R4". IDs with more than 3 hex digits are extended.
 * Optional '.' separators between data bytes are ignored ("123#11.22.33").
 * chan and ts_us are left at 0. Returns false on any syntax or range error.
 */
bool candump_parse_frame(const char *s, can_frame_t *f);

/* Write a u64 in decimal; returns chars written (no NUL). buf needs 20 bytes. */
size_t fmt_u64(char *buf, uint64_t v);

#endif
