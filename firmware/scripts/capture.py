#!/usr/bin/env python3
"""Capture canode's candump stream from USB CDC (or the UART) to a log file.

    python3 firmware/scripts/capture.py /dev/cu.usbmodemXXXX > logs/drive.log
    python3 firmware/scripts/capture.py /dev/cu.usbmodemXXXX --chan can1 -o logs/hs.log

It turns off echo, sets the board clock to host time (so timestamps are real
Unix times), starts `log on`, and writes only candump lines. Ctrl-C sends
`log off`. The file loads in tools/canlog (--replay), SavvyCAN and can-utils.
Listen-only: this script never puts a channel in a transmitting mode.
"""
import argparse
import re
import sys
import time

FRAME_RE = re.compile(r"^\(\d+\.\d+\) can[12] [0-9A-F]+#[0-9A-FR]*$")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("port", help="serial port, e.g. /dev/cu.usbmodem1101")
    ap.add_argument("--chan", default="all", choices=["all", "can1", "can2"])
    ap.add_argument("--baud", type=int, default=115200, help="UART only; ignored by USB CDC")
    ap.add_argument("-o", "--output", help="write here instead of stdout")
    args = ap.parse_args()

    import serial  # pyserial (already in the project venv)

    out = open(args.output, "a", encoding="ascii") if args.output else sys.stdout
    with serial.Serial(args.port, args.baud, timeout=0.2) as s:
        s.write(b"\r\necho off\r\n")
        time.sleep(0.1)
        s.write(f"time {time.time():.6f}\r\nlog on {args.chan}\r\n".encode())
        s.reset_input_buffer()
        frames = 0
        try:
            while True:
                line = s.readline().decode("ascii", errors="replace").strip()
                if FRAME_RE.match(line):
                    out.write(line + "\n")
                    frames += 1
                    if frames % 100 == 0:
                        out.flush()
                elif line:
                    print(f"[board] {line}", file=sys.stderr)
        except KeyboardInterrupt:
            pass
        finally:
            s.write(b"log off\r\necho on\r\n")
            out.flush()
            print(f"{frames} frames captured", file=sys.stderr)


if __name__ == "__main__":
    main()
