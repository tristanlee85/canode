#include "test.h"
#include "parse.h"

void test_parse(void)
{
    uint32_t v;
    CHECK(parse_u32("0", &v) && v == 0);
    CHECK(parse_u32("4294967295", &v) && v == 4294967295u);
    CHECK(!parse_u32("4294967296", &v));
    CHECK(parse_u32("0x1F", &v) && v == 0x1F);
    CHECK(!parse_u32("12a", &v));
    CHECK(!parse_u32("", &v));

    CHECK(parse_hex_u32("7df", &v) && v == 0x7DF);
    CHECK(parse_hex_u32("1FFFFFFF", &v) && v == 0x1FFFFFFF);
    CHECK(!parse_hex_u32("123456789", &v));
    CHECK(!parse_hex_u32("xyz", &v));

    CHECK(parse_bitrate("500000", &v) && v == 500000);
    CHECK(parse_bitrate("500k", &v) && v == 500000);
    CHECK(parse_bitrate("125K", &v) && v == 125000);
    CHECK(parse_bitrate("1M", &v) && v == 1000000);
    CHECK(parse_bitrate("83.333k", &v) && v == 83333);
    CHECK(parse_bitrate("33.3k", &v) && v == 33300);
    CHECK(!parse_bitrate("2M", &v));
    CHECK(!parse_bitrate("0", &v));
    CHECK(!parse_bitrate("k", &v));
    CHECK(!parse_bitrate("500kb", &v));
    CHECK(!parse_bitrate("1.2345k", &v));
    CHECK(!parse_bitrate("1.k", &v));

    uint8_t ch, mask;
    CHECK(parse_channel("can1", &ch) && ch == 0);
    CHECK(parse_channel("can2", &ch) && ch == 1);
    CHECK(!parse_channel("1", &ch));      /* must name the channel */
    CHECK(!parse_channel("can3", &ch));
    CHECK(!parse_channel("all", &ch));
    CHECK(parse_channel_mask("all", &mask) && mask == 3);
    CHECK(parse_channel_mask("can2", &mask) && mask == 2);
    CHECK(!parse_channel_mask("both", &mask));

    uint64_t us;
    CHECK(parse_epoch_us("1699999999", &us) && us == 1699999999000000ull);
    CHECK(parse_epoch_us("1699999999.25", &us) && us == 1699999999250000ull);
    CHECK(parse_epoch_us("1.1234567", &us) && us == 1123456ull);   /* extra digits truncated */
    CHECK(!parse_epoch_us("1.", &us));
    CHECK(!parse_epoch_us("abc", &us));
    CHECK(!parse_epoch_us("12x", &us));
}
