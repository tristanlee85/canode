# Capture findings

Decoded results from the sessions whose `.json`/`.marks` are committed here. The
matching `.log` frame dumps are gitignored; regenerate or re-run `canlog.py
--replay` against a local copy if you need the frames.

## 2019 Silverado 3500 — single-wire CAN (SW-CAN, 33.3k, 29-bit)

Session `20261105_233405_sw` (69,800 frames). Exterior lighting decodes to a
single arbitration ID, **`0x1020C040`**:

| Feature | Signal |
|---------|--------|
| Headlight switch | byte 3 bit 7:  AUTO=0, OFF=0, PARK=1, ON=1 |
| High beams | byte 1 bit 5 / byte 2 bit 4:  low=0, high=1; byte 4 bits 0–1: low=01, high=02 |
| Fog lights | byte 0 bit 7 = fog on; byte 2 bit 4 flips with high/low; byte 4 bits 0–1 as above |

Session `20261105_231840_sw` (134,791 frames) is background chatter with no
guided-test findings recorded.

Both captures were taken with the adapter in silent monitor mode (listen-only).
