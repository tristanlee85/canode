/*
 * can_frame.h - the one CAN frame type shared by the driver, logger and gateway.
 *
 * Plain C, no HAL: everything in firmware/lib/ is unit-tested on the host.
 */
#ifndef CAN_FRAME_H
#define CAN_FRAME_H

#include <stdint.h>

#define CAN_NUM_CHANNELS 2u       /* channel 0 = CAN1 (car side), 1 = CAN2 (module side) */
#define CAN_MAX_DLEN     8u       /* classic CAN only */

#define CAN_STD_ID_MAX   0x7FFu
#define CAN_EXT_ID_MAX   0x1FFFFFFFu

#define CAN_FLAG_EXT     0x01u    /* 29-bit identifier */
#define CAN_FLAG_RTR     0x02u    /* remote frame (no data, len = requested DLC) */

typedef struct {
    uint64_t ts_us;               /* receive time, microseconds (see system_time_us) */
    uint32_t id;                  /* 11- or 29-bit identifier, no flag bits mixed in */
    uint8_t  chan;                /* 0 = can1, 1 = can2 */
    uint8_t  len;                 /* 0..8 */
    uint8_t  flags;               /* CAN_FLAG_* */
    uint8_t  data[CAN_MAX_DLEN];
} can_frame_t;

/* "can1" / "can2": matches the board silkscreen and the candump interface names. */
static inline const char *can_chan_name(uint8_t chan)
{
    return chan == 0 ? "can1" : chan == 1 ? "can2" : "can?";
}

#endif
