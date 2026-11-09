#include "test.h"
#include "shell.h"

static char out[1024];
static size_t outlen;
static int last_argc;
static char last_args[SHELL_ARGV_MAX][32];
static int calls;

static void cap_write(void *ctx, const char *s, size_t n)
{
    (void)ctx;
    if (outlen + n < sizeof(out)) {
        memcpy(out + outlen, s, n);
        outlen += n;
        out[outlen] = '\0';
    }
}

static int cmd_rec(shell_t *sh, int argc, char **argv)
{
    (void)sh;
    calls++;
    last_argc = argc;
    for (int i = 0; i < argc; i++)
        snprintf(last_args[i], sizeof(last_args[i]), "%s", argv[i]);
    return 0;
}

static int cmd_hello(shell_t *sh, int argc, char **argv)
{
    (void)argc;
    (void)argv;
    shell_printf(sh, "hello %d\r\n", 42);
    return 0;
}

static const shell_cmd_t cmds[] = {
    {"rec", "[args]", "record args", cmd_rec},
    {"hello", "", "say hello", cmd_hello},
};

static void reset(void)
{
    outlen = 0;
    out[0] = '\0';
    calls = 0;
    last_argc = 0;
}

static void feed(shell_t *sh, const char *s)
{
    while (*s)
        shell_input(sh, *s++);
}

void test_shell(void)
{
    shell_t sh;
    shell_init(&sh, cmds, sizeof(cmds) / sizeof(cmds[0]), cap_write, NULL);

    /* Tokenizer. */
    char line[] = "  mode \t can1   monitor ";
    char *argv[SHELL_ARGV_MAX];
    int argc = shell_tokenize(line, argv, SHELL_ARGV_MAX);
    CHECK_EQ(argc, 3);
    CHECK_STR(argv[0], "mode");
    CHECK_STR(argv[1], "can1");
    CHECK_STR(argv[2], "monitor");

    /* Echo off: no echo, no prompt, just the command's output. */
    sh.echo = false;
    reset();
    feed(&sh, "hello\r\n");
    CHECK_STR(out, "hello 42\r\n");

    /* CRLF counts once; LF alone and CR alone both work. */
    reset();
    feed(&sh, "rec a b\r\nrec c\nrec d e f\r");
    CHECK_EQ(calls, 3);
    CHECK_EQ(last_argc, 4);
    CHECK_STR(last_args[3], "f");

    /* Empty lines do nothing. */
    reset();
    feed(&sh, "\r\n\r\n   \n");
    CHECK_EQ(calls, 0);
    CHECK_STR(out, "");

    /* Backspace edits the line. */
    reset();
    feed(&sh, "recx\b a\n");
    CHECK_EQ(calls, 1);
    CHECK_STR(last_args[0], "rec");
    CHECK_STR(last_args[1], "a");

    /* Ctrl-C drops the line. */
    reset();
    feed(&sh, "rec zzz\x03" "hello\n");
    CHECK_EQ(calls, 0);
    CHECK_STR(out, "hello 42\r\n");

    /* Unknown command. */
    reset();
    feed(&sh, "bogus\n");
    CHECK(strstr(out, "unknown command 'bogus'") != NULL);

    /* Overlong line is rejected, and the shell recovers. */
    reset();
    for (int i = 0; i < 300; i++)
        shell_input(&sh, 'x');
    feed(&sh, "\nrec ok\n");
    CHECK(strstr(out, "line too long") != NULL);
    CHECK_EQ(calls, 1);
    CHECK_STR(last_args[1], "ok");

    /* Echo on: characters echoed, prompt after the command. */
    sh.echo = true;
    reset();
    feed(&sh, "hello\r");
    CHECK_STR(out, "hello\r\nhello 42\r\n" SHELL_PROMPT);

    /* Help lists commands. */
    reset();
    shell_print_help(&sh);
    CHECK(strstr(out, "rec") != NULL && strstr(out, "say hello") != NULL);
}
