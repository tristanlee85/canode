#include "test.h"
#include "frame_ring.h"

static frame_ring_t ring;  /* 6 KB: keep it off the stack */

void test_frame_ring(void)
{
    can_frame_t f = {0}, out;
    frame_ring_init(&ring);

    CHECK(!frame_ring_pop(&ring, &out));
    CHECK_EQ(frame_ring_count(&ring), 0);

    for (uint32_t i = 0; i < FRAME_RING_SIZE; i++) {
        f.id = i;
        CHECK(frame_ring_push(&ring, &f));
    }
    CHECK_EQ(frame_ring_count(&ring), FRAME_RING_SIZE);
    f.id = 9999;
    CHECK(!frame_ring_push(&ring, &f));   /* full */
    CHECK_EQ(ring.dropped, 1);

    for (uint32_t i = 0; i < FRAME_RING_SIZE; i++) {
        CHECK(frame_ring_pop(&ring, &out));
        CHECK_EQ(out.id, i);
    }
    CHECK(!frame_ring_pop(&ring, &out));

    /* Indices wrap past 2^32 correctly (unsigned arithmetic). */
    ring.head = ring.tail = 0xFFFFFFF0u;
    for (uint32_t i = 0; i < 40; i++) {
        f.id = i;
        CHECK(frame_ring_push(&ring, &f));
        CHECK(frame_ring_pop(&ring, &out));
        CHECK_EQ(out.id, i);
    }
    CHECK_EQ(frame_ring_count(&ring), 0);
}
