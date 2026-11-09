#include "test.h"

int g_failures;
int g_checks;

int main(void)
{
    struct { const char *name; void (*fn)(void); } suites[] = {
        {"bittiming", test_bittiming},
        {"candump", test_candump},
        {"frame_ring", test_frame_ring},
        {"parse", test_parse},
        {"shell", test_shell},
        {"gateway", test_gateway},
        {"power", test_power},
    };
    for (size_t i = 0; i < sizeof(suites) / sizeof(suites[0]); i++) {
        int before = g_failures;
        suites[i].fn();
        printf("%-12s %s\n", suites[i].name, g_failures == before ? "ok" : "FAIL");
    }
    printf("%d checks, %d failures\n", g_checks, g_failures);
    return g_failures ? 1 : 0;
}
