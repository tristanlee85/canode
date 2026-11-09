#include "test.h"
#include "candump.h"

static const char *fmt(const can_frame_t *f, uint64_t off)
{
    static char buf[CANDUMP_LINE_MAX + 1];
    size_t n = candump_format(buf, CANDUMP_LINE_MAX, f, off);
    buf[n] = '\0';
    return buf;
}

void test_candump(void)
{
    can_frame_t f = {0};

    /* Matches the example in the task and tools/canlog's CANDUMP_RE. */
    f.ts_us = 1699999999123456ull;
    f.chan = 0;
    f.id = 0x123;
    f.len = 4;
    f.data[0] = 0xDE; f.data[1] = 0xAD; f.data[2] = 0xBE; f.data[3] = 0xEF;
    CHECK_STR(fmt(&f, 0), "(1699999999.123456) can1 123#DEADBEEF\n");

    /* Epoch offset is added; microseconds are zero padded. */
    f.ts_us = 5;
    CHECK_STR(fmt(&f, 1000000ull), "(1.000005) can1 123#DEADBEEF\n");

    /* Standard IDs are always 3 digits (canlog decides ext by length > 3). */
    f.ts_us = 0;
    f.id = 0x7;
    f.len = 0;
    CHECK_STR(fmt(&f, 0), "(0.000000) can1 007#\n");

    /* Extended: 8 digits, channel 2. Same frame as tools/canlog/tests/sample.log. */
    f.chan = 1;
    f.flags = CAN_FLAG_EXT;
    f.id = 0x10244060;
    f.len = 3;
    f.data[0] = 0xAA; f.data[1] = 0xBB; f.data[2] = 0xCC;
    f.ts_us = 1794197037283207ull;
    CHECK_STR(fmt(&f, 0), "(1794197037.283207) can2 10244060#AABBCC\n");

    /* Small extended ID keeps its leading zeros. */
    f.id = 0x123;
    f.ts_us = 0;
    f.len = 0;
    CHECK_STR(fmt(&f, 0), "(0.000000) can2 00000123#\n");

    /* Remote frames. */
    f.flags = CAN_FLAG_RTR;
    f.id = 0x7DF;
    f.len = 0;
    CHECK_STR(fmt(&f, 0), "(0.000000) can2 7DF#R\n");
    f.len = 4;
    CHECK_STR(fmt(&f, 0), "(0.000000) can2 7DF#R4\n");

    /* Worst case fits in CANDUMP_LINE_MAX, and too-small buffers are refused. */
    f.flags = CAN_FLAG_EXT;
    f.id = 0x1FFFFFFF;
    f.len = 8;
    memset(f.data, 0xFF, 8);
    f.ts_us = UINT64_MAX;
    char big[CANDUMP_LINE_MAX];
    size_t n = candump_format(big, sizeof(big), &f, 0);
    CHECK(n > 0 && n <= CANDUMP_LINE_MAX);
    char small[10];
    CHECK_EQ(candump_format(small, sizeof(small), &f, 0), 0);

    /* Parsing (used by the "send" command). */
    can_frame_t p;
    CHECK(candump_parse_frame("123#DEADBEEF", &p));
    CHECK_EQ(p.id, 0x123);
    CHECK_EQ(p.flags, 0);
    CHECK_EQ(p.len, 4);
    CHECK_EQ(p.data[3], 0xEF);

    CHECK(candump_parse_frame("18daf110#0211", &p));
    CHECK_EQ(p.id, 0x18DAF110);
    CHECK_EQ(p.flags, CAN_FLAG_EXT);
    CHECK_EQ(p.len, 2);

    CHECK(candump_parse_frame("00000123#", &p));
    CHECK_EQ(p.flags, CAN_FLAG_EXT);
    CHECK_EQ(p.len, 0);

    CHECK(candump_parse_frame("123#11.22.33", &p));
    CHECK_EQ(p.len, 3);
    CHECK_EQ(p.data[2], 0x33);

    CHECK(candump_parse_frame("7DF#R", &p));
    CHECK_EQ(p.flags, CAN_FLAG_RTR);
    CHECK_EQ(p.len, 0);
    CHECK(candump_parse_frame("7DF#R8", &p));
    CHECK_EQ(p.len, 8);

    CHECK(!candump_parse_frame("800#00", &p));          /* > 0x7FF for 3 digits */
    CHECK(!candump_parse_frame("20000000#00", &p));     /* > 29 bits */
    CHECK(!candump_parse_frame("123456789#00", &p));    /* 9 digits */
    CHECK(!candump_parse_frame("123#0", &p));           /* odd nibble */
    CHECK(!candump_parse_frame("123#001122334455667788", &p)); /* 9 bytes */
    CHECK(!candump_parse_frame("123", &p));
    CHECK(!candump_parse_frame("#00", &p));
    CHECK(!candump_parse_frame("12G#00", &p));
    CHECK(!candump_parse_frame("123#R9", &p));

    /* Round trip. */
    CHECK(candump_parse_frame("1ABCDEF0#0102030405060708", &p));
    p.chan = 1;
    p.ts_us = 42;
    CHECK_STR(fmt(&p, 0), "(0.000042) can2 1ABCDEF0#0102030405060708\n");

    char u[21];
    u[fmt_u64(u, 0)] = '\0';
    CHECK_STR(u, "0");
    u[fmt_u64(u, UINT64_MAX)] = '\0';
    CHECK_STR(u, "18446744073709551615");
}
