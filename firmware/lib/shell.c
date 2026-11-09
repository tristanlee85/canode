#include "shell.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

void shell_init(shell_t *sh, const shell_cmd_t *cmds, size_t ncmds, shell_write_fn write, void *ctx)
{
    memset(sh, 0, sizeof(*sh));
    sh->cmds = cmds;
    sh->ncmds = ncmds;
    sh->write = write;
    sh->ctx = ctx;
    sh->echo = true;
}

void shell_puts(shell_t *sh, const char *s)
{
    sh->write(sh->ctx, s, strlen(s));
}

void shell_printf(shell_t *sh, const char *fmt, ...)
{
    char buf[160];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    if (n < 0)
        return;
    if ((size_t)n >= sizeof(buf))
        n = (int)sizeof(buf) - 1;
    sh->write(sh->ctx, buf, (size_t)n);
}

void shell_prompt(shell_t *sh)
{
    if (sh->echo && (sh->prompt_ok == NULL || sh->prompt_ok(sh)))
        shell_puts(sh, SHELL_PROMPT);
}

int shell_tokenize(char *line, char **argv, int max)
{
    int argc = 0;
    char *p = line;
    while (*p && argc < max) {
        while (*p == ' ' || *p == '\t')
            *p++ = '\0';
        if (!*p)
            break;
        argv[argc++] = p;
        while (*p && *p != ' ' && *p != '\t')
            p++;
    }
    return argc;
}

int shell_exec(shell_t *sh, char *line)
{
    char *argv[SHELL_ARGV_MAX];
    int argc = shell_tokenize(line, argv, (int)SHELL_ARGV_MAX);
    if (argc == 0)
        return 0;
    for (size_t i = 0; i < sh->ncmds; i++) {
        if (strcmp(argv[0], sh->cmds[i].name) == 0)
            return sh->cmds[i].fn(sh, argc, argv);
    }
    shell_printf(sh, "error: unknown command '%s' (try 'help')\r\n", argv[0]);
    return -1;
}

void shell_print_help(shell_t *sh)
{
    for (size_t i = 0; i < sh->ncmds; i++) {
        const shell_cmd_t *c = &sh->cmds[i];
        shell_printf(sh, "  %-8s %s\r\n", c->name, c->usage);
        shell_printf(sh, "           %s\r\n", c->help);
    }
}

void shell_input(shell_t *sh, char c)
{
    char prev = sh->last;
    sh->last = c;

    if (c == '\n' && prev == '\r')
        return;  /* second half of CRLF */

    if (c == '\r' || c == '\n') {
        if (sh->echo)
            shell_puts(sh, "\r\n");
        if (sh->overflow) {
            shell_puts(sh, "error: line too long\r\n");
        } else {
            sh->line[sh->len] = '\0';
            shell_exec(sh, sh->line);
        }
        sh->len = 0;
        sh->overflow = false;
        shell_prompt(sh);
        return;
    }

    if (c == '\b' || c == 0x7F) {  /* backspace / DEL */
        if (sh->len > 0) {
            sh->len--;
            if (sh->echo)
                shell_puts(sh, "\b \b");
        }
        return;
    }

    if (c == 0x03) {  /* Ctrl-C: drop the current line */
        sh->len = 0;
        sh->overflow = false;
        if (sh->echo)
            shell_puts(sh, "^C\r\n");
        shell_prompt(sh);
        return;
    }

    if ((unsigned char)c < 0x20 || (unsigned char)c > 0x7E)
        return;  /* ignore other control / non-ASCII bytes */

    if (sh->len >= SHELL_LINE_MAX - 1u) {
        sh->overflow = true;
        return;
    }
    sh->line[sh->len++] = c;
    if (sh->echo)
        sh->write(sh->ctx, &c, 1);
}
