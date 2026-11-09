#include "test.h"
#include "bittiming.h"

#define FDCAN_CLK 40000000u

static void expect(uint32_t rate, unsigned brp, unsigned tq, unsigned tseg1, unsigned tseg2)
{
    can_bittiming_t bt;
    CHECK_EQ(can_bittiming_calc(FDCAN_CLK, rate, 875, &bt), 0);
    CHECK_EQ(bt.brp, brp);
    CHECK_EQ(bt.tq_per_bit, tq);
    CHECK_EQ(bt.tseg1, tseg1);
    CHECK_EQ(bt.tseg2, tseg2);
    CHECK_EQ(bt.sjw, tseg2);
    CHECK_EQ(bt.sp_permille, 875);
    CHECK_EQ(bt.bitrate, rate);
    CHECK_EQ(bt.err_ppm, 0);
    /* The register fields must add up to the bit time. */
    CHECK_EQ(1u + bt.tseg1 + bt.tseg2, bt.tq_per_bit);
    CHECK_EQ((uint64_t)FDCAN_CLK, (uint64_t)bt.brp * bt.tq_per_bit * rate);
}

void test_bittiming(void)
{
    /* The table documented in bittiming.h and firmware/README.md. */
    expect(125000, 2, 160, 139, 20);
    expect(250000, 1, 160, 139, 20);
    expect(500000, 1, 80, 69, 10);
    expect(1000000, 1, 40, 34, 5);

    /* Every result must respect the FDCAN register limits. */
    static const uint32_t rates[] = {10000, 20000, 33333, 50000, 83333, 100000, 125000,
                                     250000, 500000, 800000, 1000000};
    for (unsigned i = 0; i < sizeof(rates) / sizeof(rates[0]); i++) {
        can_bittiming_t bt;
        CHECK_EQ(can_bittiming_calc(FDCAN_CLK, rates[i], 875, &bt), 0);
        CHECK(bt.brp >= BT_BRP_MIN && bt.brp <= BT_BRP_MAX);
        CHECK(bt.tseg1 >= BT_TSEG1_MIN && bt.tseg1 <= BT_TSEG1_MAX);
        CHECK(bt.tseg2 >= BT_TSEG2_MIN && bt.tseg2 <= BT_TSEG2_MAX);
        CHECK(bt.sjw >= 1 && bt.sjw <= bt.tseg2);
        CHECK(bt.tq_per_bit >= BT_TQ_MIN);
        CHECK(bt.err_ppm <= BT_MAX_ERR_PPM);
        CHECK(bt.sp_permille >= 860 && bt.sp_permille <= 890);
    }

    /* 83.333k (an odd legacy rate) is not an exact divisor; small error is fine. */
    can_bittiming_t bt;
    CHECK_EQ(can_bittiming_calc(FDCAN_CLK, 83333, 875, &bt), 0);
    CHECK(bt.err_ppm < 10);

    /* Different sample point. */
    CHECK_EQ(can_bittiming_calc(FDCAN_CLK, 500000, 800, &bt), 0);
    CHECK_EQ(bt.sp_permille, 800);

    /* Impossible requests. */
    CHECK_EQ(can_bittiming_calc(FDCAN_CLK, 0, 875, &bt), -1);
    CHECK_EQ(can_bittiming_calc(FDCAN_CLK, 8000000, 875, &bt), -1);   /* < 8 tq per bit */
    CHECK_EQ(can_bittiming_calc(FDCAN_CLK, 500000, 1000, &bt), -1);
    CHECK_EQ(can_bittiming_calc(FDCAN_CLK, 500000, 875, NULL), -1);
    CHECK_EQ(can_bittiming_calc(FDCAN_CLK, 3000000, 875, &bt), -1);  /* 13.3 tq: 0.25 % off at best */

    /* HSI16 fallback / Nucleo also feeds 40 MHz, but check a 16 MHz kernel works too. */
    CHECK_EQ(can_bittiming_calc(16000000u, 500000, 875, &bt), 0);
    CHECK_EQ(bt.tq_per_bit, 32);
    CHECK_EQ(bt.sp_permille, 875);
}
