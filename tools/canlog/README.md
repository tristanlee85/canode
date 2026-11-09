# canlog

A terminal CAN logger and byte-diff console for STN-chip OBD adapters (OBDLink MX+/SX/EX). It logs in candump format and highlights bytes that change against a baseline, so you can find which bytes move when you press a button.

```bash
pip install pyserial
python3 canlog.py --port /dev/cu.OBDLinkMXPlus-Port --bus hs      # live
python3 canlog.py --replay logs/<file>.log --speed 4               # replay a capture
python3 tests/test_canlog.py                                       # offline tests, no adapter needed
```
Keys while running: `b` set baseline, `c` clear, `m` add a marker, `p` pause, `s` sort, `q` quit. Run `--help` for filters, protocol probing and other options.
