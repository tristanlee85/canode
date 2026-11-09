/*
 * shell.h - tiny line-based command shell, transport independent.
 *
 * Each serial port (USB CDC, UART) owns one shell_t. Bytes go in through
 * shell_input(); a CR or LF ends the line, which is split on whitespace and
 * dispatched to the matching entry of the command table. Output goes back
 * through the write callback, so a command's reply lands on the port it came from.
 */
#ifndef SHELL_H
#define SHELL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SHELL_LINE_MAX 128u
#define SHELL_ARGV_MAX 12u
#define SHELL_PROMPT   "canode> "

typedef struct shell shell_t;

typedef int (*shell_cmd_fn)(shell_t *sh, int argc, char **argv);
typedef void (*shell_write_fn)(void *ctx, const char *s, size_t n);

typedef struct {
    const char  *name;
    const char  *usage;    /* argument synopsis, shown by help */
    const char  *help;     /* one-line description */
    shell_cmd_fn fn;
} shell_cmd_t;

struct shell {
    char               line[SHELL_LINE_MAX];
    size_t             len;
    bool               echo;       /* echo typed characters and show a prompt */
    bool               overflow;   /* current line exceeded SHELL_LINE_MAX */
    char               last;       /* previous char, to treat CRLF as one newline */
    const shell_cmd_t *cmds;
    size_t             ncmds;
    shell_write_fn     write;
    void              *ctx;        /* passed to write(); the app uses it as the port id */
    bool             (*prompt_ok)(shell_t *sh); /* optional: return false to suppress the prompt */
};

void shell_init(shell_t *sh, const shell_cmd_t *cmds, size_t ncmds, shell_write_fn write, void *ctx);

/* Feed one received byte. Runs the command when a line is complete. */
void shell_input(shell_t *sh, char c);

/* Tokenise and run one line in place. Returns the command's result, or -1 if unknown. */
int shell_exec(shell_t *sh, char *line);

/* Split on spaces/tabs in place. Returns argc (at most max). */
int shell_tokenize(char *line, char **argv, int max);

void shell_puts(shell_t *sh, const char *s);
void shell_printf(shell_t *sh, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
void shell_prompt(shell_t *sh);

/* Print the command table (used by the "help" command). */
void shell_print_help(shell_t *sh);

#endif
