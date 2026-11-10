#!/usr/bin/env python3
"""
canbus.py - shared core for the STN/OBDLink truck tools.

Holds the pieces used by more than one front-end: serial frame parsing, the
adapter wrapper (ELM327 + STN "ST" command set), ISO-TP (ISO 15765-2) transport
for diagnostics, and GM GMLAN diagnostic helpers.

Two completely separate ways of using the adapter live here:

  * MONITOR  - silent listening (ATCSM1). The adapter never ACKs or transmits;
               it only reports frames. This is what canlog.py uses. Nothing this
               side does can put a byte on the vehicle bus.

  * DIAGNOSTIC - active participant (ATCSM0). The adapter ACKs frames and sends
               requests + flow control. Reading (Mode 09, $1A, $22, DTCs) and
               writing (device control $AE) both use this. Entering diagnostic
               mode is the ONLY path that can transmit, and callers must opt in.

Nothing here transmits on construction or import. A diagnostic request goes out
only when request()/send_frame() is called.

Requirements: pip install pyserial
"""

import glob
import re
import sys
import time

# ---------------------------------------------------------------------------
# Frame parsing (shared with the candump logger)
# ---------------------------------------------------------------------------

HEX_RE = re.compile(r"^[0-9A-Fa-f]+$")


def fmt_id(can_id, ext):
    return f"{can_id:08X}" if ext else f"{can_id:03X}"


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


def parse_frame_line(line):
    """Parse a response line shown with headers (ATH1) but no DLC (ATD0), which
    is how the adapter prints frames outside monitor mode: <ID><DATA>, e.g.
    '641 06 50 03 00 00 00 00'. Returns (can_id, is_ext, data) or None."""
    s = line.strip().replace(" ", "")
    if not s or not HEX_RE.match(s):
        return None
    # An 11-bit line (3-char ID + even data) is odd length; a 29-bit line is even.
    # So validate the data length per width rather than on the whole string.
    for w in (3, 8):
        if len(s) >= w + 2 and (len(s) - w) % 2 == 0:
            try:
                can_id = int(s[:w], 16)
            except ValueError:
                continue
            ext = (w == 8)
            if not ext and can_id > 0x7FF:
                continue
            return can_id, ext, bytes.fromhex(s[w:])
    return None


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
# ISO-TP (ISO 15765-2) reassembly
# ---------------------------------------------------------------------------
# Single frame   : 0x0L  + L data bytes                 (L <= 7)
# First frame    : 0x1L LL + 6 data bytes               (12-bit total length)
# Consecutive    : 0x2N  + up to 7 data bytes           (N = sequence 0..F)
# Flow control   : 0x30 BS STmin                        (sent by the receiver)
# The adapter sends flow control itself when ATCFC1 is set, so we only have to
# reassemble the frames it prints.


def isotp_reassemble(frames):
    """Join the data halves of the ISO-TP frames from one arbitration ID.
    `frames` is a list of bytes (each the data field of one CAN frame), in
    arrival order. Returns the service payload, or None if it isn't ISO-TP."""
    if not frames:
        return None
    first = frames[0]
    if not first:
        return None
    pci = first[0] >> 4
    if pci == 0x0:               # single frame
        n = first[0] & 0x0F
        return first[1:1 + n]
    if pci == 0x1:               # first frame + consecutive frames
        if len(first) < 2:
            return None
        total = ((first[0] & 0x0F) << 8) | first[1]
        out = bytearray(first[2:])
        for f in frames[1:]:
            if f and (f[0] >> 4) == 0x2:
                out += f[1:]
        return bytes(out[:total])
    return None


def isotp_single(payload):
    """Build the 8-byte CAN data field for a single-frame request, zero-padded.
    Raises if the payload needs multiple frames (none of our requests do)."""
    if len(payload) > 7:
        raise ValueError("payload needs a multi-frame request (not implemented)")
    return bytes([len(payload)]) + payload + bytes(7 - len(payload))


# ---------------------------------------------------------------------------
# GMLAN / UDS service numbers and negative-response codes
# ---------------------------------------------------------------------------

SERVICE = {
    0x09: "ReadVehicleInfo (OBD Mode 09)",
    0x10: "InitiateDiagnosticOperation",
    0x1A: "ReadDataByIdentifier (GMLAN)",
    0x20: "ReturnToNormalMode",
    0x22: "ReadDataByIdentifier (UDS)",
    0x27: "SecurityAccess",
    0x28: "DisableNormalCommunication",
    0x3E: "TesterPresent",
    0xA9: "ReadDiagnosticInformation",
    0xAE: "DeviceControl",
}

# Negative response codes (byte after 0x7F <service>).
NRC = {
    0x10: "general reject",
    0x11: "service not supported",
    0x12: "sub-function not supported",
    0x13: "wrong message length",
    0x22: "conditions not correct",
    0x31: "request out of range",
    0x33: "security access denied",
    0x35: "invalid key",
    0x78: "response pending",
    0x7E: "service not supported in active session",
    0x7F: "service not supported in active session",
}


class Response:
    """A parsed diagnostic reply from one module."""

    def __init__(self, can_id, payload):
        self.can_id = can_id
        self.payload = payload or b""

    @property
    def negative(self):
        return len(self.payload) >= 3 and self.payload[0] == 0x7F

    @property
    def nrc(self):
        return self.payload[2] if self.negative else None

    @property
    def service(self):
        if self.negative:
            return self.payload[1]
        return self.payload[0] - 0x40 if self.payload else None

    def __repr__(self):
        who = fmt_id(self.can_id, self.can_id > 0x7FF)
        if self.negative:
            return f"<{who} NEG {SERVICE.get(self.service, hex(self.service))}: " \
                   f"{NRC.get(self.nrc, hex(self.nrc))}>"
        return f"<{who} {self.payload.hex(' ').upper()}>"


# Common GM 11-bit diagnostic addresses (confirm per vehicle with discover()).
FUNCTIONAL_REQ = 0x101      # GMLAN "all nodes" functional request
BCM_REQ, BCM_RESP = 0x241, 0x641
LEGISLATED_FUNC = 0x7DF     # OBD-II functional (Mode 01/09 etc.)


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

STALL_SECS = 15.0           # silence in monitor mode before a liveness check
BUSY_FLIPS = 3              # flips per capture for a bit to count as "blinking"


class Adapter:
    """ELM327 + STN adapter over a serial port. Construction opens the port but
    sends nothing; call init() to configure, then either monitor (silent) or
    the diagnostic methods (active)."""

    def __init__(self, port, baud=115200, raw_path=None):
        self.port, self.baud = port, baud
        self.ser = None
        self.diag = False       # True once in active diagnostic mode
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
        """Send an AT/ST command, return the response text (prompt stripped)."""
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
        """Reset the adapter until it answers; returns the banner or None."""
        for _ in range(tries):
            self.stop_monitor()
            r = self.cmd("ATZ", timeout=3.0)
            if r:
                return r
        return None

    def init(self, silent=True):
        """Reset and configure. silent=True keeps the adapter off the bus
        (ATCSM1, for monitoring); silent=False lets it ACK/transmit for
        diagnostics. Returns an info dict, or None if it never answered."""
        reset = self.wake()
        if reset is None:
            return None
        warnings = []
        base = ["ATE0", "ATL0", "ATS0", "ATH1", "ATD1", "ATCAF0", "ATAL"]
        mode = ["ATCSM1"] if silent else ["ATCSM0"]
        for c in base + mode:
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
            tag = f"STP{stp}" if stp else f"ATSP{elm}"
            raise RuntimeError(f"adapter rejected protocol ({tag}): {r}")
        desc = self.cmd("STPRS")
        return desc if "?" not in desc else self.cmd("ATDP")

    def probe(self, lo=1, hi=99, report=None):
        found = {}
        for n in range(lo, hi + 1):
            r = self.cmd(f"STP{n}", timeout=1.0)
            if "OK" in r:
                found[n] = self.cmd("STPRS", timeout=1.0)
                if report:
                    report(n, found[n])
        return found

    def set_filters(self, filters, ext):
        self.cmd("STFCP")  # clear pass filters
        for pat, mask in filters:
            w = 8 if ext else 3
            r = self.cmd(f"STFAP{pat:0{w}X},{mask:0{w}X}")
            if "?" in r:
                raise RuntimeError(f"filter rejected: {pat:X},{mask:X} -> {r}")

    # -- monitor (silent) --------------------------------------------------

    def start_monitor(self, filtered):
        self._rawlog(">>", "STM" if filtered else "STMA")
        self.ser.write(b"STM\r" if filtered else b"STMA\r")

    def stop_monitor(self):
        if self.ser is None:
            return
        self.ser.write(b"\r")
        time.sleep(0.3)
        self.ser.reset_input_buffer()

    # -- diagnostics (active) ----------------------------------------------

    def enter_diag(self, ext=False):
        """Switch to active diagnostic framing: headers on, DLC off, CAN auto
        formatting off (we build ISO-TP ourselves), adapter-side flow control
        on so multi-frame replies assemble without us chasing them."""
        self.cmd("ATCSM0")       # not silent: the adapter ACKs and transmits
        self.cmd("ATH1")         # show the responder's arbitration ID
        self.cmd("ATD0")         # no DLC column
        self.cmd("ATCAF0")       # we add ISO-TP PCI bytes ourselves
        r = self.cmd("ATCFC1")   # adapter answers flow control for multi-frame RX
        if "?" in r:
            self.cmd("STCFCPA")  # STN spelling, best effort
        self.diag = True

    def _set_tx(self, req_id, resp_id, ext):
        w = 8 if ext else 3
        self.cmd(f"ATSH{req_id:0{w}X}")          # our transmit header
        self.cmd(f"ATFCSH{req_id:0{w}X}")        # flow-control source header
        if resp_id is not None:
            self.cmd(f"ATCRA{resp_id:0{w}X}")    # only hear this responder
        else:
            self.cmd("ATCRA")                    # clear filter: hear everyone

    def send_frame(self, hexbytes, read_secs=1.0):
        """Transmit one already-built CAN data field (8 bytes of hex) and return
        the raw (id, ext, data) frames seen before the prompt. The caller must
        have set the header. This is the only method that puts data on the bus."""
        if not self.diag:
            raise RuntimeError("send_frame requires enter_diag() first")
        payload = hexbytes.replace(" ", "")
        self.ser.reset_input_buffer()
        self._rawlog(">>", payload)
        self.ser.write((payload + "\r").encode("ascii"))
        buf, end = b"", time.time() + read_secs
        while time.time() < end:
            chunk = self.ser.read(512)
            if chunk:
                buf += chunk
                if b">" in buf:
                    break
        text = buf.decode("ascii", errors="replace")
        self._rawlog("<<", text)
        frames = []
        for line in text.replace(">", "\n").replace("\r", "\n").split("\n"):
            line = line.strip()
            if not line or line == payload:
                continue
            fr = parse_frame_line(line)
            if fr:
                frames.append(fr)
        return frames

    def request(self, service_bytes, req_id, resp_id=None, ext=False, read_secs=1.0):
        """Send one single-frame diagnostic request and return a list of
        Response objects (one per responding module). service_bytes is the raw
        service payload, e.g. b'\\x3e\\x00' for TesterPresent or
        b'\\x1a\\x90' to read a data identifier."""
        self._set_tx(req_id, resp_id, ext)
        frame = isotp_single(bytes(service_bytes))
        raw = self.send_frame(frame.hex().upper(), read_secs=read_secs)
        by_id = {}
        for can_id, _e, data in raw:
            by_id.setdefault(can_id, []).append(data)
        return [Response(cid, isotp_reassemble(frs)) for cid, frs in by_id.items()]


# ---------------------------------------------------------------------------
# Finding the adapter (shared with canlog.py)
# ---------------------------------------------------------------------------

PORT_MATCH = r"obd|stn|elm|mx"


def candidate_ports(pattern):
    """Return (matching ports, all ports seen). On macOS only cu.* devices are
    used: tty.* opens block waiting for carrier detect."""
    from serial.tools import list_ports
    names = {p.device: f"{p.device} {p.description} {p.product or ''}" for p in list_ports.comports()}
    for dev in glob.glob("/dev/cu.*") + glob.glob("/dev/rfcomm*"):
        names.setdefault(dev, dev)
    if sys.platform == "darwin":
        names = {d: t for d, t in names.items() if not d.startswith("/dev/tty.")}
    rx = re.compile(pattern, re.I)
    return sorted(d for d, t in names.items() if rx.search(t)), sorted(names)


def connect(port=None, port_match=PORT_MATCH, baud=115200, wait=0, raw_path=None,
            silent=True, report=print):
    """Wait for the adapter's port, open it and wake the adapter.
    Returns (adapter, info). Gives up after `wait` seconds (0 = forever)."""
    deadline = time.time() + wait if wait else None
    last = None
    while True:
        ports, seen = ([port], []) if port else candidate_ports(port_match)
        msg = None
        for p in ports:
            try:
                adapter = Adapter(p, baud, raw_path)
            except OSError as e:
                msg = f"{p}: can't open ({e}) - adapter plugged in and in range?"
                continue
            try:
                info = adapter.init(silent=silent)
            except OSError as e:
                info, msg = None, f"{p}: link failed ({e})"
            if info:
                return adapter, info
            adapter.close()
            msg = msg or (f"{p}: opened but the adapter didn't answer - press the MX+ button, "
                          f"or on macOS run 'sudo pkill bluetoothd' and wait; still retrying")
        if not ports:
            shown = ", ".join(p.split("/")[-1] for p in seen) or "none"
            msg = f"waiting for a serial port matching /{port_match}/ (ports now: {shown})"
        if msg != last and report:
            report(f"  {msg}")
            last = msg
        if deadline and time.time() > deadline:
            raise SystemExit("gave up waiting for the adapter (use port= or port_match=?)")
        time.sleep(2)
