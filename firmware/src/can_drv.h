/*
 * can_drv.h - FDCAN1/FDCAN2 + SN65HVD230 transceiver control.
 *
 * READ THE SAFETY RULES AT THE TOP OF can_drv.c BEFORE CHANGING ANYTHING HERE.
 * Short version: listen-only by default; transmit only via can_enable_tx(),
 * and only call that from an explicit user command naming the channel.
 */
#ifndef CAN_DRV_H
#define CAN_DRV_H

#include <stdbool.h>
#include <stdint.h>

#include "bittiming.h"
#include "can_frame.h"

typedef enum {
    CAN_MODE_OFF = 0,   /* controller stopped, transceiver in standby */
    CAN_MODE_MONITOR,   /* FDCAN bus monitoring: receive only, never drives the bus */
    CAN_MODE_NORMAL,    /* TX-CAPABLE: ACKs, error frames, transmits */
    CAN_MODE_LOOPBACK,  /* internal loopback self-test: bus untouched, transceiver in standby */
} can_mode_t;

/*
 * What the transceiver does while a channel is in CAN_MODE_MONITOR:
 *   LOW   Rs driven low: transceiver fully active; FDCAN bus monitoring alone
 *         keeps us off the bus. Current policy (CLAUDE.md), and the default.
 *   HIGH  Rs left high: SN65HVD230 "standby", driver OFF in hardware, receiver
 *         on (TI specifies a slower receiver path here). Two independent
 *         no-transmit layers, but reception at 500k/1M is NOT bench-verified yet.
 * TX-capable modes always drive Rs low, whatever this is set to.
 */
typedef enum {
    CAN_RS_LISTEN_LOW = 0,
    CAN_RS_LISTEN_HIGH,
} can_rs_listen_t;

enum {
    CAN_OK = 0,
    CAN_ERR_BITRATE = -1,   /* no valid bit timing for that rate */
    CAN_ERR_HAL = -2,       /* peripheral did not respond */
    CAN_ERR_MODE = -3,      /* operation not allowed in the current mode */
    CAN_ERR_FULL = -4,      /* TX FIFO full */
    CAN_ERR_ARG = -5,
};

typedef struct {
    can_mode_t      mode;
    uint32_t        bitrate;
    can_bittiming_t bt;
    can_rs_listen_t rs_listen;  /* Rs state used in monitor mode */
    uint32_t        rx;         /* frames received */
    uint32_t        tx;         /* frames queued for transmit */
    uint32_t        tx_full;    /* transmit attempts refused: FIFO full */
    uint32_t        hw_lost;    /* frames lost in the 3-deep hardware RX FIFOs */
    uint32_t        bus_off;    /* bus-off events (each one dropped us back to monitor) */
} can_chan_info_t;

typedef struct {
    bool    bus_off;
    bool    error_passive;
    bool    warning;
    uint8_t tec, rec;           /* transmit / receive error counters */
    uint8_t last_error;         /* PSR.LEC: 0 none, 1 stuff, 2 form, 3 ack, 4 bit1, 5 bit0, 6 crc, 7 unchanged */
} can_bus_state_t;

/* Pins, clocks, interrupt; transceivers forced to standby; both channels then
 * start in CAN_MODE_MONITOR at BOARD_CAN_DEFAULT_BITRATE. */
void can_init(void);

/* Switch to a non-transmitting mode: CAN_MODE_OFF or CAN_MODE_MONITOR.
 * Any other mode is refused. Also the way to change bitrate. */
int can_set_listen_mode(uint8_t ch, can_mode_t mode, uint32_t bitrate);

/* !!! Enter CAN_MODE_NORMAL (TX-capable). Only call from an explicit user
 * command that names this channel. Never call it automatically. !!! */
int can_enable_tx(uint8_t ch, uint32_t bitrate);

/* Choose Rs low/high for monitor mode (see can_rs_listen_t). Takes effect
 * immediately if the channel is monitoring; never affects TX-capable modes. */
int can_set_rs_listen(uint8_t ch, can_rs_listen_t v);

/* Internal loopback for the self-test: frames never leave the chip. */
int can_set_loopback(uint8_t ch, uint32_t bitrate);

/* Queue a frame. Refused (CAN_ERR_MODE) unless the channel is NORMAL or LOOPBACK. */
int can_send(uint8_t ch, const can_frame_t *f);

/* Received frames from both channels, in arrival order. */
bool can_pop(can_frame_t *f);
void can_flush_rx(void);
uint32_t can_ring_dropped(void);   /* frames lost because the main loop fell behind */

/* Call from the main loop. Handles bus-off: the channel is put back in
 * CAN_MODE_MONITOR (never back to NORMAL). Returns a bitmask of channels that
 * just went bus-off, so the caller can warn the user. */
uint8_t can_poll(void);

/* True once can_enable_tx() has been called since boot, even if the channel
 * has since gone back to monitor mode. The sleep policy uses it (lib/power.h). */
bool can_tx_ever_enabled(void);

/* ---- sleep (src/sleep.c) ----
 * can_sleep_enter(): remember each channel's mode/bitrate, put the transceivers
 * in standby (Rs high), stop both controllers, and park the pins (TX driven
 * recessive, RX as a GPIO input with pull-up, ready for a wake-up trigger).
 * can_sleep_exit(): bring every channel that was listening back in
 * CAN_MODE_MONITOR through the normal configure path (Rs low only after the
 * controller runs). Never restores a TX-capable mode. */
typedef struct {
    can_mode_t mode[CAN_NUM_CHANNELS];     /* CAN_MODE_OFF or CAN_MODE_MONITOR */
    uint32_t   bitrate[CAN_NUM_CHANNELS];
} can_sleep_state_t;
void can_sleep_enter(can_sleep_state_t *saved);
void can_sleep_exit(const can_sleep_state_t *saved);
bool can_rx_pending(void);   /* frames waiting in the RX ring */

const can_chan_info_t *can_info(uint8_t ch);
void can_bus_state(uint8_t ch, can_bus_state_t *st);
const char *can_mode_name(can_mode_t m);

#endif
