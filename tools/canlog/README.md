# canlog — STN/OBDLink CAN workbench

Terminal tools for sniffing and reverse-engineering a vehicle's CAN buses with an
STN-chip OBD adapter (OBDLink MX+/SX/EX). These predate the canode board and were
the start of the CAN debugging process; they live here, isolated from the
hardware, because they're how you find the messages the board will later gateway.

```bash
pip install pyserial
```

| File | What it does | Bus access |
|------|--------------|------------|
| `canlog.py`  | Logger + byte-diff + guided feature tests. Logs candump format, highlights changed bytes against a baseline, and walks you through flipping a switch to find the bits that track it. | **listen-only** (silent monitor, `ATCSM1`) |
| `cantool.py` | Active diagnostic read/write console: VIN, module discovery, data-identifier reads, and held GMLAN `$AE` device-control overrides. | **transmits** (see Safety) |
| `canbus.py`  | Shared core used by `cantool.py`: frame parsing, adapter wrapper, ISO-TP, GMLAN/UDS helpers. Not run directly. | — |
| `stn_protocols.json` | Protocol-number cache written by `canlog.py --probe`. | — |

## canlog (listen-only)

```bash
python3 canlog.py --probe                       # one time: list adapter protocols
python3 canlog.py --bus hs                       # GM high-speed CAN (pins 6/14)
python3 canlog.py --bus sw                       # GM single-wire CAN (pin 1)
python3 canlog.py --bus sw --filter 10240040:1FFFFF00
python3 canlog.py --replay logs/<file>.log --speed 4   # analyse a capture offline
```
Keys while running: `b` learn baseline, `t` guided tests, `m` marker, `f`
changed-only/all, `s` sort, `p` pause, `c` clear baseline, `q` quit. It survives
Bluetooth dropouts and writes `.log` (frames), `.marks` (markers/baselines/gaps)
and `.json` (session summary with decoded findings). Run `--help` for the rest.

## cantool (active — transmits on the bus)

```bash
python3 cantool.py info                 # adapter + VIN, read-only
python3 cantool.py discover             # list modules that answer diagnostics
python3 cantool.py read --did 90        # read a data identifier from a module
python3 cantool.py control              # interactive device-control console
```

### Safety

`cantool.py` is the one tool here that **puts frames on the vehicle bus**. It is
the only transmitter in this repo, and it exists for bench / garage work:

- Reading (`info`, `discover`, `read`) never changes vehicle state.
- The `control` console sends nothing until you type `arm` and confirm the
  vehicle is in Park. Every override is released (`ReturnToNormalMode`) on quit,
  on Ctrl-C, and if the process dies; the module also reverts on its own within
  seconds once tester-present stops.
- Test parked, engine off or idling, away from powertrain / brake / airbag
  modules. Defaults target the GM Global A BCM (`0x241/0x641`) — confirm with
  `discover` on your truck first.

This is deliberately separate from the canode firmware's vehicle rules, which
default to listen-only (see the repo `CLAUDE.md`, Safety rules). `cantool.py`
never runs as part of the board; it's a hand-operated scan-tool substitute.

## Tests

```bash
python3 tests/test_canlog.py            # offline, no adapter needed
```
Covered from the repo root by `make test-tools`. The tests fake an STN adapter
over a stub serial port and check frame parsing, protocol probe/pick, the monitor
reader, and the guided-test signal finder.

## logs/

Real captures live here. Raw `.log`/`.raw` frame dumps are gitignored (they're
large); the small `.json`/`.marks` summaries are committed because they carry the
decoded findings. See `logs/FINDINGS.md`.
