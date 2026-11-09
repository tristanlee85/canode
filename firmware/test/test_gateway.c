#include "test.h"
#include "gateway.h"

static bool add(gw_table_t *t, const char *spec)
{
    char buf[128];
    snprintf(buf, sizeof(buf), "%s", spec);
    char *argv[12];
    int argc = 0;
    for (char *p = strtok(buf, " "); p && argc < 12; p = strtok(NULL, " "))
        argv[argc++] = p;
    gw_rule_t r;
    const char *err = NULL;
    if (!gw_rule_parse(argc, argv, &r, &err))
        return false;
    return gw_rule_add(t, &r) >= 0;
}

static can_frame_t frame(uint8_t chan, uint32_t id, bool ext, uint8_t len)
{
    can_frame_t f = {0};
    f.chan = chan;
    f.id = id;
    f.flags = ext ? CAN_FLAG_EXT : 0;
    f.len = len;
    for (uint8_t i = 0; i < len; i++)
        f.data[i] = (uint8_t)(0x10 * i + i);  /* 00 11 22 33 ... */
    return f;
}

static const char *show(const gw_rule_t *r)
{
    static char buf[96];
    gw_rule_format(r, buf, sizeof(buf));
    return buf;
}

void test_gateway(void)
{
    static gw_table_t t;  /* static: zero-initialised and off the stack */
    gw_init(&t);

    /* Empty table = transparent. */
    can_frame_t f = frame(0, 0x123, false, 8);
    CHECK(gw_process(&t, &f));
    CHECK_EQ(f.id, 0x123);
    CHECK_EQ(f.data[7], 0x77);

    CHECK(add(&t, "can1 123 drop"));
    CHECK(add(&t, "any 3B3 rewrite data=....0."));
    CHECK(add(&t, "can2 18DAF100/1FFFFF00 rewrite id=18DAF1FF"));
    CHECK(add(&t, "can1 * pass"));
    CHECK(add(&t, "can2 7E0 rewrite id=7E8 data=02"));
    CHECK_EQ(gw_rule_count(&t), 5);

    /* Drop only applies to the named direction. */
    f = frame(0, 0x123, false, 8);
    CHECK(!gw_process(&t, &f));
    f = frame(1, 0x123, false, 8);
    CHECK(gw_process(&t, &f));
    CHECK_EQ(t.rules[0].hits, 1);

    /* Standard rule does not match an extended frame with the same number. */
    f = frame(0, 0x123, true, 1);
    CHECK(gw_process(&t, &f));

    /* Nibble rewrite: byte 2 high nibble cleared (0x22 -> 0x02). */
    f = frame(1, 0x3B3, false, 8);
    CHECK(gw_process(&t, &f));
    CHECK_EQ(f.data[1], 0x11);
    CHECK_EQ(f.data[2], 0x02);
    CHECK_EQ(f.data[3], 0x33);
    /* Pattern longer than the frame: no bytes are added. */
    f = frame(0, 0x3B3, false, 2);
    CHECK(gw_process(&t, &f));
    CHECK_EQ(f.len, 2);

    /* Masked extended match + ID rewrite. */
    f = frame(1, 0x18DAF110, true, 2);
    CHECK(gw_process(&t, &f));
    CHECK_EQ(f.id, 0x18DAF1FF);
    CHECK(f.flags & CAN_FLAG_EXT);
    f = frame(1, 0x18DAF210, true, 2);   /* outside the mask */
    CHECK(gw_process(&t, &f));
    CHECK_EQ(f.id, 0x18DAF210);

    /* ID and data together; RTR frames keep their (empty) data. */
    f = frame(1, 0x7E0, false, 3);
    CHECK(gw_process(&t, &f));
    CHECK_EQ(f.id, 0x7E8);
    CHECK_EQ(f.data[0], 0x02);
    CHECK_EQ(f.data[1], 0x11);
    f = frame(1, 0x7E0, false, 0);
    f.flags |= CAN_FLAG_RTR;
    f.len = 8;
    CHECK(gw_process(&t, &f));
    CHECK_EQ(f.data[0], 0x00);

    /* Formatting round-trips the syntax. */
    CHECK_STR(show(&t.rules[0]), "can1 123 drop");
    CHECK_STR(show(&t.rules[1]), "any 3B3 rewrite data=....0.");
    CHECK_STR(show(&t.rules[2]), "can2 18DAF100/1FFFFF00 rewrite id=18DAF1FF");
    CHECK_STR(show(&t.rules[3]), "can1 * pass");
    CHECK_STR(show(&t.rules[4]), "can2 7E0 rewrite id=7E8 data=02");

    /* Delete keeps order. */
    CHECK(gw_rule_del(&t, 0));
    CHECK_EQ(gw_rule_count(&t), 4);
    CHECK_STR(show(&t.rules[0]), "any 3B3 rewrite data=....0.");
    CHECK(!gw_rule_del(&t, 4));
    f = frame(0, 0x123, false, 1);
    CHECK(gw_process(&t, &f));   /* the drop rule is gone */

    /* Table full. */
    gw_init(&t);
    for (unsigned i = 0; i < GW_MAX_RULES; i++)
        CHECK(add(&t, "any * pass"));
    CHECK(!add(&t, "any * pass"));

    /* Parse errors. */
    gw_init(&t);
    CHECK(!add(&t, "can3 123 drop"));
    CHECK(!add(&t, "can1 800 drop"));           /* 3 digits but > 0x7FF */
    CHECK(!add(&t, "can1 123 forward"));
    CHECK(!add(&t, "can1 123 rewrite"));         /* nothing to rewrite */
    CHECK(!add(&t, "can1 123 drop data=00"));    /* options only for rewrite */
    CHECK(!add(&t, "can1 123 rewrite data=0"));  /* odd length */
    CHECK(!add(&t, "can1 123 rewrite data=001122334455667788"));  /* 9 bytes */
    CHECK(!add(&t, "can1 123 rewrite foo=1"));
    CHECK(!add(&t, "can1 123/zz drop"));
    CHECK(!add(&t, "can1"));
    CHECK_EQ(gw_rule_count(&t), 0);
}
