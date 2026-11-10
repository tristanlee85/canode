#!/usr/bin/env python3
"""
cantool.py - diagnostic read/write console for STN adapters (OBDLink MX+).

Companion to canlog.py. Where canlog.py only LISTENS, this tool actively talks
to vehicle modules: it reads data (VIN, module discovery, data identifiers,
DTCs) and, when you explicitly arm it, holds device-control overrides the way a
scan tool does (GMLAN DeviceControl $AE), refreshed with tester-present so the
override lasts only while this program runs.

    python cantool.py info                 adapter + VIN, read-only
    python cantool.py discover             list modules that answer diagnostics
    python cantool.py read --did 90        read a data identifier from a module
    python cantool.py control              interactive device-control console

SAFETY
  * Reading never changes vehicle state.
  * The control console sends nothing until you type `arm` and confirm you are
    parked. Every override is released (ReturnToNormalMode) when you quit, on
    Ctrl-C, and if the program dies - and the module itself reverts within
    seconds if tester-present stops. Test in a garage, in Park, engine off or
    idling, and stay away from powertrain / brake / airbag modules.
  * Defaults target the body control module (BCM, 0x241/0x641 on GM Global A);
    confirm with `discover` on your truck before trusting those IDs.

Requirements: pip install pyserial    (shares canbus.py with canlog.py)
"""

import argparse
import os
import signal
import sys
import threading
import time
from datetime import datetime

import canbus as cb


# ---------------------------------------------------------------------------
# Session: adapter in active diagnostic mode, with a transcript log
# ---------------------------------------------------------------------------

class DiagSession:
    def __init__(self, adapter, elm=6, stp=None, ext=False, log_path=None):
        self.a = adapter
        self.ext = ext
        self.log = open(log_path, "a", buffering=1) if log_path else None
        desc = adapter.set_protocol(stp=stp) if stp else adapter.set_protocol(elm=elm)
        self.protocol = desc
        adapter.enter_diag(ext=ext)
        self._note(f"# session start {datetime.now().isoformat(timespec='seconds')}  protocol={desc}")

    def _note(self, text):
        if self.log:
            self.log.write(text + "\n")

    def request(self, service_bytes, req_id, resp_id=None, read_secs=1.0, label=""):
        resps = self.a.request(service_bytes, req_id, resp_id, self.ext, read_secs)
        self._note(f"{time.time():.3f} TX {cb.fmt_id(req_id, self.ext)} "
                   f"{bytes(service_bytes).hex().upper()} {label}")
        for r in resps:
            self._note(f"{time.time():.3f} RX {r!r}")
        return resps

    def close(self):
        if self.log:
            self._note(f"# session end {datetime.now().isoformat(timespec='seconds')}")
            self.log.close()


# ---------------------------------------------------------------------------
# Held device-control override, with guaranteed release
# ---------------------------------------------------------------------------

class Override:
    """Holds one or more GMLAN device controls alive on a background thread by
    re-sending $AE and tester-present every `period` seconds. Releasing (also on
    stop(), process exit, or any error) sends ReturnToNormalMode $20. If this
    thread dies the module reverts on its own once tester-present stops."""

    def __init__(self, session, req_id, resp_id, period=1.5, on_event=None):
        self.s = session
        self.req_id, self.resp_id = req_id, resp_id
        self.period = period
        self.controls = {}          # cpid -> state bytes
        self.on_event = on_event or (lambda m: None)
        self._stop = threading.Event()
        self._thread = None
        self.last_error = None

    def set(self, cpid, state):
        self.controls[cpid] = bytes(state)
        self._send_control(cpid, bytes(state))
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def clear(self, cpid):
        self.controls.pop(cpid, None)

    def _send_control(self, cpid, state):
        resps = self.s.request(bytes([0xAE, cpid]) + state, self.req_id, self.resp_id,
                               label=f"hold cpid {cpid:02X}")
        bad = [r for r in resps if r.negative]
        if bad:
            self.on_event(f"module refused cpid {cpid:02X}: {bad[0]!r}")
        return resps

    def _loop(self):
        while not self._stop.wait(self.period):
            try:
                self.s.request(b"\x3e\x00", self.req_id, self.resp_id, read_secs=0.4,
                               label="tester-present")
                for cpid, state in list(self.controls.items()):
                    self._send_control(cpid, state)
            except OSError as e:
                self.last_error = e
                self.on_event(f"link error while holding: {e} - module will revert on its own")
                return

    def release(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        self.controls.clear()
        try:
            self.s.request(b"\x20", self.req_id, self.resp_id, label="ReturnToNormalMode")
            self.on_event("released (ReturnToNormalMode sent)")
        except OSError as e:
            self.on_event(f"couldn't send release ({e}); module reverts on tester-present timeout")


# ---------------------------------------------------------------------------
# Read-only operations
# ---------------------------------------------------------------------------

def read_vin_legislated(session):
    """Mode 09 PID 02, the standard emissions VIN read, to the functional
    address. Harmless on any OBD2 vehicle and a good transmit smoke test."""
    resps = session.request(b"\x09\x02", cb.LEGISLATED_FUNC, None, read_secs=1.5, label="Mode 09 VIN")
    for r in resps:
        if not r.negative and len(r.payload) >= 3:
            vin = r.payload[2:].replace(b"\x00", b"")
            if vin.isascii():
                return vin.decode(errors="replace"), r.can_id
    return None, None


def discover(session, report):
    """Find modules that answer diagnostics. First a functional tester-present
    (most modules answer at once), then a physical sweep of GM Global A request
    IDs 0x241-0x24F as a cross-check. Read-only."""
    found = {}
    report("functional tester-present (0x101) ...")
    for r in session.request(b"\x3e\x00", cb.FUNCTIONAL_REQ, None, read_secs=2.0, label="discover func"):
        found[r.can_id] = "answered functional tester-present"
        report(f"  {cb.fmt_id(r.can_id, session.ext)}  {r!r}")
    report("physical sweep 0x241-0x24F ...")
    for req in range(0x241, 0x250):
        resp = req + 0x400          # 0x241 -> 0x641
        for r in session.request(b"\x3e\x00", req, resp, read_secs=0.4, label=f"probe {req:03X}"):
            if r.can_id not in found:
                found[r.can_id] = f"answered physical {req:03X}"
                report(f"  req {req:03X} -> {cb.fmt_id(r.can_id, session.ext)}  {r!r}")
    if not found:
        report("no modules answered. On the high-speed bus? right protocol? ignition on?")
    return found


# ---------------------------------------------------------------------------
# Interactive control console
# ---------------------------------------------------------------------------

CONTROL_HELP = """commands:
  arm                     enable transmitting (asks you to confirm you're parked)
  send <hex>              send one raw service, show the response  e.g. send 1A90
  read <did-hex>          read a data identifier from the target   e.g. read 30
  hold <cpid> <state>     begin holding a device control           e.g. hold 0A 00
  drop <cpid>             stop holding one control (keeps others)
  release                 release ALL controls (ReturnToNormalMode)
  target <reqhex>         change target module (default 241, resp = req+400)
  status                  show target, armed state, active holds
  help                    this list
  quit                    release everything and exit
"""


def control_console(session, report, prompt):
    req_id, resp_id = cb.BCM_REQ, cb.BCM_RESP
    armed = False
    ov = Override(session, req_id, resp_id, on_event=report)

    def need_arm():
        if not armed:
            report("not armed - type `arm` first (reading is fine unarmed)")
        return armed

    try:
        report("control console. `help` for commands. Nothing is sent until you `arm`.")
        while True:
            try:
                line = prompt(f"[{cb.fmt_id(req_id, session.ext)}{' ARMED' if armed else ''}] ").strip()
            except EOFError:
                break
            if not line:
                continue
            parts = line.split()
            cmd, args = parts[0].lower(), parts[1:]

            if cmd in ("quit", "exit", "q"):
                break
            elif cmd == "help":
                report(CONTROL_HELP)
            elif cmd == "status":
                report(f"target req={cb.fmt_id(req_id, session.ext)} resp={cb.fmt_id(resp_id, session.ext)}  "
                       f"armed={armed}  holding={[f'{c:02X}={s.hex().upper()}' for c, s in ov.controls.items()]}")
            elif cmd == "target":
                if args:
                    req_id = int(args[0], 16)
                    resp_id = req_id + 0x400
                    ov.req_id, ov.resp_id = req_id, resp_id
                    report(f"target -> req {cb.fmt_id(req_id, session.ext)} resp {cb.fmt_id(resp_id, session.ext)}")
            elif cmd == "arm":
                ans = prompt("Confirm the vehicle is PARKED and you accept control of its "
                             "modules [type 'yes']: ").strip().lower()
                armed = ans == "yes"
                report("ARMED - transmit enabled" if armed else "not armed")
            elif cmd == "read":
                did = int(args[0], 16)
                for r in session.request(bytes([0x1A, did]), req_id, resp_id, label=f"read {did:02X}"):
                    report(f"  {r!r}")
            elif cmd == "send":
                if not need_arm():
                    continue
                payload = bytes.fromhex(args[0])
                for r in session.request(payload, req_id, resp_id, label="manual send"):
                    report(f"  {r!r}")
            elif cmd == "hold":
                if not need_arm():
                    continue
                cpid, state = int(args[0], 16), bytes.fromhex(args[1]) if len(args) > 1 else b"\x00"
                ov.set(cpid, state)
                report(f"holding cpid {cpid:02X} = {state.hex().upper()} (tester-present running)")
            elif cmd == "drop":
                ov.clear(int(args[0], 16))
                report(f"dropped cpid {args[0].upper()} (others still held)")
            elif cmd == "release":
                ov.release()
                ov = Override(session, req_id, resp_id, on_event=report)
            else:
                report(f"unknown command: {cmd} (try `help`)")
    finally:
        ov.release()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="STN/OBDLink diagnostic read/write console")
    ap.add_argument("mode", choices=["info", "discover", "read", "control"], help="what to do")
    ap.add_argument("--port", help="serial port (default: auto-detect)")
    ap.add_argument("--port-match", default=cb.PORT_MATCH, help="regex to auto-detect the port")
    ap.add_argument("--wait", type=float, default=30, help="seconds to wait for the adapter (0 = forever)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--elm", type=int, default=6, help="ELM protocol number (6 = ISO 15765 11-bit 500k)")
    ap.add_argument("--stp", type=int, help="force an STN protocol number instead of --elm")
    ap.add_argument("--ext", action="store_true", help="29-bit diagnostic IDs")
    ap.add_argument("--module", default="241", help="target request ID in hex (read mode)")
    ap.add_argument("--did", help="data identifier in hex (read mode)")
    ap.add_argument("--outdir", default="logs", help="directory for the transcript log")
    args = ap.parse_args()

    if os.name == "nt":
        os.system("")

    os.makedirs(args.outdir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(args.outdir, f"{stamp}_diag.txt")

    print("connecting (active diagnostic mode - the adapter will ACK the bus) ...")
    adapter, info = cb.connect(args.port, args.port_match, args.baud, args.wait, silent=False)
    print(f"  port:     {adapter.port}")
    print(f"  adapter:  {info['device'] or info['firmware'] or '(unknown)'}")
    print(f"  voltage:  {info['voltage'] or '?'}")

    session = DiagSession(adapter, elm=args.elm, stp=args.stp, ext=args.ext, log_path=log_path)
    print(f"  protocol: {session.protocol}")
    print(f"  log:      {log_path}")

    # Release on SIGINT/SIGTERM even outside the control loop.
    def on_signal(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, on_signal)

    try:
        if args.mode == "info":
            vin, who = read_vin_legislated(session)
            print(f"  VIN:      {vin or '(no response - ignition on? OBD bus?)'}"
                  + (f"  (from {cb.fmt_id(who, args.ext)})" if who else ""))
        elif args.mode == "discover":
            discover(session, print)
        elif args.mode == "read":
            if not args.did:
                ap.error("read mode needs --did (hex)")
            req = int(args.module, 16)
            for r in session.request(bytes([0x1A, int(args.did, 16)]), req, req + 0x400, label="read"):
                print(f"  {r!r}")
        elif args.mode == "control":
            control_console(session, print, input)
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        session.close()
        try:
            adapter.cmd("ATCSM1")   # back to silent before leaving
        except OSError:
            pass
        adapter.close()
        print(f"done. transcript: {log_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\naborted")
