#!/bin/sh
# Host unit tests for firmware/lib (no hardware, no cross compiler).
# Usage: firmware/test/run_tests.sh      (CC=gcc to pick another compiler)
set -eu
here=$(cd "$(dirname "$0")" && pwd)
lib="$here/../lib"
out="${TMPDIR:-/tmp}/canode-fw-tests.$$"
CC=${CC:-cc}

# Sanitizers catch out-of-bounds and UB in the parsers; skip them if the
# compiler can't link them (some minimal toolchains).
san="-fsanitize=address,undefined -fno-omit-frame-pointer"
if ! echo 'int main(void){return 0;}' | $CC $san -x c - -o "$out" 2>/dev/null; then
    san=""
fi

$CC -std=c11 -Wall -Wextra -Werror -Wshadow -Wconversion -Wno-sign-conversion -g $san \
    -I"$lib" -I"$here" \
    "$here"/test_*.c "$lib"/*.c \
    -o "$out"
trap 'rm -f "$out"' EXIT
"$out"
