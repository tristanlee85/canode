#include "parse.h"

#include <string.h>

#include "can_frame.h"

static int hexdigit(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

bool parse_hex_u32(const char *s, uint32_t *out)
{
    size_t n = s ? strlen(s) : 0;
    if (n == 0 || n > 8)
        return false;
    uint32_t v = 0;
    for (size_t i = 0; i < n; i++) {
        int d = hexdigit(s[i]);
        if (d < 0)
            return false;
        v = (v << 4) | (uint32_t)d;
    }
    *out = v;
    return true;
}

bool parse_u32(const char *s, uint32_t *out)
{
    if (s == NULL || *s == '\0')
        return false;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X'))
        return parse_hex_u32(s + 2, out);
    uint64_t v = 0;
    for (const char *p = s; *p; p++) {
        if (*p < '0' || *p > '9')
            return false;
        v = v * 10u + (uint64_t)(*p - '0');
        if (v > 0xFFFFFFFFu)
            return false;
    }
    *out = (uint32_t)v;
    return true;
}

bool parse_bitrate(const char *s, uint32_t *out)
{
    if (s == NULL || *s == '\0')
        return false;
    /* Fixed point: value * 1000 so "83.333k" works without floats. */
    uint64_t milli = 0;
    int frac_digits = -1;   /* -1 = no decimal point seen */
    const char *p = s;
    for (; *p >= '0' && *p <= '9'; p++)
        milli = milli * 10u + (uint64_t)(*p - '0');
    if (p == s)
        return false;
    milli *= 1000u;
    if (*p == '.') {
        p++;
        frac_digits = 0;
        uint64_t scale = 100u;
        for (; *p >= '0' && *p <= '9'; p++, frac_digits++) {
            if (frac_digits >= 3)
                return false;
            milli += (uint64_t)(*p - '0') * scale;
            scale /= 10u;
        }
        if (frac_digits == 0)
            return false;
    }
    uint64_t mult = 1;
    if (*p == 'k' || *p == 'K') {
        mult = 1000u;
        p++;
    } else if (*p == 'M' || *p == 'm') {
        mult = 1000000u;
        p++;
    }
    if (*p != '\0')
        return false;
    uint64_t bps = milli * mult / 1000u;
    if (bps == 0u || bps > 1000000u)
        return false;
    *out = (uint32_t)bps;
    return true;
}

bool parse_channel(const char *s, uint8_t *chan)
{
    if (s == NULL)
        return false;
    for (uint8_t i = 0; i < CAN_NUM_CHANNELS; i++) {
        if (strcmp(s, can_chan_name(i)) == 0) {
            *chan = i;
            return true;
        }
    }
    return false;
}

bool parse_channel_mask(const char *s, uint8_t *mask)
{
    uint8_t ch;
    if (s != NULL && strcmp(s, "all") == 0) {
        *mask = (uint8_t)((1u << CAN_NUM_CHANNELS) - 1u);
        return true;
    }
    if (!parse_channel(s, &ch))
        return false;
    *mask = (uint8_t)(1u << ch);
    return true;
}

bool parse_epoch_us(const char *s, uint64_t *out)
{
    if (s == NULL || *s == '\0')
        return false;
    uint64_t sec = 0;
    const char *p = s;
    for (; *p >= '0' && *p <= '9'; p++) {
        sec = sec * 10u + (uint64_t)(*p - '0');
        if (sec > 0xFFFFFFFFFFull)   /* ~year 36800; just a sanity bound */
            return false;
    }
    if (p == s)
        return false;
    uint64_t us = 0;
    if (*p == '.') {
        p++;
        uint64_t scale = 100000u;
        int digits = 0;
        for (; *p >= '0' && *p <= '9'; p++, digits++) {
            if (digits < 6)
                us += (uint64_t)(*p - '0') * scale;
            scale /= 10u;
        }
        if (digits == 0)
            return false;
    }
    if (*p != '\0')
        return false;
    *out = sec * 1000000u + us;
    return true;
}
