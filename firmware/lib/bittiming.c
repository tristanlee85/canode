#include "bittiming.h"

#include <stddef.h>

static uint32_t udiv_round(uint64_t num, uint64_t den)
{
    return (uint32_t)((num + den / 2u) / den);
}

int can_bittiming_calc(uint32_t clk_hz, uint32_t bitrate, uint16_t sp_permille,
                       can_bittiming_t *out)
{
    if (out == NULL || clk_hz == 0u || bitrate == 0u || sp_permille == 0u || sp_permille >= 1000u)
        return -1;

    int found = 0;
    can_bittiming_t best = {0};
    uint32_t best_sp_err = 0;

    for (uint32_t brp = BT_BRP_MIN; brp <= BT_BRP_MAX; brp++) {
        uint32_t tq = udiv_round(clk_hz, (uint64_t)brp * bitrate);
        if (tq < BT_TQ_MIN)
            break;  /* larger prescalers only make it worse */
        if (tq > 1u + BT_TSEG1_MAX + BT_TSEG2_MAX)
            continue;

        /* Sample point position in tq, counted from the start of the bit. */
        uint32_t sample = udiv_round((uint64_t)tq * sp_permille, 1000u);
        uint32_t tseg2 = tq - sample;
        if (tseg2 < BT_TSEG2_MIN) {
            tseg2 = BT_TSEG2_MIN;
            sample = tq - tseg2;
        }
        uint32_t tseg1 = sample - 1u;
        if (tseg1 < BT_TSEG1_MIN || tseg1 > BT_TSEG1_MAX || tseg2 > BT_TSEG2_MAX)
            continue;

        uint32_t actual = udiv_round(clk_hz, (uint64_t)brp * tq);
        uint32_t diff = actual > bitrate ? actual - bitrate : bitrate - actual;
        uint32_t err_ppm = udiv_round((uint64_t)diff * 1000000u, bitrate);
        if (err_ppm > BT_MAX_ERR_PPM)
            continue;

        uint32_t sp_achieved = udiv_round((uint64_t)sample * 1000u, tq);
        uint32_t sp_err = sp_achieved > sp_permille ? sp_achieved - sp_permille
                                                    : sp_permille - sp_achieved;

        /* Prefer: lowest bitrate error, then closest sample point, then the
         * smallest prescaler (we iterate upwards, so keep the first on ties). */
        if (!found || err_ppm < best.err_ppm ||
            (err_ppm == best.err_ppm && sp_err < best_sp_err)) {
            found = 1;
            best_sp_err = sp_err;
            best.brp = (uint16_t)brp;
            best.tseg1 = (uint16_t)tseg1;
            best.tseg2 = (uint16_t)tseg2;
            best.sjw = (uint16_t)(tseg2 < BT_SJW_MAX ? tseg2 : BT_SJW_MAX);
            best.tq_per_bit = (uint16_t)tq;
            best.sp_permille = (uint16_t)sp_achieved;
            best.bitrate = actual;
            best.err_ppm = err_ppm;
        }
    }

    if (!found)
        return -1;
    *out = best;
    return 0;
}
