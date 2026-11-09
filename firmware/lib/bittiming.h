/*
 * bittiming.h - classic-CAN nominal bit timing for the STM32G0 FDCAN (Bosch M_CAN).
 *
 * A bit is split into time quanta (tq):  | SYNC (1 tq) | TSEG1 | TSEG2 |
 *                                                              ^ sample point
 *   tq       = prescaler / f_kernel
 *   bit time = (1 + TSEG1 + TSEG2) tq
 *   sample   = (1 + TSEG1) / (1 + TSEG1 + TSEG2)
 *
 * With f_kernel = 40 MHz (PLLQ) and an 87.5 % target (CiA 301 recommendation for
 * <= 800 kbit/s, and what the vehicle networks use), the calculator gives:
 *
 *   bitrate  BRP  tq/bit  TSEG1  TSEG2  SJW  sample point
 *   125k      2    160     139     20    20   87.5 %
 *   250k      1    160     139     20    20   87.5 %
 *   500k      1     80      69     10    10   87.5 %
 *   1M        1     40      34      5     5   87.5 %
 *
 * (125k needs BRP 2 because 320 tq at BRP 1 would need TSEG1 = 279 > 256.)
 * The smallest prescaler is preferred: finer tq means a more exact sample point,
 * which is also what CiA 601 recommends for FD-capable controllers.
 * SJW = TSEG2 gives the widest resynchronisation range, which helps with
 * slightly-off clocks on other nodes.
 */
#ifndef BITTIMING_H
#define BITTIMING_H

#include <stdint.h>

/* FDCAN nominal bit timing limits (RM0444, FDCAN_NBTP). */
#define BT_BRP_MIN     1u
#define BT_BRP_MAX     512u
#define BT_TSEG1_MIN   2u
#define BT_TSEG1_MAX   256u
#define BT_TSEG2_MIN   2u
#define BT_TSEG2_MAX   128u
#define BT_SJW_MAX     128u
#define BT_TQ_MIN      8u     /* ISO 11898-1: at least 8 tq per bit */

/* Largest bitrate error accepted: 0.1 % (CAN nodes tolerate ~0.5 % total). */
#define BT_MAX_ERR_PPM 1000u

typedef struct {
    uint16_t brp;          /* prescaler */
    uint16_t tseg1;        /* PROP_SEG + PHASE_SEG1, in tq */
    uint16_t tseg2;        /* PHASE_SEG2, in tq */
    uint16_t sjw;          /* resync jump width, in tq */
    uint16_t tq_per_bit;   /* 1 + tseg1 + tseg2 */
    uint16_t sp_permille;  /* achieved sample point, 875 = 87.5 % */
    uint32_t bitrate;      /* achieved bitrate, bit/s */
    uint32_t err_ppm;      /* |achieved - requested| / requested, parts per million */
} can_bittiming_t;

/*
 * Compute nominal bit timing. Returns 0 on success, -1 if no valid setting
 * exists within BT_MAX_ERR_PPM.
 */
int can_bittiming_calc(uint32_t clk_hz, uint32_t bitrate, uint16_t sp_permille,
                       can_bittiming_t *out);

#endif
