/*
 * can_drv.c - FDCAN1/FDCAN2 driver and transceiver (Rs pin) control.
 *
 * ============================================================================
 *  SAFETY RULES: this board sits on a live vehicle bus. Keep these true.
 * ============================================================================
 *  1. After reset both transceivers are in STANDBY: the 10k pull-ups hold
 *     Rs (PD2 = CAN1, PB2 = CAN2) high, and a standby SN65HVD230 cannot drive
 *     the bus. Firmware drives Rs LOW only AFTER that channel's FDCAN has been
 *     configured and started (see chan_configure()). Every reconfiguration
 *     starts by putting the transceiver back in standby.
 *  2. The default mode for both channels is FDCAN BUS MONITORING: the
 *     controller receives but sends nothing, not even ACKs or error frames.
 *     In monitor mode Rs is driven low or left high per channel
 *     (can_rs_listen_t, default BOARD_CAN_RS_LISTEN_DEFAULT). Rs high adds a
 *     second, hardware no-transmit layer (transceiver driver off).
 *  3. Any mode that can put a dominant bit on the bus (CAN_MODE_NORMAL, which
 *     covers sending frames and gateway forwarding) is entered ONLY through
 *     can_enable_tx(), and can_enable_tx() is called ONLY from an explicit
 *     shell command that names the channel. Never call it automatically: not
 *     at boot, not after a bus-off, not after a self-test, not after a
 *     bitrate change.
 *  4. Anything that resets or recovers a channel leaves it non-transmitting:
 *     bus-off -> MONITOR, bitrate change -> MONITOR, self-test end -> MONITOR.
 *  5. Faults: HardFault_Handler (system.c) drives both Rs pins high, then resets.
 * ============================================================================
 */
#include "can_drv.h"

#include <string.h>

#include "board.h"
#include "frame_ring.h"
#include "stm32g0xx_hal.h"
#include "system.h"

#define SAMPLE_POINT_PERMILLE 875u   /* 87.5 %: see lib/bittiming.h */

typedef struct {
    GPIO_TypeDef *port;
    uint16_t      rx_pin, tx_pin;
    uint8_t       af;
    GPIO_TypeDef *rs_port;
    uint16_t      rs_pin;
} chan_hw_t;

static const chan_hw_t s_hw[CAN_NUM_CHANNELS] = {
    {BOARD_CAN1_PORT, BOARD_CAN1_RX_PIN, BOARD_CAN1_TX_PIN, BOARD_CAN1_AF, BOARD_CAN1_RS_PORT, BOARD_CAN1_RS_PIN},
    {BOARD_CAN2_PORT, BOARD_CAN2_RX_PIN, BOARD_CAN2_TX_PIN, BOARD_CAN2_AF, BOARD_CAN2_RS_PORT, BOARD_CAN2_RS_PIN},
};

static FDCAN_HandleTypeDef s_h[CAN_NUM_CHANNELS];
static can_chan_info_t     s_info[CAN_NUM_CHANNELS];
static bool                s_pins_muxed[CAN_NUM_CHANNELS];
static volatile bool       s_busoff_pending[CAN_NUM_CHANNELS];
static frame_ring_t        s_ring;

/* ---- transceiver ---------------------------------------------------------- */

static void rs_standby(uint8_t ch)
{
    HAL_GPIO_WritePin(s_hw[ch].rs_port, s_hw[ch].rs_pin, GPIO_PIN_SET);
}

static void rs_active(uint8_t ch)
{
    HAL_GPIO_WritePin(s_hw[ch].rs_port, s_hw[ch].rs_pin, GPIO_PIN_RESET);
}

/* ---- configuration -------------------------------------------------------- */

static uint32_t hal_mode(can_mode_t m)
{
    switch (m) {
    case CAN_MODE_NORMAL:   return FDCAN_MODE_NORMAL;
    case CAN_MODE_LOOPBACK: return FDCAN_MODE_INTERNAL_LOOPBACK;
    case CAN_MODE_MONITOR:
    default:                return FDCAN_MODE_BUS_MONITORING;
    }
}

/* The only function that starts a controller. Order matters, see rule 1. */
static int chan_configure(uint8_t ch, can_mode_t mode, uint32_t bitrate)
{
    can_bittiming_t bt;
    if (can_bittiming_calc(FDCAN_KERNEL_HZ, bitrate, SAMPLE_POINT_PERMILLE, &bt) != 0)
        return CAN_ERR_BITRATE;

    /* 1. Transceiver off the bus before touching the controller. */
    rs_standby(ch);

    /* Both FDCANs share one interrupt; keep it quiet while the handle changes. */
    NVIC_DisableIRQ(TIM16_FDCAN_IT0_IRQn);

    FDCAN_HandleTypeDef *h = &s_h[ch];
    if (h->State != HAL_FDCAN_STATE_RESET)
        (void)HAL_FDCAN_DeInit(h);   /* stops it: CCCR.INIT=1, TX pin recessive */
    s_info[ch].mode = CAN_MODE_OFF;
    s_info[ch].bitrate = bitrate;
    s_info[ch].bt = bt;
    s_busoff_pending[ch] = false;

    int rc = CAN_OK;
    if (mode == CAN_MODE_OFF)
        goto out;

    /* 2. Configure the controller. */
    h->Instance = ch == 0 ? FDCAN1 : FDCAN2;
    h->Init.ClockDivider = FDCAN_CLOCK_DIV1;   /* shared by both; written via FDCAN1 */
    h->Init.FrameFormat = FDCAN_FRAME_CLASSIC;
    h->Init.Mode = hal_mode(mode);
    /* Standard CAN behaviour: retry after lost arbitration or errors. */
    h->Init.AutoRetransmission = ENABLE;
    h->Init.TransmitPause = DISABLE;
    h->Init.ProtocolException = DISABLE;
    h->Init.NominalPrescaler = bt.brp;
    h->Init.NominalSyncJumpWidth = bt.sjw;
    h->Init.NominalTimeSeg1 = bt.tseg1;
    h->Init.NominalTimeSeg2 = bt.tseg2;
    h->Init.DataPrescaler = 1;        /* data phase unused (classic CAN) */
    h->Init.DataSyncJumpWidth = 1;
    h->Init.DataTimeSeg1 = 1;
    h->Init.DataTimeSeg2 = 1;
    h->Init.StdFiltersNbr = 0;        /* no filter elements: the global filter takes everything */
    h->Init.ExtFiltersNbr = 0;
    h->Init.TxFifoQueueMode = FDCAN_TX_FIFO_OPERATION;
    if (HAL_FDCAN_Init(h) != HAL_OK) {
        rc = CAN_ERR_HAL;
        goto out;
    }

    /* Mux TX/RX to the FDCAN only now, while the controller is in INIT and
     * holding TX recessive, so the pin never glitches dominant. */
    if (!s_pins_muxed[ch]) {
        GPIO_InitTypeDef gpio = {0};
        gpio.Pin = s_hw[ch].rx_pin | s_hw[ch].tx_pin;
        gpio.Mode = GPIO_MODE_AF_PP;
        gpio.Pull = GPIO_NOPULL;
        gpio.Speed = GPIO_SPEED_FREQ_LOW;   /* 1 Mbit/s needs nothing faster; less EMI */
        gpio.Alternate = s_hw[ch].af;
        HAL_GPIO_Init(s_hw[ch].port, &gpio);
        s_pins_muxed[ch] = true;
    }

    /* The G0's message RAM has only 3 RX slots per FIFO. Sending standard IDs to
     * FIFO0 and extended IDs to FIFO1 doubles the buffering on mixed buses. */
    if (HAL_FDCAN_ConfigGlobalFilter(h, FDCAN_ACCEPT_IN_RX_FIFO0, FDCAN_ACCEPT_IN_RX_FIFO1,
                                     FDCAN_FILTER_REMOTE, FDCAN_FILTER_REMOTE) != HAL_OK ||
        HAL_FDCAN_ActivateNotification(h,
                                       FDCAN_IT_RX_FIFO0_NEW_MESSAGE | FDCAN_IT_RX_FIFO0_MESSAGE_LOST |
                                       FDCAN_IT_RX_FIFO1_NEW_MESSAGE | FDCAN_IT_RX_FIFO1_MESSAGE_LOST |
                                       FDCAN_IT_BUS_OFF, 0) != HAL_OK ||
        HAL_FDCAN_Start(h) != HAL_OK) {
        (void)HAL_FDCAN_DeInit(h);
        rc = CAN_ERR_HAL;
        goto out;
    }
    s_info[ch].mode = mode;

    /* 3. Controller configured and running: only now enable the transceiver.
     *    NORMAL is only reachable via can_enable_tx() (explicit user opt-in).
     *    MONITOR follows the per-channel rs_listen setting. Internal loopback
     *    never needs the bus, so it stays in standby. On the Nucleo there is
     *    no transceiver; the pin toggles harmlessly. */
    if (mode == CAN_MODE_NORMAL ||
        (mode == CAN_MODE_MONITOR && s_info[ch].rs_listen == CAN_RS_LISTEN_LOW))
        rs_active(ch);

out:
    NVIC_EnableIRQ(TIM16_FDCAN_IT0_IRQn);
    return rc;
}

void can_init(void)
{
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_GPIOD_CLK_ENABLE();

    /* Rs pins: set the output latch high BEFORE making them outputs, so they go
     * from "input + external pull-up" straight to "driven high": standby. */
    for (uint8_t ch = 0; ch < CAN_NUM_CHANNELS; ch++) {
        rs_standby(ch);
        GPIO_InitTypeDef gpio = {0};
        gpio.Pin = s_hw[ch].rs_pin;
        gpio.Mode = GPIO_MODE_OUTPUT_PP;
        gpio.Pull = GPIO_NOPULL;
        gpio.Speed = GPIO_SPEED_FREQ_LOW;
        HAL_GPIO_Init(s_hw[ch].rs_port, &gpio);
    }

    frame_ring_init(&s_ring);
    memset(s_info, 0, sizeof(s_info));
    for (uint8_t ch = 0; ch < CAN_NUM_CHANNELS; ch++)
        s_info[ch].rs_listen = BOARD_CAN_RS_LISTEN_DEFAULT;

    /* FDCAN kernel clock (PLLQ, 40 MHz) was selected in system_clock_init(). */
    __HAL_RCC_FDCAN_CLK_ENABLE();
    /* Highest priority: the hardware FIFOs are only 3 frames deep. */
    NVIC_SetPriority(TIM16_FDCAN_IT0_IRQn, 0);

    for (uint8_t ch = 0; ch < CAN_NUM_CHANNELS; ch++)
        (void)chan_configure(ch, CAN_MODE_MONITOR, BOARD_CAN_DEFAULT_BITRATE);
}

int can_set_listen_mode(uint8_t ch, can_mode_t mode, uint32_t bitrate)
{
    if (ch >= CAN_NUM_CHANNELS || (mode != CAN_MODE_OFF && mode != CAN_MODE_MONITOR))
        return CAN_ERR_ARG;
    return chan_configure(ch, mode, bitrate);
}

int can_enable_tx(uint8_t ch, uint32_t bitrate)
{
    if (ch >= CAN_NUM_CHANNELS)
        return CAN_ERR_ARG;
    return chan_configure(ch, CAN_MODE_NORMAL, bitrate);
}

int can_set_rs_listen(uint8_t ch, can_rs_listen_t v)
{
    if (ch >= CAN_NUM_CHANNELS || (v != CAN_RS_LISTEN_LOW && v != CAN_RS_LISTEN_HIGH))
        return CAN_ERR_ARG;
    s_info[ch].rs_listen = v;
    /* Only a monitoring channel changes now. Its FDCAN is already configured
     * and running in bus-monitoring mode, so driving Rs low here obeys rule 1. */
    if (s_info[ch].mode == CAN_MODE_MONITOR) {
        if (v == CAN_RS_LISTEN_LOW)
            rs_active(ch);
        else
            rs_standby(ch);
    }
    return CAN_OK;
}

int can_set_loopback(uint8_t ch, uint32_t bitrate)
{
    if (ch >= CAN_NUM_CHANNELS)
        return CAN_ERR_ARG;
    return chan_configure(ch, CAN_MODE_LOOPBACK, bitrate);
}

/* ---- transmit ------------------------------------------------------------- */

int can_send(uint8_t ch, const can_frame_t *f)
{
    if (ch >= CAN_NUM_CHANNELS || f == NULL || f->len > CAN_MAX_DLEN)
        return CAN_ERR_ARG;
    /* Belt and braces for rule 3: the controller would refuse in monitor mode
     * anyway, but don't even queue the frame. */
    if (s_info[ch].mode != CAN_MODE_NORMAL && s_info[ch].mode != CAN_MODE_LOOPBACK)
        return CAN_ERR_MODE;

    FDCAN_TxHeaderTypeDef th = {0};
    th.Identifier = f->id;
    th.IdType = (f->flags & CAN_FLAG_EXT) ? FDCAN_EXTENDED_ID : FDCAN_STANDARD_ID;
    th.TxFrameType = (f->flags & CAN_FLAG_RTR) ? FDCAN_REMOTE_FRAME : FDCAN_DATA_FRAME;
    th.DataLength = f->len;   /* FDCAN_DLC_BYTES_0..8 are the values 0..8 */
    th.ErrorStateIndicator = FDCAN_ESI_ACTIVE;
    th.BitRateSwitch = FDCAN_BRS_OFF;
    th.FDFormat = FDCAN_CLASSIC_CAN;
    th.TxEventFifoControl = FDCAN_NO_TX_EVENTS;
    th.MessageMarker = 0;

    if (HAL_FDCAN_GetTxFifoFreeLevel(&s_h[ch]) == 0u) {
        s_info[ch].tx_full++;
        return CAN_ERR_FULL;
    }
    if (HAL_FDCAN_AddMessageToTxFifoQ(&s_h[ch], &th, f->data) != HAL_OK)
        return CAN_ERR_HAL;
    s_info[ch].tx++;
    return CAN_OK;
}

/* ---- receive (interrupt context) ------------------------------------------- */

static uint8_t chan_of(const FDCAN_HandleTypeDef *h)
{
    return h == &s_h[1] ? 1u : 0u;
}

static void drain_fifo(FDCAN_HandleTypeDef *h, uint32_t fifo)
{
    uint8_t ch = chan_of(h);
    FDCAN_RxHeaderTypeDef hdr;
    uint8_t data[64];   /* HAL copies up to the FD maximum; classic frames use 8 */
    /* One timestamp per interrupt: frames drained together arrived within a
     * few frame times of each other. */
    uint64_t ts = system_time_us();

    while (HAL_FDCAN_GetRxFifoFillLevel(h, fifo) > 0u) {
        if (HAL_FDCAN_GetRxMessage(h, fifo, &hdr, data) != HAL_OK)
            break;
        can_frame_t f;
        f.ts_us = ts;
        f.chan = ch;
        f.id = hdr.Identifier;
        f.flags = (uint8_t)((hdr.IdType == FDCAN_EXTENDED_ID ? CAN_FLAG_EXT : 0u) |
                            (hdr.RxFrameType == FDCAN_REMOTE_FRAME ? CAN_FLAG_RTR : 0u));
        /* Classic CAN: DLC 9..15 still means 8 data bytes. */
        f.len = (uint8_t)(hdr.DataLength > CAN_MAX_DLEN ? CAN_MAX_DLEN : hdr.DataLength);
        memcpy(f.data, data, CAN_MAX_DLEN);
        if (f.flags & CAN_FLAG_RTR)
            memset(f.data, 0, CAN_MAX_DLEN);
        s_info[ch].rx++;
        (void)frame_ring_push(&s_ring, &f);   /* counts its own drops */
    }
}

void HAL_FDCAN_RxFifo0Callback(FDCAN_HandleTypeDef *h, uint32_t its)
{
    if (its & FDCAN_IT_RX_FIFO0_MESSAGE_LOST)
        s_info[chan_of(h)].hw_lost++;
    drain_fifo(h, FDCAN_RX_FIFO0);
}

void HAL_FDCAN_RxFifo1Callback(FDCAN_HandleTypeDef *h, uint32_t its)
{
    if (its & FDCAN_IT_RX_FIFO1_MESSAGE_LOST)
        s_info[chan_of(h)].hw_lost++;
    drain_fifo(h, FDCAN_RX_FIFO1);
}

void HAL_FDCAN_ErrorStatusCallback(FDCAN_HandleTypeDef *h, uint32_t its)
{
    /* The hardware has already stopped the controller (CCCR.INIT=1) on bus-off.
     * Recovery is left to the main loop: see can_poll(). */
    if ((its & FDCAN_IT_BUS_OFF) && (h->Instance->PSR & FDCAN_PSR_BO))
        s_busoff_pending[chan_of(h)] = true;
}

/* FDCAN1 and FDCAN2 interrupt line 0 (shared with TIM16, which we don't use). */
void TIM16_FDCAN_IT0_IRQHandler(void)
{
    for (uint8_t ch = 0; ch < CAN_NUM_CHANNELS; ch++) {
        if (s_h[ch].State != HAL_FDCAN_STATE_RESET)
            HAL_FDCAN_IRQHandler(&s_h[ch]);
    }
}

/* ---- main-loop API --------------------------------------------------------- */

bool can_pop(can_frame_t *f)
{
    return frame_ring_pop(&s_ring, f);
}

void can_flush_rx(void)
{
    can_frame_t f;
    while (frame_ring_pop(&s_ring, &f)) {
    }
}

uint32_t can_ring_dropped(void)
{
    return s_ring.dropped;
}

uint8_t can_poll(void)
{
    uint8_t went_off = 0;
    for (uint8_t ch = 0; ch < CAN_NUM_CHANNELS; ch++) {
        if (!s_busoff_pending[ch])
            continue;
        s_busoff_pending[ch] = false;
        s_info[ch].bus_off++;
        went_off |= (uint8_t)(1u << ch);
        /* Rule 4: recover into MONITOR, never back into NORMAL. */
        (void)chan_configure(ch, CAN_MODE_MONITOR, s_info[ch].bitrate);
    }
    return went_off;
}

const can_chan_info_t *can_info(uint8_t ch)
{
    return &s_info[ch < CAN_NUM_CHANNELS ? ch : 0];
}

void can_bus_state(uint8_t ch, can_bus_state_t *st)
{
    memset(st, 0, sizeof(*st));
    if (ch >= CAN_NUM_CHANNELS || s_h[ch].State == HAL_FDCAN_STATE_RESET)
        return;
    FDCAN_ProtocolStatusTypeDef ps;
    FDCAN_ErrorCountersTypeDef ec;
    if (HAL_FDCAN_GetProtocolStatus(&s_h[ch], &ps) == HAL_OK) {
        st->bus_off = ps.BusOff != 0u;
        st->error_passive = ps.ErrorPassive != 0u;
        st->warning = ps.Warning != 0u;
        st->last_error = (uint8_t)ps.LastErrorCode;
    }
    if (HAL_FDCAN_GetErrorCounters(&s_h[ch], &ec) == HAL_OK) {
        st->tec = (uint8_t)ec.TxErrorCnt;
        st->rec = (uint8_t)ec.RxErrorCnt;
    }
}

const char *can_mode_name(can_mode_t m)
{
    switch (m) {
    case CAN_MODE_OFF:      return "off";
    case CAN_MODE_MONITOR:  return "monitor";
    case CAN_MODE_NORMAL:   return "NORMAL(tx)";
    case CAN_MODE_LOOPBACK: return "loopback";
    default:                return "?";
    }
}
