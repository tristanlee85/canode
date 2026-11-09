/*
 * gateway.h - CAN1 <-> CAN2 forwarding rules (milestone 5 skeleton).
 *
 * The board sits man-in-the-middle: CAN1 on the car side, CAN2 on the module
 * side. When the gateway is on, every frame received on one channel is run
 * through the rule table and, unless dropped, transmitted on the other.
 *
 * Rules are checked in order; the first rule that matches decides:
 *   pass     forward unchanged
 *   drop     do not forward
 *   rewrite  forward with a new ID and/or some data nibbles replaced
 * A frame that matches no rule is forwarded unchanged (transparent gateway).
 *
 * Shell syntax (argv after "gw add"):
 *   <from> <match> <action> [id=<hex>] [data=<pattern>]
 *   from     can1 | can2 | any       which side the frame arrived on
 *   match    *            any frame
 *            123          standard ID (1-3 hex digits)
 *            18DAF110     extended ID (4-8 hex digits, same rule as candump)
 *            123/7F0      ID with a mask: (rx_id & mask) == (id & mask)
 *   action   pass | drop | rewrite
 *   data     two characters per byte, one per nibble: a hex digit replaces that
 *            nibble, '.' keeps it. "data=..01" sets byte 1 to 0x01 and leaves
 *            byte 0 alone. Bytes beyond the frame's length are not added.
 *
 * Example (hypothetical ID/byte): clear the high nibble of byte 2 of ID 3B3 on
 * its way from the car to the module:  gw add can1 3B3 rewrite data=....0.
 */
#ifndef GATEWAY_H
#define GATEWAY_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "can_frame.h"

#define GW_MAX_RULES 16u

typedef enum { GW_PASS = 0, GW_DROP, GW_REWRITE } gw_action_t;
typedef enum { GW_MATCH_STD = 0, GW_MATCH_EXT, GW_MATCH_ANY } gw_idtype_t;

typedef struct {
    bool        used;
    uint8_t     from_mask;            /* bit n set = applies to frames received on channel n */
    gw_idtype_t idtype;
    uint32_t    id;
    uint32_t    id_mask;
    gw_action_t action;
    bool        set_id;
    uint32_t    new_id;               /* same width (std/ext) as the received frame */
    uint8_t     data_mask[CAN_MAX_DLEN];  /* bits to replace */
    uint8_t     data_val[CAN_MAX_DLEN];   /* replacement bits */
    uint32_t    hits;
} gw_rule_t;

typedef struct {
    gw_rule_t rules[GW_MAX_RULES];
} gw_table_t;

void gw_init(gw_table_t *t);

/*
 * Decide what happens to frame f (f->chan = channel it was received on).
 * Returns true if it should be sent on the other channel; f may have been
 * modified in place. Increments the matching rule's hit counter.
 */
bool gw_process(gw_table_t *t, can_frame_t *f);

/* Parse "gw add" arguments. On error returns false and sets *err to a message. */
bool gw_rule_parse(int argc, char **argv, gw_rule_t *out, const char **err);

/* Append a rule; returns its index, or -1 if the table is full. */
int gw_rule_add(gw_table_t *t, const gw_rule_t *r);

/* Delete rule idx and shift later rules up (keeps the order). */
bool gw_rule_del(gw_table_t *t, unsigned idx);

unsigned gw_rule_count(const gw_table_t *t);

/* Render a rule back in "gw add" syntax (without the hit count). */
size_t gw_rule_format(const gw_rule_t *r, char *buf, size_t cap);

#endif
