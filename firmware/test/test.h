/* Minimal assert-style test helpers for the host unit tests. */
#ifndef TEST_H
#define TEST_H

#include <stdio.h>
#include <string.h>

extern int g_failures;
extern int g_checks;

#define CHECK(cond)                                                              \
    do {                                                                         \
        g_checks++;                                                              \
        if (!(cond)) {                                                           \
            g_failures++;                                                        \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, #cond); \
        }                                                                        \
    } while (0)

#define CHECK_EQ(a, b)                                                           \
    do {                                                                         \
        g_checks++;                                                              \
        long long _a = (long long)(a), _b = (long long)(b);                      \
        if (_a != _b) {                                                          \
            g_failures++;                                                        \
            fprintf(stderr, "%s:%d: CHECK_EQ failed: %s == %lld, expected %s == %lld\n", \
                    __FILE__, __LINE__, #a, _a, #b, _b);                         \
        }                                                                        \
    } while (0)

#define CHECK_STR(a, b)                                                          \
    do {                                                                         \
        g_checks++;                                                              \
        const char *_a = (a), *_b = (b);                                         \
        if (strcmp(_a, _b) != 0) {                                               \
            g_failures++;                                                        \
            fprintf(stderr, "%s:%d: CHECK_STR failed:\n   got: \"%s\"\n  want: \"%s\"\n", \
                    __FILE__, __LINE__, _a, _b);                                 \
        }                                                                        \
    } while (0)

void test_bittiming(void);
void test_candump(void);
void test_frame_ring(void);
void test_parse(void);
void test_shell(void);
void test_gateway(void);

#endif
