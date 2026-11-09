#!/usr/bin/env python3
"""
canlog.py - CAN bus logger / reverse-engineering console for STN-based adapters
(OBDLink MX+, SX, EX, LX ... anything speaking the ELM327 + STN "ST" command set).

What it does
  * Puts the adapter in raw monitor mode on a chosen bus (GM HS-CAN or GM SW-CAN)
  * Logs every frame to a candump-format file (loads straight into SavvyCAN,
    python-can, cantools, etc.)
  * Shows a live table of every arbitration ID: count, rate, last payload
  * Baseline/diff workflow: press [b] to snapshot, flip a switch in the truck,
    and the bytes that changed light up. New IDs are tagged NEW.
  * Markers: press [m] to drop a timestamped marker (written to a .marks file)
  * --probe lists every protocol number the adapter supports with its
    description, so you can confirm the SW-CAN / raw CAN numbers on YOUR firmware.
  * --replay feeds a saved candump log through the same UI (offline analysis).

Requirements
  pip install pyserial

Typical use (Windows, MX+ paired as a Bluetooth COM port):
  python canlog.py --port COM5 --probe            # one time: see protocol list
  python canlog.py --port COM5 --bus hs           # GM high-speed CAN (pins 6/14)
  python canlog.py --port COM5 --bus sw           # GM single-wire CAN (pin 1)
  python canlog.py --port COM5 --bus sw --filter 10240040:1FFFFF00
  python canlog.py --replay logs/2026..._sw.log   # analyse a capture offline

Keys in the live view
  b = set baseline (snapshot)   c = clear baseline   m = add marker
  p = pause/resume display      s = cycle sort (id / count / changed)   q = quit

Safety: this tool only LISTENS (monitor mode). Nothing is transmitted on the
vehicle bus except the adapter's own configuration. Do captures parked.
"""

import argparse
import json
import os
import queue
import re
import sys
import threading
import time
from datetime import datetime

# ---------------------------------------------------------------------------
# Frame parsing
# ---------------------------------------------------------------------------

HEX_RE = re.compile(r"^[0-9A-Fa-f]+$")


def parse_stn_line(line, prefer_ext=None):
    """Parse one monitor line produced with ATS0 (no spaces), ATH1 (headers),
    ATD1 (DLC shown). Format: <ID 3 or 8 hex><DLC 1 hex><DATA 2*DLC hex>.
    Returns (can_id:int, is_ext:bool, data:bytes) or None if not a frame."""
    s = line.strip().replace(" ", "")
    if not s or not HEX_RE.match(s):
        return None
    widths = (8, 3) if prefer_ext else (3, 8)
    for w in widths:
        if len(s) < w + 1:
            continue
        dlc = int(s[w], 16)
        if dlc > 8:
            continue
        if len(s) == w + 1 + 2 * dlc:
            can_id = int(s[:w], 16)
            data = bytes.fromhex(s[w + 1:]) if dlc else b""
            ext = (w == 8)
            if not ext and can_id > 0x7FF:
                continue
            return can_id, ext, data
    return None


def fmt_id(can_id, ext):
    return f"{can_id:08X}" if ext else f"{can_id:03X}"


def candump_line(ts, iface, can_id, ext, data):
    return f"({ts:.6f}) {iface} {fmt_id(can_id, ext)}#{data.hex().upper()}"


CANDUMP_RE = re.compile(r"^\((\d+\.\d+)\)\s+(\S+)\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)")


def parse_candump(line):
    m = CANDUMP_RE.match(line.strip())
    if not m:
        return None
    ts, _iface, sid, sdata = m.groups()
    ext = len(sid) > 3
    return float(ts), int(sid, 16), ext, bytes.fromhex(sdata)


# ---------------------------------------------------------------------------
# Adapter (STN / ELM327 over serial)
# ---------------------------------------------------------------------------

class Adapter:
    def __init__(self, port, baud=115200, raw_path=None):
        import serial  # pyserial
        self.ser = serial.Serial(port, baud, timeout=0.05)
        self.raw = open(raw_path, "a", encoding="ascii", errors="replace") if raw_path else None

    def close(self):
        try:
            self.ser.close()
        finally:
            if self.raw:
                self.raw.close()

    def _rawlog(self, direction, text):
        if self.raw:
            self.raw.write(f"{time.time():.6f} {direction} {text!r}\n")

    def cmd(self, command, timeout=2.0):
        """Send an AT/ST command and return the response text (prompt stripped)."""
        self.ser.reset_input_buffer()
        self._rawlog(">>", command)
        self.ser.write((command + "\r").encode("ascii"))
        buf = b""
        end = time.time() + timeout
        while time.time() < end:
            chunk = self.ser.read(256)
            if chunk:
                buf += chunk
                if b">" in buf:
                    break
        text = buf.decode("ascii", errors="replace")
        self._rawlog("<<", text)
        text = text.replace(">", "").replace("\r", "\n")
        lines = [l.strip() for l in text.split("\n") if l.strip() and l.strip() != command]
        return "\n".join(lines)

    def init(self):
        self.cmd("ATZ", timeout=3.0)
        for c in ("ATE0", "ATL0", "ATS0", "ATH1", "ATD1", "ATCAF0", "ATAL"):
            r = self.cmd(c)
            if "?" in r:
                print(f"  warning: {c} -> {r}")
        ident = self.cmd("STI")
        return ident

    def set_protocol(self, stp=None, elm=None):
        if stp is not None:
            r = self.cmd(f"STP{stp}")
        else:
            r = self.cmd(f"ATSP{elm}")
        if "?" in r:
            raise RuntimeError(f"adapter rejected protocol ({'STP' + str(stp) if stp else 'ATSP' + str(elm)}): {r}")
        desc = self.cmd("STPRS")
        return desc if "?" not in desc else self.cmd("ATDP")

    def probe(self, lo=1, hi=99):
        found = {}
        for n in range(lo, hi + 1):
            r = self.cmd(f"STP{n}", timeout=1.0)
            if "OK" in r:
                found[n] = self.cmd("STPRS", timeout=1.0)
                print(f"  STP{n:<3} {found[n]}")
        return found

    def set_filters(self, filters, ext):
        self.cmd("STFCP")  # clear pass filters
        for pat, mask in filters:
            w = 8 if ext else 3
            r = self.cmd(f"STFAP{pat:0{w}X},{mask:0{w}X}")
            if "?" in r:
                raise RuntimeError(f"filter rejected: {pat:X},{mask:X} -> {r}")

    def start_monitor(self, filtered):
        self._rawlog(">>", "STM" if filtered else "STMA")
        self.ser.write(b"STM\r" if filtered else b"STMA\r")

    def stop_monitor(self):
        self.ser.write(b"\r")
        time.sleep(0.3)
        self.ser.reset_input_buffer()


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

class IdStat:
    __slots__ = ("count", "last", "last_ts", "first_ts", "rate", "changed_ts")

    def __init__(self, ts):
        self.count = 0
        self.last = b""
        self.last_ts = ts
        self.first_ts = ts
        self.rate = 0.0
        self.changed_ts = [0.0] * 8


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.ids = {}            # (id, ext) -> IdStat
        self.baseline = None     # (id, ext) -> bytes
        self.total = 0
        self.status = []         # recent non-frame lines from adapter
        self.markers = []
        self.start = time.time()
        self.running = True
        self.replay_done = False

    def add(self, ts, can_id, ext, data):
        key = (can_id, ext)
        with self.lock:
            st = self.ids.get(key)
            if st is None:
                st = self.ids[key] = IdStat(ts)
            dt = ts - st.last_ts
            if st.count and dt > 0:
                inst = 1.0 / dt
                st.rate = inst if st.rate == 0 else 0.9 * st.rate + 0.1 * inst
            for i, b in enumerate(data):
                if i >= len(st.last) or st.last[i] != b:
                    st.changed_ts[i] = ts
            st.last = data
            st.last_ts = ts
            st.count += 1
            self.total += 1

    def note(self, text):
        with self.lock:
            self.status.append(f"{datetime.now():%H:%M:%S} {text}")
            self.status = self.status[-5:]


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def serial_reader(adapter, state, log, iface, prefer_ext, filtered):
    buf = ""
    adapter.start_monitor(filtered)
    while state.running:
        chunk = adapter.ser.read(4096)
        if not chunk:
            continue
        text = chunk.decode("ascii", errors="replace")
        adapter._rawlog("<<", text)
        buf += text
        while "\r" in buf or "\n" in buf:
            idx = min(i for i in (buf.find("\r"), buf.find("\n")) if i != -1)
            line, buf = buf[:idx], buf[idx + 1:]
            line = line.strip().lstrip(">")
            if not line:
                continue
            ts = time.time()
            fr = parse_stn_line(line, prefer_ext)
            if fr:
                can_id, ext, data = fr
                log.write(candump_line(ts, iface, can_id, ext, data) + "\n")
                state.add(ts, can_id, ext, data)
            else:
                state.note(line)
                if "BUFFER FULL" in line or "STOPPED" in line:
                    # adapter fell behind or monitor ended: restart it
                    time.sleep(0.05)
                    adapter.start_monitor(filtered)
    log.flush()


def replay_reader(path, state, speed):
    with open(path, encoding="ascii", errors="replace") as f:
        frames = [p for p in (parse_candump(l) for l in f) if p]
    if not frames:
        state.note("replay: no frames found")
        return
    t0 = frames[0][0]
    wall0 = time.time()
    for ts, can_id, ext, data in frames:
        if not state.running:
            return
        if speed > 0:
            delay = (ts - t0) / speed - (time.time() - wall0)
            if delay > 0:
                time.sleep(delay)
            now = time.time()
        else:
            now = ts
        state.add(now if speed > 0 else ts, can_id, ext, data)
    state.note(f"replay finished: {len(frames)} frames")
    state.replay_done = True


# ---------------------------------------------------------------------------
# Terminal UI
# ---------------------------------------------------------------------------

RESET, REV, YEL, CYN, DIM, GRN = "\x1b[0m", "\x1b[7m", "\x1b[33m", "\x1b[36m", "\x1b[2m", "\x1b[32m"


def render(state, title, sort_mode, max_rows):
    now = time.time()
    with state.lock:
        items = list(state.ids.items())
        base = dict(state.baseline) if state.baseline is not None else None
        total, status, markers = state.total, list(state.status), list(state.markers)
    elapsed = max(now - state.start, 1e-6)

    def changed_score(kv):
        (k, st) = kv
        if base is None:
            return -max(st.changed_ts)
        b = base.get(k)
        if b is None:
            return -1e12
        return -sum(1 for i, x in enumerate(st.last) if i >= len(b) or b[i] != x)

    if sort_mode == "count":
        items.sort(key=lambda kv: -kv[1].count)
    elif sort_mode == "changed":
        items.sort(key=changed_score)
    else:
        items.sort(key=lambda kv: (kv[0][1], kv[0][0]))

    out = [f"{CYN}{title}{RESET}",
           f"frames {total}  ({total / elapsed:.0f}/s)  ids {len(items)}  "
           f"baseline {'SET' if base is not None else 'off'}  sort {sort_mode}  markers {len(markers)}",
           f"{DIM}keys: b baseline  c clear  m marker  p pause  s sort  q quit{RESET}",
           f"{'ID':>8}  {'count':>7}  {'Hz':>6}  data (yellow = differs from baseline, inverse = changed <1s)"]
    for (can_id, ext), st in items[:max_rows]:
        b = base.get((can_id, ext)) if base is not None else None
        tag = f" {GRN}NEW{RESET}" if base is not None and b is None else ""
        cells = []
        for i, byte in enumerate(st.last):
            s = f"{byte:02X}"
            recent = now - st.changed_ts[i] < 1.0 and st.count > 1
            diff = b is not None and (i >= len(b) or b[i] != byte)
            if diff:
                s = f"{YEL}{s}{RESET}"
            if recent:
                s = f"{REV}{s}{RESET}"
            cells.append(s)
        stale = now - st.last_ts > 2.0
        idtxt = fmt_id(can_id, ext)
        line = f"{idtxt:>8}  {st.count:>7}  {st.rate:>6.1f}  {' '.join(cells)}{tag}"
        out.append(f"{DIM}{line}{RESET}" if stale else line)
    if len(items) > max_rows:
        out.append(f"{DIM}... {len(items) - max_rows} more ids (resize terminal or use --filter){RESET}")
    if status:
        out.append(f"{DIM}adapter: {' | '.join(status[-3:])}{RESET}")
    if markers:
        out.append(f"{DIM}last marker: {markers[-1]}{RESET}")
    sys.stdout.write("\x1b[H\x1b[J" + "\n".join(out) + "\n")
    sys.stdout.flush()


class Keys:
    """Non-blocking single-key reader for Windows and POSIX terminals."""

    def __init__(self):
        self.win = os.name == "nt"
        self.old = None
        if not self.win and sys.stdin.isatty():
            import termios
            import tty
            self.old = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())

    def get(self):
        if self.win:
            import msvcrt
            if msvcrt.kbhit():
                return msvcrt.getwch().lower()
            return None
        import select
        if sys.stdin.isatty() and select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.read(1).lower()
        return None

    def restore(self):
        if self.old is not None:
            import termios
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old)


def run_ui(state, title, marks_path, refresh, no_ui):
    keys = Keys()
    sort_modes = ["id", "count", "changed"]
    sort_i, paused = 0, False
    try:
        while state.running:
            k = keys.get()
            if k == "q":
                break
            elif k == "b":
                with state.lock:
                    state.baseline = {key: st.last for key, st in state.ids.items()}
                state.note("baseline set")
            elif k == "c":
                with state.lock:
                    state.baseline = None
                state.note("baseline cleared")
            elif k == "m":
                with state.lock:
                    n = len(state.markers) + 1
                    label = f"MARK {n} @ {time.time():.6f}"
                    state.markers.append(label)
                if marks_path:
                    with open(marks_path, "a") as mf:
                        mf.write(label + "\n")
            elif k == "p":
                paused = not paused
            elif k == "s":
                sort_i = (sort_i + 1) % len(sort_modes)
            if not paused and not no_ui:
                try:
                    rows = os.get_terminal_size().lines - 8
                except OSError:
                    rows = 40
                render(state, title, sort_modes[sort_i], max(rows, 5))
            elif no_ui:
                print(f"\rframes {state.total}  ids {len(state.ids)}", end="", flush=True)
                if state.replay_done:
                    print()
                    break
            time.sleep(refresh)
    except KeyboardInterrupt:
        pass
    finally:
        state.running = False
        keys.restore()


# ---------------------------------------------------------------------------
# Protocol selection
# ---------------------------------------------------------------------------

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stn_protocols.json")


def pick_protocol(protocols, bus, ext):
    """Choose an STP number from probe results by its description string."""
    def score(desc):
        d = desc.upper()
        s = 0
        if bus == "sw":
            if not re.search(r"SW|SINGLE", d):
                return -1
            s += 10
        else:
            if re.search(r"SW|SINGLE|MS[- ]?CAN|MEDIUM|J1939", d):
                return -1
            if "500" not in d:
                return -1
            s += 5
        if "11898" in d or "RAW" in d:
            s += 5
        if ("29" in d) == ext:
            s += 3
        return s
    best = max(((score(d), int(n)) for n, d in protocols.items()), default=(-1, None))
    return best[1] if best[0] >= 0 else None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_filter(text, ext):
    full = 0x1FFFFFFF if ext else 0x7FF
    if ":" in text:
        p, m = text.split(":", 1)
        return int(p, 16), int(m, 16)
    return int(text, 16), full


def main():
    ap = argparse.ArgumentParser(description="STN/OBDLink CAN logger and diff console")
    ap.add_argument("--port", help="serial port, e.g. COM5 or /dev/rfcomm0")
    ap.add_argument("--baud", type=int, default=115200, help="serial baud (ignored by Bluetooth SPP)")
    ap.add_argument("--bus", choices=["hs", "sw"], default="hs",
                    help="hs = GM high-speed CAN 500k (pins 6/14), sw = GM single-wire CAN 33.3k (pin 1)")
    ap.add_argument("--stp", type=int, help="force a specific STN protocol number (see --probe)")
    ap.add_argument("--ext", action="store_true", help="expect 29-bit IDs (default: sw=29-bit, hs=11-bit)")
    ap.add_argument("--std", action="store_true", help="expect 11-bit IDs")
    ap.add_argument("--filter", action="append", default=[], help="pass filter ID[:MASK] in hex (repeatable)")
    ap.add_argument("--probe", action="store_true", help="list adapter protocols and exit")
    ap.add_argument("--outdir", default="logs", help="directory for logs")
    ap.add_argument("--raw", action="store_true", help="also save raw adapter serial traffic (.raw)")
    ap.add_argument("--replay", help="replay a candump log instead of reading the adapter")
    ap.add_argument("--speed", type=float, default=1.0, help="replay speed multiplier (0 = instant)")
    ap.add_argument("--refresh", type=float, default=0.25, help="UI refresh interval seconds")
    ap.add_argument("--no-ui", action="store_true", help="log only, no live table")
    args = ap.parse_args()

    if os.name == "nt":
        os.system("")  # enable ANSI escape handling in Windows consoles

    ext = args.ext or (args.bus == "sw" and not args.std)
    state = State()

    if args.replay:
        title = f"REPLAY {args.replay}"
        t = threading.Thread(target=replay_reader, args=(args.replay, state, args.speed), daemon=True)
        t.start()
        run_ui(state, title, None, args.refresh, args.no_ui)
        return

    if not args.port:
        ap.error("--port is required unless --replay is used")

    os.makedirs(args.outdir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(args.outdir, f"{stamp}_{args.bus}")
    adapter = Adapter(args.port, args.baud, raw_path=base + ".raw" if args.raw else None)
    try:
        print("initialising adapter ...")
        ident = adapter.init()
        print(f"  adapter: {ident or '(no STI response - not an STN device?)'}")

        if args.probe:
            print("probing STN protocol numbers (takes ~30s) ...")
            protos = adapter.probe()
            with open(CACHE, "w") as f:
                json.dump(protos, f, indent=1)
            print(f"saved to {CACHE}")
            return

        stp = args.stp
        if stp is None:
            if os.path.exists(CACHE):
                with open(CACHE) as f:
                    protos = json.load(f)
            else:
                print("no protocol cache yet; probing once ...")
                protos = adapter.probe()
                with open(CACHE, "w") as f:
                    json.dump(protos, f, indent=1)
            stp = pick_protocol(protos, args.bus, ext)

        if stp is None and args.bus == "hs":
            desc = adapter.set_protocol(elm=6)  # ISO 15765 11-bit 500k fallback
        elif stp is None:
            raise SystemExit("no SW-CAN protocol found on this adapter (run --probe and pass --stp N)")
        else:
            desc = adapter.set_protocol(stp=stp)
        print(f"  protocol: {desc}")

        filters = [parse_filter(f, ext) for f in args.filter]
        if filters:
            adapter.set_filters(filters, ext)

        iface = "can0" if args.bus == "hs" else "can1"
        log_path, marks_path = base + ".log", base + ".marks"
        print(f"  logging to {log_path}")
        time.sleep(0.5)
        with open(log_path, "w", buffering=1) as log:
            t = threading.Thread(target=serial_reader,
                                 args=(adapter, state, log, iface, ext, bool(filters)), daemon=True)
            t.start()
            run_ui(state, f"{args.bus.upper()}-CAN  {desc}  ->  {log_path}", marks_path,
                   args.refresh, args.no_ui)
            t.join(timeout=1.0)
        adapter.stop_monitor()
        print(f"\nstopped. {state.total} frames, {len(state.ids)} ids -> {log_path}")
    finally:
        adapter.close()


if __name__ == "__main__":
    main()
