#!/usr/bin/env python3
"""
canlog.py - CAN bus logger / reverse-engineering console for STN-based adapters
(OBDLink MX+, SX, EX, LX ... anything speaking the ELM327 + STN "ST" command set).

What it does
  * Finds the adapter by itself: waits for a serial port whose name looks like an
    OBDLink/STN/ELM device, opens it and retries until the adapter answers
  * Puts the adapter in silent raw monitor mode on a chosen bus (GM HS-CAN or GM SW-CAN)
  * Logs every frame to a candump-format file (loads straight into SavvyCAN,
    python-can, cantools, etc.)
  * Survives Bluetooth dropouts: reconnects, re-initialises and keeps appending
    to the same log; each gap is recorded in the .marks and .json files
  * Shows a live table of every arbitration ID: count, rate, last payload
  * Baseline/diff workflow: press [b] to snapshot, flip a switch in the truck,
    and the bytes that changed light up. New IDs are tagged NEW.
  * Guided tests: pick a feature, follow the on-screen steps, and it reports the
    bits that follow it (steady values, blinking bits, IDs only sent in a state)
  * Markers: press [m] to drop a labelled, timestamped marker (written to the
    .marks file with every byte that differs from the baseline at that moment)
  * Writes a .json session summary (adapter, voltage, protocol, per-ID stats)
  * --probe lists every protocol number the adapter supports with its
    description, so you can confirm the SW-CAN / raw CAN numbers on YOUR firmware.
  * --replay feeds a saved candump log through the same UI (offline analysis).

Requirements
  pip install pyserial

Typical use (macOS, MX+ paired in System Settings > Bluetooth; no --port needed):
  python canlog.py --probe                        # one time: see protocol list
  python canlog.py --bus hs                       # GM high-speed CAN (pins 6/14)
  python canlog.py --bus sw                       # GM single-wire CAN (pin 1)
  python canlog.py --bus sw --filter 10240040:1FFFFF00
  python canlog.py --replay logs/2026..._sw.log   # analyse a capture offline
  Windows: add --port COM5 (Bluetooth COM ports can't be recognised by name).

Output files (logs/<stamp>_<bus>.*)
  .log    candump frames        .marks  markers, baselines, link dropouts
  .json   session summary       .raw    raw serial traffic (with --raw)

Live view (the screen always shows what to press next)
  b = learn baseline: 10s of hands-off background chatter; bits that change on
      their own (counters, sensors) are ignored from then on
  t = guided tests menu: headlights, doors, turn signals ... each one tells you
      what to do, captures every state 3 times, and lists the bits that track it
      [r] during a test re-captures the previous step (or a finished test's last
      step); if one whole round went wrong anyway, the result says which and
      lists what the other rounds agree on
  m = marker with a typed label   f = changed-only / all IDs   s = sort
  p = pause display   c = clear baseline   q = quit (asks to confirm)
  Results go in the .marks file and the .json summary ("findings").

Safety: this tool only LISTENS (monitor mode, ATCSM1 silent). Nothing is
transmitted on the vehicle bus except the adapter's own configuration. Do captures parked.
"""

import argparse
import glob
import json
import os
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

# A bit must flip this many times in every capture of a state to count as blinking
# there; slowly drifting sensor bits flip once or twice by chance.
BUSY_FLIPS = 3

# Seconds of total silence in monitor mode before checking the adapter is still alive.
STALL_SECS = 15.0


class Adapter:
    def __init__(self, port, baud=115200, raw_path=None):
        self.port, self.baud = port, baud
        self.ser = None
        self.open()
        self.raw = open(raw_path, "a", encoding="ascii", errors="replace") if raw_path else None

    def open(self):
        import serial  # pyserial
        self.ser = serial.Serial(self.port, self.baud, timeout=0.05)

    def close_port(self):
        if self.ser is not None:
            try:
                self.ser.close()
            except OSError:
                pass
            self.ser = None

    def close(self):
        try:
            self.close_port()
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

    def wake(self, tries=4):
        """Reset the adapter until it answers; returns the reset banner or None.
        The first bytes after a Bluetooth connect are often lost, and after a
        dropout the adapter may still be in monitor mode, so stop that first."""
        for _ in range(tries):
            self.stop_monitor()
            r = self.cmd("ATZ", timeout=3.0)
            if r:
                return r
        return None

    def init(self):
        """Reset and configure the adapter. Returns an info dict, or None if the
        adapter never answered."""
        reset = self.wake()
        if reset is None:
            return None
        warnings = []
        # ATCSM1 = silent monitoring: never ACK frames, so the adapter stays invisible on the bus
        for c in ("ATE0", "ATL0", "ATS0", "ATH1", "ATD1", "ATCAF0", "ATAL", "ATCSM1"):
            r = self.cmd(c)
            if "?" in r:
                warnings.append(f"{c} -> {r}")

        def ask(c):
            r = self.cmd(c)
            return "" if "?" in r else r

        return {"reset": reset, "firmware": ask("STI"), "device": ask("STDI"),
                "voltage": ask("ATRV"), "warnings": warnings}

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
        if self.ser is None:
            return
        self.ser.write(b"\r")
        time.sleep(0.3)
        self.ser.reset_input_buffer()


# ---------------------------------------------------------------------------
# Finding the adapter
# ---------------------------------------------------------------------------

# macOS names a paired MX+ something like /dev/cu.OBDLinkMXPlus-...; Linux uses rfcomm.
PORT_MATCH = r"obd|stn|elm|mx"


def candidate_ports(pattern):
    """Return (matching ports, all ports seen). On macOS only the cu.* devices
    are used: tty.* opens block waiting for carrier detect."""
    from serial.tools import list_ports
    names = {p.device: f"{p.device} {p.description} {p.product or ''}" for p in list_ports.comports()}
    for dev in glob.glob("/dev/cu.*") + glob.glob("/dev/rfcomm*"):
        names.setdefault(dev, dev)
    if sys.platform == "darwin":
        names = {d: t for d, t in names.items() if not d.startswith("/dev/tty.")}
    rx = re.compile(pattern, re.I)
    return sorted(d for d, t in names.items() if rx.search(t)), sorted(names)


def connect(args, raw_path):
    """Wait for the adapter's port, open it and wake the adapter.
    Returns (adapter, info). Gives up after --wait seconds (0 = wait forever)."""
    deadline = time.time() + args.wait if args.wait else None
    last_msg = None
    while True:
        if args.port:
            ports, seen = [args.port], []
        else:
            ports, seen = candidate_ports(args.port_match)
        msg = None
        for port in ports:
            try:
                adapter = Adapter(port, args.baud, raw_path)
            except OSError as e:
                msg = f"{port}: can't open ({e}) - adapter plugged in and in range?"
                continue
            try:
                info = adapter.init()
            except OSError as e:
                info, msg = None, f"{port}: link failed ({e})"
            if info:
                return adapter, info
            adapter.close()
            msg = msg or (f"{port}: opened but the adapter didn't answer - press the MX+ button "
                          f"(ignition on keeps it awake), or Disconnect it in Bluetooth settings; still retrying")
        if not ports:
            shown = ", ".join(os.path.basename(p) for p in seen) or "none"
            msg = (f"waiting for a serial port matching /{args.port_match}/ - pair the MX+ "
                   f"in Bluetooth settings (ports now: {shown})")
        if msg != last_msg:
            print(f"  {msg}")
            last_msg = msg
        if deadline and time.time() > deadline:
            raise SystemExit("gave up waiting for the adapter (use --port or --port-match?)")
        time.sleep(2)


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

class IdStat:
    __slots__ = ("count", "last", "last_ts", "first_ts", "rate", "win_t0", "win_n", "changed_ts")

    def __init__(self, ts):
        self.count = 0
        self.last = b""
        self.last_ts = ts
        self.first_ts = ts
        self.rate = 0.0
        self.win_t0 = ts         # rate = frames per >=1s window: Bluetooth delivers
        self.win_n = 0           # frames in bursts, so per-frame intervals are meaningless
        self.changed_ts = [0.0] * 8


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.ids = {}            # (id, ext) -> IdStat
        self.baseline = None     # (id, ext) -> bytes
        self.noise = {}          # (id, ext) -> [8 bitmasks] that change on their own; ignored in diffs
        self.window = None       # while capturing: (id, ext) -> [last data, [64 per-bit flip counts]]
        self.findings = {}       # guided test name -> result lines
        self.total = 0
        self.status = []         # recent non-frame lines from adapter
        self.markers = []
        self.marks_path = None
        self.last_rx = None      # wall time of the newest frame
        self.link_lost_at = None # wall time the link dropped; None while connected
        self.gaps = []           # [lost_at, restored_at] per dropout
        self.start = time.time()
        self.running = True
        self.replay_done = False

    def add(self, ts, can_id, ext, data):
        key = (can_id, ext)
        with self.lock:
            st = self.ids.get(key)
            if st is None:
                st = self.ids[key] = IdStat(ts)
            if st.count:
                st.win_n += 1
                if ts - st.win_t0 >= 1.0:
                    st.rate = st.win_n / (ts - st.win_t0)
                    st.win_t0, st.win_n = ts, 0
            for i, b in enumerate(data):
                if i >= len(st.last) or st.last[i] != b:
                    st.changed_ts[i] = ts
            if self.window is not None:
                w = self.window.get(key)
                if w is None:
                    self.window[key] = [data, [0] * 64]
                else:
                    for i in range(min(len(w[0]), len(data))):
                        x = w[0][i] ^ data[i]
                        for b in range(8):
                            if x >> b & 1:
                                w[1][i * 8 + b] += 1
                    w[0] = data
            st.last = data
            st.last_ts = ts
            st.count += 1
            self.total += 1
            self.last_rx = time.time()

    def note(self, text):
        with self.lock:
            self.status.append(f"{datetime.now():%H:%M:%S} {text}")
            self.status = self.status[-5:]

    def mark(self, label, detail=()):
        """Record a marker (timestamp comparable with the .log) plus optional detail lines."""
        line = f"{label} @ {time.time():.6f}"
        with self.lock:
            self.markers.append(line)
        if self.marks_path:
            with open(self.marks_path, "a") as mf:
                mf.write(line + "\n" + "".join(d + "\n" for d in detail))

    def start_window(self):
        """Start recording which bits toggle (between frames received from now on)."""
        with self.lock:
            self.window = {}

    def end_window(self):
        """Stop recording. Returns (snapshot, toggles, busy):
          snapshot - id -> latest data, for every ID seen so far
          toggles  - id -> [8 bitmasks] of bits that flipped at least once
          busy     - id -> [8 bitmasks] of bits that flipped BUSY_FLIPS+ times (blinking)
        toggles and busy only hold the IDs received during the window."""
        with self.lock:
            win, self.window = self.window or {}, None
            snap = {k: st.last for k, st in self.ids.items()}

        def masks(counts, least):
            return [sum(1 << b for b in range(8) if counts[i * 8 + b] >= least) for i in range(8)]
        return (snap, {k: masks(w[1], 1) for k, w in win.items()},
                {k: masks(w[1], BUSY_FLIPS) for k, w in win.items()})

    def link_down(self, why):
        with self.lock:
            self.link_lost_at = time.time()
        self.note(f"link lost: {why}")
        self.mark("LINK LOST")

    def link_up(self):
        with self.lock:
            self.gaps.append([self.link_lost_at, time.time()])
            self.link_lost_at = None
        self.note("reconnected")
        self.mark("LINK RESTORED")


def diff_bits(state, key, i, byte):
    """Bits of `byte` that differ from the baseline, ignoring learned noise bits.
    Call with state.lock held and a baseline set."""
    b = state.baseline.get(key)
    if b is None or i >= len(b):
        return 0xFF
    return (byte ^ b[i]) & ~state.noise.get(key, (0,) * 8)[i] & 0xFF


def baseline_diff(state):
    """Lines describing every byte that differs from the baseline (noise ignored).
    Call with state.lock held."""
    out = []
    for (can_id, ext), st in sorted(state.ids.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        b = state.baseline.get((can_id, ext))
        if b is None:
            out.append(f"  {fmt_id(can_id, ext)} NEW {st.last.hex(' ').upper()}")
            continue
        changes = [f"b{i} {b[i]:02X}->{x:02X}" if i < len(b) else f"b{i} -->{x:02X}"
                   for i, x in enumerate(st.last) if diff_bits(state, (can_id, ext), i, x)]
        if changes:
            out.append(f"  {fmt_id(can_id, ext)} " + ", ".join(changes))
    return out


def id_summary(state):
    with state.lock:
        return {fmt_id(*k): {"count": st.count, "hz": round(st.rate, 2), "last": st.last.hex().upper()}
                for k, st in sorted(state.ids.items(), key=lambda kv: (kv[0][1], kv[0][0]))}


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def monitor(adapter, state, log, iface, prefer_ext, filtered):
    """Read monitor output until state.running is cleared. Raises OSError
    (pyserial's SerialException is one) when the link dies."""
    buf = ""
    adapter.start_monitor(filtered)
    last_rx = time.time()
    while state.running:
        chunk = adapter.ser.read(4096)
        if not chunk:
            if time.time() - last_rx > STALL_SECS:
                # total silence: either a quiet bus or a dead link that didn't raise
                adapter.stop_monitor()
                if not adapter.cmd("ATI"):
                    raise OSError("adapter stopped responding")
                state.note("bus quiet - adapter alive")
                adapter.start_monitor(filtered)
                last_rx = time.time()
            continue
        last_rx = time.time()
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


def serial_reader(adapter, state, log, iface, prefer_ext, filtered, reconnect):
    while state.running:
        try:
            monitor(adapter, state, log, iface, prefer_ext, filtered)
        except OSError as e:
            state.link_down(e)
            adapter.close_port()
            while state.running:
                time.sleep(2)
                try:
                    if reconnect(adapter):
                        state.link_up()
                        break
                except (OSError, RuntimeError):
                    pass
                adapter.close_port()
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
# Guided tests
# ---------------------------------------------------------------------------

# Each test steps through its states --rounds times and finishes back in the
# first state. A state is (label, instruction). HOLD means keep holding the
# control until the capture countdown ends. Add your own here, or press [+]
# in the test menu.
TESTS = [
    ("Headlight switch", [("AUTO", "Headlight knob in AUTO, its normal resting position"),
                          ("OFF", "Turn the headlight knob to OFF and HOLD it there (it springs back to AUTO)"),
                          ("PARK", "Turn the headlight knob to PARKING LAMPS"),
                          ("ON", "Turn the headlight knob to HEADLIGHTS ON")]),
    ("High beams", [("low", "Headlights ON, stalk in its normal position"),
                    ("high", "Push the stalk forward: HIGH BEAMS on")]),
    ("Flash-to-pass", [("released", "Leave the turn signal stalk alone"),
                       ("held", "PULL and HOLD the stalk toward you (flash-to-pass)")]),
    ("Fog lamps", [("off", "Fog lamps OFF (parking lamps or headlights on)"),
                   ("on", "Press the fog lamp button: fog lamps ON")]),
    ("Left turn signal", [("off", "Turn signal OFF"), ("on", "Stalk DOWN: LEFT turn signal on")]),
    ("Right turn signal", [("off", "Turn signal OFF"), ("on", "Stalk UP: RIGHT turn signal on")]),
    ("Hazards", [("off", "Hazard flashers OFF"), ("on", "Press the hazard button: hazards ON")]),
    ("Brake pedal", [("released", "Foot OFF the brake"), ("pressed", "PRESS and HOLD the brake pedal")]),
    ("Parking brake", [("released", "Parking brake RELEASED"), ("applied", "Parking brake APPLIED")]),
    ("Driver door", [("closed", "Driver door CLOSED"), ("open", "Driver door OPEN")]),
    ("Passenger door", [("closed", "Front passenger door CLOSED"), ("open", "Front passenger door OPEN")]),
    ("Rear doors", [("closed", "Both rear doors CLOSED"), ("open", "Both rear doors OPEN")]),
    ("Door lock switch", [("unlocked", "Press UNLOCK on the driver door switch"),
                          ("locked", "Press LOCK on the driver door switch")]),
    ("Key fob", [("unlocked", "Press UNLOCK on the key fob"), ("locked", "Press LOCK on the key fob")]),
    ("Dome light", [("off", "Interior / dome light OFF"), ("on", "Interior / dome light ON")]),
    ("Dash dimmer", [("bright", "Roll the dash dimmer to BRIGHTEST"), ("dim", "Roll the dash dimmer to DIMMEST")]),
    ("Wipers", [("off", "Wipers OFF (wet the glass first)"), ("low", "Wipers LOW"), ("high", "Wipers HIGH")]),
    ("Washer", [("off", "Leave the washer alone"), ("spray", "PULL and HOLD the washer")]),
    ("Driver seatbelt", [("unbuckled", "Driver seatbelt UNBUCKLED"), ("buckled", "Driver seatbelt BUCKLED")]),
    ("Volume + button", [("released", "Leave the steering wheel buttons alone"),
                         ("held", "HOLD the steering wheel VOLUME + button")]),
]
MENU_KEYS = "123456789abcdefghijklmnopqrstuvwxyz"


def _by_label(windows, values):
    """{label: [value for each window with that label]}, labels in first-seen order."""
    out = {}
    for w, v in zip(windows, values):
        out.setdefault(w[0], []).append(v)
    return out


def _split(on, off):
    """Given {label: [bool per window]} for 'on' and 'off', the labels that are on in
    every window, if every other label is off in every window (and both kinds exist)."""
    always = [l for l, vs in on.items() if all(vs)]
    never = [l for l, vs in off.items() if not any(vs)]
    return always if always and never and len(always) + len(never) == len(on) else None


def _strict_signals(windows, noise):
    """Signals that every capture agrees on; see find_signals."""
    if len({w[0] for w in windows}) < 2:
        return []
    order = lambda k: (k[1], k[0])
    zero = (0,) * 8
    lines = []
    keys = set.intersection(*(set(w[1]) for w in windows))
    for key in sorted(keys, key=order):
        for i in range(min(len(w[1][key]) for w in windows)):
            quiet = ~noise.get(key, zero)[i] & 0xFF
            toggles = [w[2].get(key, zero)[i] for w in windows]
            busy = [w[3].get(key, zero)[i] for w in windows]
            vals = _by_label(windows, [w[1][key][i] for w in windows])
            mask = quiet
            for t in toggles:
                mask &= ~t
            for vs in vals.values():
                for v in vs[1:]:
                    mask &= ~(v ^ vs[0])
            firsts = [vs[0] for vs in vals.values()]
            differ = 0
            for v in firsts[1:]:
                differ |= v ^ firsts[0]
            bits = [b for b in range(8) if (mask & differ) >> b & 1]
            if len(bits) == 1:
                desc = "  ".join(f"{l}={vs[0] >> bits[0] & 1}" for l, vs in vals.items())
                lines.append(f"{fmt_id(*key)} byte {i} bit {bits[0]}:  {desc}")
            elif bits:
                desc = "  ".join(f"{l}={vs[0]:02X}" for l, vs in vals.items())
                lines.append(f"{fmt_id(*key)} byte {i} bits {','.join(map(str, bits))}:  {desc}")
            for b in range(8):
                if quiet >> b & 1:
                    labels = _split(_by_label(windows, [v >> b & 1 for v in busy]),
                                    _by_label(windows, [v >> b & 1 for v in toggles]))
                    if labels:
                        lines.append(f"{fmt_id(*key)} byte {i} bit {b}:  blinks while {'/'.join(labels)}")
    for key in sorted(set().union(*(set(w[2]) for w in windows)) - set(noise), key=order):
        present = _by_label(windows, [key in w[2] for w in windows])
        labels = _split(present, present)
        if labels:
            lines.append(f"{fmt_id(*key)} only sent while {'/'.join(labels)}")
    return lines


def find_signals(windows, noise, round_len=None):
    """Compare the capture windows of a guided test; windows = [(label, snapshot, toggles, busy)]
    as returned by State.end_window.
    Returns result lines for three kinds of evidence, which every capture must agree on:
      steady  - bits with a fixed value in each state that differs between states
      blinks  - bits that flip BUSY_FLIPS+ times in every capture of some states and never
                in the others (turn signals, hazards)
      sent    - IDs only transmitted in some states (skipping IDs already seen while the
                baseline was learned: slow periodic messages land in some captures by chance)
    noise is the baseline's toggle map, so its keys are the IDs seen while learning.

    With round_len (states per round) and 3+ rounds, one bad round (a control that
    slipped) is tolerated: each round is left out in turn, and signals that only
    appear without it are listed under a NOTE naming that round. Leaving out whole
    rounds, rather than single odd captures, keeps chance matches as rare as in a
    clean 2-round test."""
    lines = _strict_signals(windows, noise)
    n_rounds = len(windows) // round_len if round_len else 0
    if n_rounds < 3:
        return lines
    for r in range(n_rounds):
        drop = range(r * round_len, (r + 1) * round_len)
        rest = [w for n, w in enumerate(windows) if n not in drop]
        extra = [l for l in _strict_signals(rest, noise) if l not in lines]
        if extra:
            lines.append(f"NOTE round {r + 1} (steps {drop[0] + 1}-{drop[-1] + 1}) disagrees with the "
                         f"others - a control was probably out of position. Without it:")
            lines += [f"  {l}" for l in extra]
    return lines


# ---------------------------------------------------------------------------
# Terminal UI
# ---------------------------------------------------------------------------

RESET, REV, YEL, CYN, DIM, GRN, BOLD = ("\x1b[0m", "\x1b[7m", "\x1b[33m", "\x1b[36m",
                                        "\x1b[2m", "\x1b[32m", "\x1b[1m")


class Keys:
    """Non-blocking key reader for Windows and POSIX terminals. Arrow and
    function keys are swallowed so their escape sequences don't act as commands."""

    def __init__(self):
        self.win = os.name == "nt"
        self.old = None
        self.pending = []
        if not self.win and sys.stdin.isatty():
            import termios
            import tty
            self.old = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())

    def get(self):
        if self.win:
            import msvcrt
            if not msvcrt.kbhit():
                return None
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):  # arrow / function key: drop its second half
                msvcrt.getwch()
                return None
            return ch
        if not self.pending:
            import select
            if not (sys.stdin.isatty() and select.select([sys.stdin], [], [], 0)[0]):
                return None
            # os.read, not sys.stdin.read: buffered reads hide queued keys from select()
            self.pending = list(os.read(sys.stdin.fileno(), 64).decode(errors="ignore"))
            if self.pending[:1] == ["\x1b"] and len(self.pending) > 1:
                self.pending = []  # escape sequence (arrow key etc.)
                return None
        return self.pending.pop(0) if self.pending else None

    def restore(self):
        if self.old is not None:
            import termios
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old)


def popcount(x):
    return bin(x).count("1")


class Console:
    """Live table plus the guided workflow. Modes: idle, menu (pick a test),
    input (typing a label), learn (baseline countdown), await (test step waiting
    for SPACE), capture (test step countdown), quit (confirm), exit."""

    SORTS = ["id", "count", "changed"]

    def __init__(self, state, title, args):
        self.state, self.title, self.args = state, title, args
        self.mode, self.t_end = "idle", 0.0
        self.prompt, self.buf, self.on_input = "", "", None
        self.test = None          # {"name", "seq": [(label, instruction)], "i", "windows"}
        self.pending = None       # test to start once the baseline has been learned
        self.last_test = None     # finished test, kept so [r] can redo its final step
        self.result = None        # (test name, lines) of the last finished test
        self.message = ""
        self.focus, self.sort_i, self.paused, self.n_marks = False, 0, False, 0
        self.tests = list(TESTS)

    # -- main loop ---------------------------------------------------------

    def run(self):
        keys = Keys()
        last_draw = 0.0
        try:
            while self.state.running and self.mode != "exit":
                pressed = False
                while True:
                    k = keys.get()
                    if k is None:
                        break
                    self.handle(k)
                    pressed = True
                self.tick()
                now = time.time()
                if self.args.no_ui:
                    if now - last_draw >= self.args.refresh:
                        lost = "  LINK LOST" if self.state.link_lost_at else ""
                        print(f"\rframes {self.state.total}  ids {len(self.state.ids)}{lost}   ", end="", flush=True)
                        last_draw = now
                    if self.state.replay_done:
                        print(f"\rframes {self.state.total}  ids {len(self.state.ids)}   ")
                        break
                elif pressed or (not self.paused and now - last_draw >= self.args.refresh):
                    self.render()
                    last_draw = now
                time.sleep(0.03)
        except KeyboardInterrupt:
            pass
        finally:
            self.state.running = False
            keys.restore()

    # -- keys --------------------------------------------------------------

    def handle(self, k):
        st = self.state
        if self.mode == "input":
            if k in ("\r", "\n"):
                text, self.mode = self.buf.strip(), "idle"
                if text:
                    self.on_input(text)
            elif k == "\x1b":
                self.mode, self.message = "idle", "cancelled"
            elif k in ("\x7f", "\b"):
                self.buf = self.buf[:-1]
            elif k.isprintable():
                self.buf += k
            return
        k = k.lower()
        if self.args.no_ui:
            if k == "q":
                self.mode = "exit"
            return
        if self.mode == "quit":
            self.mode = "exit" if k == "q" else "idle"
        elif self.mode == "menu":
            if k == "+":
                self.ask("New test as  name: state1,state2,...   e.g.  Mirrors: folded,unfolded", self.custom_test)
            elif k in MENU_KEYS[:len(self.tests)]:
                self.start_test(*self.tests[MENU_KEYS.index(k)])
            else:
                self.mode = "idle"
        elif self.mode in ("learn", "capture"):
            if k == "x":
                self.abort()
        elif self.mode == "await":
            if k == " ":
                self.begin("capture", self.args.window)
            elif k == "r":
                self.redo()
            elif k == "x":
                self.abort()
            else:
                self.view_key(k)
        elif k == "q":
            self.mode = "quit"
        elif k == "b":
            self.begin("learn", self.args.learn)
        elif k == "c":
            with st.lock:
                st.baseline, st.noise = None, {}
            self.focus, self.message = False, "baseline cleared"
        elif k == "t":
            self.mode = "menu"
        elif k == "r" and self.last_test:
            self.test, self.last_test, self.result = self.last_test, None, None
            self.redo()
        elif k == "m":
            self.ask("Label for this marker - what did you just do?", self.add_mark)
        else:
            self.view_key(k)

    def view_key(self, k):
        if k == "f":
            if self.state.baseline is None:
                self.message = "set a baseline first ([b])"
            else:
                self.focus = not self.focus
        elif k == "s":
            self.sort_i = (self.sort_i + 1) % len(self.SORTS)
        elif k == "p":
            self.paused = not self.paused

    def ask(self, prompt, callback):
        self.mode, self.prompt, self.buf, self.on_input = "input", prompt, "", callback

    # -- actions -----------------------------------------------------------

    def begin(self, mode, secs):
        self.state.start_window()
        self.mode, self.t_end = mode, time.time() + secs

    def tick(self):
        if self.mode not in ("learn", "capture") or time.time() < self.t_end:
            return
        st = self.state
        snap, toggles, busy = st.end_window()
        if self.mode == "learn":
            with st.lock:
                st.baseline, st.noise = snap, toggles
            n = sum(popcount(m) for ms in toggles.values() for m in ms)
            st.mark("BASELINE", [f"  {n} bits change on their own and are ignored"])
            self.focus, self.mode = True, "idle"
            self.message = (f"baseline set - ignoring {n} bits that change on their own; "
                            f"table now shows only changed IDs ([f] for all)")
            if self.pending:
                self.start_test(*self.pending)
            return
        t = self.test
        label = t["seq"][t["i"]][0]
        t["windows"].append((label, snap, toggles, busy))
        st.mark(f"STEP {t['name']} | {label} | {t['i'] + 1}/{len(t['seq'])}",
                [f"  window {self.t_end - self.args.window:.6f} {self.t_end:.6f}"])
        t["i"] += 1
        if t["i"] < len(t["seq"]):
            self.mode = "await"
        else:
            self.finish_test()

    def redo(self):
        """Throw away the previous step's capture and go back to it."""
        t = self.test
        if not t["windows"]:
            self.message = "nothing to redo yet - this is the first step"
            return
        t["windows"].pop()
        t["i"] -= 1
        label = t["seq"][t["i"]][0]
        self.state.mark(f"REDO {t['name']} | {label} | {t['i'] + 1}/{len(t['seq'])}")
        self.mode, self.message = "await", f"redoing step {t['i'] + 1} ({label})"

    def start_test(self, name, states):
        if self.state.baseline is None:
            # without learned noise, slow counters show up as false "signals"
            self.pending = (name, states)
            self.begin("learn", self.args.learn)
            return
        self.pending, self.last_test = None, None
        seq = [s for _ in range(self.args.rounds) for s in states] + [states[0]]
        self.test = {"name": name, "seq": seq, "i": 0, "windows": [], "round_len": len(states)}
        self.state.mark(f"TEST {name} START", [f"  states: {', '.join(l for l, _ in states)}"])
        self.mode, self.result, self.message = "await", None, ""

    def finish_test(self):
        st, t = self.state, self.test
        lines = find_signals(t["windows"], st.noise, t["round_len"])
        st.mark(f"RESULT {t['name']}: {len(lines)} candidate(s)", ["  " + l for l in lines])
        with st.lock:
            st.findings[t["name"]] = lines
        self.result, self.test, self.mode, self.last_test = (t["name"], lines), None, "idle", t
        self.message = f"'{t['name']}' finished - [t] next test, [r] redo its last step"

    def abort(self):
        self.state.end_window()
        if self.test:
            self.state.mark(f"TEST {self.test['name']} ABORTED")
            self.message = f"'{self.test['name']}' aborted"
        else:
            self.message = "baseline cancelled"
        self.test, self.pending, self.mode = None, None, "idle"

    def custom_test(self, text):
        name, _, rest = text.partition(":")
        labels = [s.strip() for s in rest.split(",") if s.strip()]
        if not name.strip() or len(labels) < 2:
            self.message = "custom test needs a name and at least two states, e.g.  Mirrors: folded,unfolded"
            return
        test = (name.strip(), [(l, f"Set it to: {l.upper()}") for l in labels])
        self.tests.append(test)
        self.start_test(*test)

    def add_mark(self, text):
        st = self.state
        self.n_marks += 1
        with st.lock:
            detail = baseline_diff(st) if st.baseline is not None else []
        st.mark(f"MARK {self.n_marks} {text}", detail)
        self.message = f"marker {self.n_marks} saved: {text} ({len(detail)} changed IDs recorded)"

    # -- drawing -----------------------------------------------------------

    def guide(self, now, cols):
        st = self.state
        if self.mode == "learn":
            return [f"{YEL}{BOLD}LEARNING BASELINE{RESET}  don't touch anything ... {self.t_end - now:4.1f}s",
                    f"{DIM}recording which bits change on their own (counters, sensors) so they're ignored"
                    f"   [x] cancel{RESET}"] + ([f"then the '{self.pending[0]}' test starts"] if self.pending else [])
        if self.mode in ("await", "capture"):
            t = self.test
            label, what = t["seq"][t["i"]]
            head = f"{CYN}{BOLD}TEST: {t['name']}{RESET}   step {t['i'] + 1} of {len(t['seq'])}"
            hold = "HOLD" in what
            if self.mode == "capture":
                keep = (f"{YEL}{BOLD}KEEP HOLDING{RESET} until the countdown ends" if hold
                        else "keep still")
                return [head, f"  {YEL}{BOLD}CAPTURING '{label}'{RESET}  {keep} ... {self.t_end - now:4.1f}s"]
            first = t["i"] == 0
            then = (f"  then, {BOLD}still holding{RESET}, press {BOLD}[SPACE]{RESET} and keep holding for "
                    f"{self.args.window:g}s" if hold else
                    f"  then press {BOLD}[SPACE]{RESET} and keep still for {self.args.window:g}s")
            if first:
                then = then.replace("  then", "  already like that? just", 1) if not hold else then
            redo = "" if first else "   [r] redo previous step"
            return [head, f"  {BOLD}{'STARTING POSITION' if first else 'DO NOW'} >  {what}{RESET}",
                    f"{then}        {DIM}[x] abort test{redo}{RESET}"]
        if self.mode == "menu":
            out = [f"{BOLD}GUIDED TESTS{RESET} - press a key to start   "
                   f"{DIM}({self.args.rounds} rounds each, {self.args.window:g}s per step){RESET}"]
            cells = []
            for k, (name, _) in zip(MENU_KEYS, self.tests):
                found = st.findings.get(name)
                cells.append((f"[{k}] {name}" + (f"  done:{len(found)}" if found is not None else ""),
                              found is not None))
            width = 30
            ncol = max(1, min(3, cols // width))
            nrow = -(-len(cells) // ncol)
            for r in range(nrow):
                row = ""
                for c in range(ncol):
                    idx = c * nrow + r
                    if idx < len(cells):
                        text, done = cells[idx]
                        row += f"{GRN}{text:<{width}}{RESET}" if done else f"{text:<{width}}"
                out.append("  " + row)
            out.append(f"{DIM}[+] add your own test     any other key closes{RESET}")
            return out
        if self.mode == "input":
            return [f"{BOLD}{self.prompt}{RESET}", f"  > {self.buf}_", f"{DIM}[Enter] save   [Esc] cancel{RESET}"]
        if self.mode == "quit":
            return [f"{YEL}{BOLD}Quit?{RESET}  press [q] again to stop logging, any other key to keep going"]
        if st.baseline is None:
            return [f"{BOLD}START >{RESET}  leave everything alone and press {BOLD}[b]{RESET} - learns "
                    f"{self.args.learn:g}s of normal background chatter so it can be ignored",
                    f"{DIM}then press [t] for guided tests (headlights, doors, turn signals ...){RESET}"]
        return [f"{BOLD}NEXT >{RESET}  press {BOLD}[t]{RESET} to pick a guided test,  or do something "
                f"yourself and press {BOLD}[m]{RESET} to label it",
                f"{DIM}[b] re-learns the baseline if the table fills up with things you didn't touch{RESET}"]

    def result_lines(self, limit=8):
        if not self.result or self.mode not in ("idle", "menu"):
            return []
        name, lines = self.result
        if not lines:
            return [f"{BOLD}RESULT: {name}{RESET} - no consistent signal found. It may live on the "
                    f"high-speed bus (--bus hs), need more rounds, or need a longer --window."]
        out = [f"{BOLD}{GRN}RESULT: {name}{RESET} - {len(lines)} candidate(s)  {DIM}(all saved in the .marks file){RESET}"]
        out += [f"  {l}" for l in lines[:limit]]
        if len(lines) > limit:
            out.append(f"{DIM}  ... {len(lines) - limit} more in the .marks file{RESET}")
        return out

    def keybar(self):
        if self.mode == "await":
            redo = "   [r] redo previous step" if self.test["windows"] else ""
            return f"[SPACE] capture{redo}   [x] abort test   [f] changed/all   [s] sort   [p] pause"
        if self.mode == "idle":
            redo = f"   [r] redo last step of '{self.last_test['name']}'" if self.last_test else ""
            return ("[b] baseline   [t] tests   [m] marker+label   [f] changed/all   [s] sort   "
                    f"[p] pause   [c] clear baseline   [q] quit{redo}")
        return ""

    def render(self):
        st = self.state
        now = time.time()
        try:
            size = os.get_terminal_size()
            cols, lines_avail = size.columns, size.lines
        except OSError:
            cols, lines_avail = 120, 50
        sort_mode = self.SORTS[self.sort_i]
        with st.lock:
            has_base = st.baseline is not None
            rows = []
            for key, s in st.ids.items():
                new = has_base and key not in st.baseline
                diffs = [diff_bits(st, key, i, x) for i, x in enumerate(s.last)] if has_base else []
                noisy = [st.noise.get(key, (0,) * 8)[i] for i in range(len(s.last))] if has_base else []
                rows.append((key, s, new, diffs, noisy))
            total, status, n_markers = st.total, list(st.status), len(st.markers)
            last_rx, lost_at = st.last_rx, st.link_lost_at
        elapsed = max(now - st.start, 1e-6)
        n_ids = len(rows)
        if self.focus and has_base:
            rows = [r for r in rows if r[2] or any(r[3])]
        if sort_mode == "count":
            rows.sort(key=lambda r: -r[1].count)
        elif sort_mode == "changed":
            rows.sort(key=lambda r: (not r[2], -sum(popcount(d) for d in r[3]), r[0][1], r[0][0]))
        else:
            rows.sort(key=lambda r: (r[0][1], r[0][0]))

        if lost_at:
            link = f"{YEL}LINK LOST {now - lost_at:.0f}s - reconnecting{RESET}"
        elif last_rx:
            link = f"last frame {now - last_rx:.1f}s ago"
        else:
            link = "no frames yet"
        rule = f"{DIM}{'-' * min(cols, 110)}{RESET}"
        top = [f"{CYN}{self.title}{RESET}",
               f"frames {total} ({total / elapsed:.0f}/s)  ids {n_ids}  {link}  "
               f"baseline {'SET' if has_base else 'off'}  view {'changed-only' if self.focus and has_base else 'all'}"
               f"  sort {sort_mode}  markers {n_markers}" + (f"  {YEL}PAUSED [p]{RESET}" if self.paused else ""),
               rule]
        if total == 0 and elapsed > 5 and not lost_at:
            top.append(f"{YEL}no frames after {elapsed:.0f}s: ignition on? right bus (--bus hs/sw)? "
                       f"filter too tight?{RESET}")
        guide = self.guide(now, cols) + [rule]
        result = self.result_lines()
        if result:
            result.append(rule)
        bottom = [rule]
        if self.message:
            bottom.append(f"{GRN}{self.message}{RESET}")
        if status:
            bottom.append(f"{DIM}adapter: {' | '.join(status[-3:])}{RESET}")
        if self.keybar():
            bottom.append(f"{BOLD}{self.keybar()}{RESET}")

        room = max(lines_avail - len(top) - len(guide) - len(result) - len(bottom) - 3, 3)
        table = [f"{'ID':>8}  {'count':>7}  {'Hz':>6}  data  {DIM}(yellow = differs from baseline,"
                 f" inverse = just changed){RESET}"]
        for key, s, new, diffs, noisy in rows[:room]:
            cells = []
            for i, byte in enumerate(s.last):
                txt = f"{byte:02X}"
                recent = now - s.changed_ts[i] < 1.0 and s.count > 1 and not (noisy and noisy[i])
                if diffs and diffs[i]:
                    txt = f"{YEL}{txt}{RESET}"
                if recent:
                    txt = f"{REV}{txt}{RESET}"
                cells.append(txt)
            tag = f" {GRN}NEW{RESET}" if new else ""
            line = f"{fmt_id(*key):>8}  {s.count:>7}  {s.rate:>6.1f}  {' '.join(cells)}{tag}"
            table.append(f"{DIM}{line}{RESET}" if now - s.last_ts > 2.0 else line)
        if len(rows) > room:
            table.append(f"{DIM}... {len(rows) - room} more ids (bigger terminal, [f] changed-only, or --filter){RESET}")
        if self.focus and has_base and not rows:
            table.append(f"{DIM}  nothing differs from the baseline yet - do something in the truck{RESET}")
        sys.stdout.write("\x1b[H\x1b[J" + "\n".join(top + guide + result + table + bottom) + "\n")
        sys.stdout.flush()


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


def setup_bus(adapter, proto, filters, ext):
    """Select the protocol and filters; returns the protocol description."""
    kind, n = proto
    desc = adapter.set_protocol(**{kind: n})
    if filters:
        adapter.set_filters(filters, ext)
    return desc


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_filter(text, ext):
    full = 0x1FFFFFFF if ext else 0x7FF
    if ":" in text:
        p, m = text.split(":", 1)
        return int(p, 16), int(m, 16)
    return int(text, 16), full


def write_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=1)


def main():
    ap = argparse.ArgumentParser(description="STN/OBDLink CAN logger and diff console")
    ap.add_argument("--port", help="serial port, e.g. /dev/cu.OBDLinkMXPlus-... or COM5 (default: auto-detect)")
    ap.add_argument("--port-match", default=PORT_MATCH,
                    help="regex (case-insensitive) used to auto-detect the adapter's port (default: %(default)s)")
    ap.add_argument("--wait", type=float, default=0, help="seconds to wait for the adapter (default 0 = forever)")
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
    ap.add_argument("--learn", type=float, default=10.0, help="seconds the [b] baseline spends learning noise")
    ap.add_argument("--window", type=float, default=3.0, help="seconds captured per guided test step")
    ap.add_argument("--rounds", type=int, default=3, help="times each guided test cycles through its states (min 2)")
    args = ap.parse_args()
    if args.rounds < 2:
        ap.error("--rounds must be at least 2: with one capture per state, random bits look like signals")

    if os.name == "nt":
        os.system("")  # enable ANSI escape handling in Windows consoles

    ext = args.ext or (args.bus == "sw" and not args.std)
    state = State()

    if args.replay:
        title = f"REPLAY {args.replay}"
        t = threading.Thread(target=replay_reader, args=(args.replay, state, args.speed), daemon=True)
        t.start()
        Console(state, title, args).run()
        return

    os.makedirs(args.outdir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(args.outdir, f"{stamp}_{args.bus}")
    print("looking for the adapter ... (Ctrl-C to abort)")
    adapter, info = connect(args, base + ".raw" if args.raw else None)
    try:
        print(f"  port:     {adapter.port}")
        print(f"  adapter:  {info['device'] or info['firmware'] or '(no STI response - not an STN device?)'}")
        if info["device"] and info["firmware"]:
            print(f"  firmware: {info['firmware']}")
        print(f"  voltage:  {info['voltage'] or '?'}")
        for w in info["warnings"]:
            print(f"  warning:  {w}")

        if args.probe:
            print("probing STN protocol numbers (takes ~30s) ...")
            protos = adapter.probe()
            write_json(CACHE, protos)
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
                write_json(CACHE, protos)
            stp = pick_protocol(protos, args.bus, ext)

        if stp is not None:
            proto = ("stp", stp)
        elif args.bus == "hs":
            proto = ("elm", 6)  # ISO 15765 11-bit 500k fallback
        else:
            raise SystemExit("no SW-CAN protocol found on this adapter (run --probe and pass --stp N)")
        filters = [parse_filter(f, ext) for f in args.filter]
        desc = setup_bus(adapter, proto, filters, ext)
        print(f"  protocol: {desc}")

        def reconnect(a):
            a.open()
            if a.init() is None:
                return False
            setup_bus(a, proto, filters, ext)
            return True

        iface = "can0" if args.bus == "hs" else "can1"
        log_path, state.marks_path, meta_path = base + ".log", base + ".marks", base + ".json"
        meta = {"started": datetime.now().isoformat(timespec="seconds"), "port": adapter.port,
                "adapter": info, "bus": args.bus, "protocol": desc, "proto": list(proto),
                "ext_ids": ext, "filters": args.filter, "log": log_path}
        write_json(meta_path, meta)
        print(f"  logging to {log_path}")
        time.sleep(0.5)
        with open(log_path, "w", buffering=1) as log:
            t = threading.Thread(target=serial_reader,
                                 args=(adapter, state, log, iface, ext, bool(filters), reconnect),
                                 daemon=True)
            t.start()
            Console(state, f"{args.bus.upper()}-CAN  {desc}  ->  {log_path}", args).run()
            t.join(timeout=3.0)
        try:
            adapter.stop_monitor()
        except OSError:
            pass
        meta.update(ended=datetime.now().isoformat(timespec="seconds"), frames=state.total,
                    link_gaps=state.gaps, findings=state.findings, ids=id_summary(state))
        write_json(meta_path, meta)
        print(f"\nstopped. {state.total} frames, {len(state.ids)} ids -> {log_path}")
        if state.gaps:
            print(f"  {len(state.gaps)} Bluetooth dropout(s), see {state.marks_path}")
    finally:
        adapter.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\naborted")
