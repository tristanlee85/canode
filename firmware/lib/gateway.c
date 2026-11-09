#include "gateway.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "parse.h"

void gw_init(gw_table_t *t)
{
    memset(t, 0, sizeof(*t));
}

static bool rule_matches(const gw_rule_t *r, const can_frame_t *f)
{
    if (!(r->from_mask & (1u << f->chan)))
        return false;
    bool ext = (f->flags & CAN_FLAG_EXT) != 0;
    if (r->idtype == GW_MATCH_STD && ext)
        return false;
    if (r->idtype == GW_MATCH_EXT && !ext)
        return false;
    return (f->id & r->id_mask) == (r->id & r->id_mask);
}

bool gw_process(gw_table_t *t, can_frame_t *f)
{
    for (unsigned i = 0; i < GW_MAX_RULES; i++) {
        gw_rule_t *r = &t->rules[i];
        if (!r->used)
            break;
        if (!rule_matches(r, f))
            continue;
        r->hits++;
        switch (r->action) {
        case GW_DROP:
            return false;
        case GW_REWRITE:
            if (r->set_id)
                f->id = r->new_id & ((f->flags & CAN_FLAG_EXT) ? CAN_EXT_ID_MAX : CAN_STD_ID_MAX);
            if (!(f->flags & CAN_FLAG_RTR)) {
                for (unsigned b = 0; b < f->len && b < CAN_MAX_DLEN; b++)
                    f->data[b] = (uint8_t)((f->data[b] & ~r->data_mask[b]) | (r->data_val[b] & r->data_mask[b]));
            }
            return true;
        case GW_PASS:
        default:
            return true;
        }
    }
    return true;  /* no rule: transparent */
}

static int hexval(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static bool parse_data_pattern(const char *s, gw_rule_t *r)
{
    size_t n = strlen(s);
    if (n == 0 || n % 2u != 0 || n > 2u * CAN_MAX_DLEN)
        return false;
    for (size_t i = 0; i < n; i++) {
        unsigned byte = (unsigned)(i / 2u);
        unsigned shift = (i % 2u) ? 0u : 4u;
        if (s[i] == '.')
            continue;
        int v = hexval(s[i]);
        if (v < 0)
            return false;
        r->data_mask[byte] |= (uint8_t)(0xFu << shift);
        r->data_val[byte] |= (uint8_t)((unsigned)v << shift);
    }
    return true;
}

bool gw_rule_parse(int argc, char **argv, gw_rule_t *out, const char **err)
{
    gw_rule_t r;
    memset(&r, 0, sizeof(r));
    r.used = true;

    if (argc < 3) {
        *err = "usage: gw add <can1|can2|any> <id[/mask]|*> <pass|drop|rewrite> [id=..] [data=..]";
        return false;
    }

    if (strcmp(argv[0], "any") == 0) {
        r.from_mask = (uint8_t)((1u << CAN_NUM_CHANNELS) - 1u);
    } else {
        uint8_t ch;
        if (!parse_channel(argv[0], &ch)) {
            *err = "from must be can1, can2 or any";
            return false;
        }
        r.from_mask = (uint8_t)(1u << ch);
    }

    /* match: "*", "ID" or "ID/MASK"; ID width (3 vs >3 digits) picks std/ext */
    if (strcmp(argv[1], "*") == 0) {
        r.idtype = GW_MATCH_ANY;
        r.id = 0;
        r.id_mask = 0;
    } else {
        char idbuf[20];
        size_t n = strlen(argv[1]);
        if (n >= sizeof(idbuf)) {
            *err = "bad id";
            return false;
        }
        memcpy(idbuf, argv[1], n + 1u);
        char *slash = strchr(idbuf, '/');
        if (slash)
            *slash = '\0';
        size_t idlen = strlen(idbuf);
        if (!parse_hex_u32(idbuf, &r.id)) {
            *err = "bad id (hex, 3 digits = standard, 8 = extended)";
            return false;
        }
        r.idtype = idlen > 3 ? GW_MATCH_EXT : GW_MATCH_STD;
        uint32_t full = r.idtype == GW_MATCH_EXT ? CAN_EXT_ID_MAX : CAN_STD_ID_MAX;
        if (r.id > full) {
            *err = "id out of range";
            return false;
        }
        r.id_mask = full;
        if (slash && !parse_hex_u32(slash + 1, &r.id_mask)) {
            *err = "bad mask";
            return false;
        }
        r.id_mask &= full;
    }

    if (strcmp(argv[2], "pass") == 0) {
        r.action = GW_PASS;
    } else if (strcmp(argv[2], "drop") == 0) {
        r.action = GW_DROP;
    } else if (strcmp(argv[2], "rewrite") == 0) {
        r.action = GW_REWRITE;
    } else {
        *err = "action must be pass, drop or rewrite";
        return false;
    }

    for (int i = 3; i < argc; i++) {
        if (r.action != GW_REWRITE) {
            *err = "id=/data= only apply to rewrite";
            return false;
        }
        if (strncmp(argv[i], "id=", 3) == 0) {
            if (!parse_hex_u32(argv[i] + 3, &r.new_id) || r.new_id > CAN_EXT_ID_MAX) {
                *err = "bad id= value";
                return false;
            }
            r.set_id = true;
        } else if (strncmp(argv[i], "data=", 5) == 0) {
            if (!parse_data_pattern(argv[i] + 5, &r)) {
                *err = "bad data= pattern (2 chars per byte, hex digit or '.')";
                return false;
            }
        } else {
            *err = "unknown rewrite option (use id= or data=)";
            return false;
        }
    }
    if (r.action == GW_REWRITE && !r.set_id) {
        bool any = false;
        for (unsigned b = 0; b < CAN_MAX_DLEN; b++)
            any = any || r.data_mask[b] != 0u;
        if (!any) {
            *err = "rewrite needs id= and/or data=";
            return false;
        }
    }

    *out = r;
    return true;
}

unsigned gw_rule_count(const gw_table_t *t)
{
    unsigned n = 0;
    while (n < GW_MAX_RULES && t->rules[n].used)
        n++;
    return n;
}

int gw_rule_add(gw_table_t *t, const gw_rule_t *r)
{
    unsigned n = gw_rule_count(t);
    if (n >= GW_MAX_RULES)
        return -1;
    t->rules[n] = *r;
    t->rules[n].used = true;
    t->rules[n].hits = 0;
    return (int)n;
}

bool gw_rule_del(gw_table_t *t, unsigned idx)
{
    unsigned n = gw_rule_count(t);
    if (idx >= n)
        return false;
    memmove(&t->rules[idx], &t->rules[idx + 1u], (n - idx - 1u) * sizeof(gw_rule_t));
    memset(&t->rules[n - 1u], 0, sizeof(gw_rule_t));
    return true;
}

size_t gw_rule_format(const gw_rule_t *r, char *buf, size_t cap)
{
    static const char HEXC[] = "0123456789ABCDEF";
    const char *from = r->from_mask == 1u ? "can1" : r->from_mask == 2u ? "can2" : "any";
    const char *act = r->action == GW_DROP ? "drop" : r->action == GW_REWRITE ? "rewrite" : "pass";
    char match[24];
    if (r->idtype == GW_MATCH_ANY) {
        snprintf(match, sizeof(match), "*");
    } else {
        bool ext = r->idtype == GW_MATCH_EXT;
        uint32_t full = ext ? CAN_EXT_ID_MAX : CAN_STD_ID_MAX;
        if (r->id_mask == full)
            snprintf(match, sizeof(match), ext ? "%08" PRIX32 : "%03" PRIX32, r->id);
        else
            snprintf(match, sizeof(match), ext ? "%08" PRIX32 "/%08" PRIX32 : "%03" PRIX32 "/%03" PRIX32,
                     r->id, r->id_mask);
    }

    int n = snprintf(buf, cap, "%s %s %s", from, match, act);
    if (n < 0 || (size_t)n >= cap)
        return cap ? cap - 1u : 0u;
    size_t len = (size_t)n;

    if (r->action == GW_REWRITE) {
        if (r->set_id) {
            n = snprintf(buf + len, cap - len, " id=%" PRIX32, r->new_id);
            if (n < 0 || (size_t)n >= cap - len)
                return cap - 1u;
            len += (size_t)n;
        }
        int last = -1;
        for (int b = 0; b < (int)CAN_MAX_DLEN; b++)
            if (r->data_mask[b])
                last = b;
        if (last >= 0 && len + 6u + 2u * (size_t)(last + 1) < cap) {
            memcpy(buf + len, " data=", 6);
            len += 6;
            for (int b = 0; b <= last; b++) {
                for (int nib = 1; nib >= 0; nib--) {
                    unsigned sh = (unsigned)nib * 4u;
                    buf[len++] = ((r->data_mask[b] >> sh) & 0xFu) ? HEXC[(r->data_val[b] >> sh) & 0xFu] : '.';
                }
            }
            buf[len] = '\0';
        }
    }
    return len;
}
