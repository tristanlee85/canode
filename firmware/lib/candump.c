#include "candump.h"

#include <string.h>

static const char HEX[] = "0123456789ABCDEF";

size_t fmt_u64(char *buf, uint64_t v)
{
    char tmp[20];
    size_t n = 0;
    do {
        tmp[n++] = (char)('0' + (v % 10u));
        v /= 10u;
    } while (v != 0u);
    for (size_t i = 0; i < n; i++)
        buf[i] = tmp[n - 1u - i];
    return n;
}

static size_t put_hex(char *p, uint32_t v, unsigned digits)
{
    for (unsigned i = 0; i < digits; i++)
        p[i] = HEX[(v >> (4u * (digits - 1u - i))) & 0xFu];
    return digits;
}

size_t candump_format(char *buf, size_t cap, const can_frame_t *f, uint64_t epoch_offset_us)
{
    /* Build into a scratch buffer that is always big enough, then copy. */
    char line[CANDUMP_LINE_MAX];
    char *p = line;
    uint64_t ts = f->ts_us + epoch_offset_us;
    uint32_t usec = (uint32_t)(ts % 1000000u);

    *p++ = '(';
    p += fmt_u64(p, ts / 1000000u);
    *p++ = '.';
    for (int i = 5; i >= 0; i--) {
        p[i] = (char)('0' + usec % 10u);
        usec /= 10u;
    }
    p += 6;
    *p++ = ')';
    *p++ = ' ';
    const char *iface = can_chan_name(f->chan);
    size_t ilen = strlen(iface);
    memcpy(p, iface, ilen);
    p += ilen;
    *p++ = ' ';

    if (f->flags & CAN_FLAG_EXT)
        p += put_hex(p, f->id & CAN_EXT_ID_MAX, 8);
    else
        p += put_hex(p, f->id & CAN_STD_ID_MAX, 3);
    *p++ = '#';

    uint8_t len = f->len > CAN_MAX_DLEN ? CAN_MAX_DLEN : f->len;
    if (f->flags & CAN_FLAG_RTR) {
        *p++ = 'R';
        if (len)
            *p++ = (char)('0' + len);
    } else {
        for (uint8_t i = 0; i < len; i++)
            p += put_hex(p, f->data[i], 2);
    }
    *p++ = '\n';

    size_t n = (size_t)(p - line);
    if (n > cap)
        return 0;
    memcpy(buf, line, n);
    return n;
}

static int hexval(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

bool candump_parse_frame(const char *s, can_frame_t *f)
{
    if (s == NULL || f == NULL)
        return false;
    memset(f, 0, sizeof(*f));

    const char *hash = strchr(s, '#');
    if (hash == NULL)
        return false;
    size_t idlen = (size_t)(hash - s);
    if (idlen == 0 || idlen > 8)
        return false;

    uint32_t id = 0;
    for (size_t i = 0; i < idlen; i++) {
        int v = hexval(s[i]);
        if (v < 0)
            return false;
        id = (id << 4) | (uint32_t)v;
    }
    if (idlen > 3) {
        if (id > CAN_EXT_ID_MAX)
            return false;
        f->flags |= CAN_FLAG_EXT;
    } else if (id > CAN_STD_ID_MAX) {
        return false;
    }
    f->id = id;

    const char *d = hash + 1;
    if (*d == 'R' || *d == 'r') {
        f->flags |= CAN_FLAG_RTR;
        d++;
        if (*d) {
            if (*d < '0' || *d > '8' || d[1] != '\0')
                return false;
            f->len = (uint8_t)(*d - '0');
        }
        return true;
    }

    while (*d) {
        if (*d == '.') {
            d++;
            continue;
        }
        int hi = hexval(d[0]);
        int lo = hi < 0 ? -1 : hexval(d[1]);
        if (hi < 0 || lo < 0 || f->len >= CAN_MAX_DLEN)
            return false;
        f->data[f->len++] = (uint8_t)((hi << 4) | lo);
        d += 2;
    }
    return true;
}
