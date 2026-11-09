#include "frame_ring.h"

#include <string.h>

_Static_assert((FRAME_RING_SIZE & (FRAME_RING_SIZE - 1u)) == 0u, "FRAME_RING_SIZE must be a power of two");

void frame_ring_init(frame_ring_t *r)
{
    memset(r, 0, sizeof(*r));
}

bool frame_ring_push(frame_ring_t *r, const can_frame_t *f)
{
    uint32_t head = r->head;  /* own index: plain read is fine */
    uint32_t tail = __atomic_load_n(&r->tail, __ATOMIC_ACQUIRE);
    if (head - tail >= FRAME_RING_SIZE) {
        r->dropped++;
        return false;
    }
    r->buf[head & (FRAME_RING_SIZE - 1u)] = *f;
    __atomic_store_n(&r->head, head + 1u, __ATOMIC_RELEASE);
    return true;
}

bool frame_ring_pop(frame_ring_t *r, can_frame_t *f)
{
    uint32_t tail = r->tail;
    uint32_t head = __atomic_load_n(&r->head, __ATOMIC_ACQUIRE);
    if (head == tail)
        return false;
    *f = r->buf[tail & (FRAME_RING_SIZE - 1u)];
    __atomic_store_n(&r->tail, tail + 1u, __ATOMIC_RELEASE);
    return true;
}

uint32_t frame_ring_count(const frame_ring_t *r)
{
    return __atomic_load_n(&r->head, __ATOMIC_ACQUIRE) - __atomic_load_n(&r->tail, __ATOMIC_ACQUIRE);
}
