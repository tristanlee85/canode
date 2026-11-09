/*
 * frame_ring.h - lock-free single-producer / single-consumer queue of CAN frames.
 *
 * The FDCAN interrupt is the only producer and the main loop the only consumer,
 * so no interrupt masking is needed: each side only writes its own index, and
 * acquire/release ordering makes sure the frame body is visible before the index.
 * (On the single-core Cortex-M0+ this compiles to plain loads/stores plus DMB.)
 */
#ifndef FRAME_RING_H
#define FRAME_RING_H

#include <stdbool.h>
#include <stdint.h>

#include "can_frame.h"

#define FRAME_RING_SIZE 256u   /* must be a power of two; 256 x 24 B = 6 KB */

typedef struct {
    can_frame_t buf[FRAME_RING_SIZE];
    uint32_t head;      /* written by producer only */
    uint32_t tail;      /* written by consumer only */
    uint32_t dropped;   /* producer-side count of frames lost because the ring was full */
} frame_ring_t;

void frame_ring_init(frame_ring_t *r);
bool frame_ring_push(frame_ring_t *r, const can_frame_t *f);   /* producer */
bool frame_ring_pop(frame_ring_t *r, can_frame_t *f);          /* consumer */
uint32_t frame_ring_count(const frame_ring_t *r);

#endif
