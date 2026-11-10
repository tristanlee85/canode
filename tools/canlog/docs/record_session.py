#!/usr/bin/env python3
"""Record docs/canlog-session.{gif,mp4}: a real canlog.py run, not a mock-up.

Replays the 2026-11-05 Silverado SW-CAN capture through canlog.py --replay at 1x
speed inside a pseudo-terminal, and presses the same keys at the same capture
times the original session's .marks file recorded (baseline, then the Headlight
switch, High beams and custom "Fog lights" guided tests). The terminal output is
saved as an asciinema v2 .cast with real timing; render it with agg + ffmpeg.

    python3 docs/record_session.py /tmp/canlog-session.cast      # ~7 min, real time
    agg -q --speed 7 --fps-cap 8 --font-size 14 --theme github-dark \\
        --last-frame-duration 4 /tmp/canlog-session.cast docs/canlog-session.gif
    ffmpeg -y -i docs/canlog-session.gif -movflags +faststart -pix_fmt yuv420p \\
        -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" -c:v libx264 -crf 23 -preset slow \\
        docs/canlog-session.mp4

Needs the gitignored .log frame dump (logs/20261105_233405_sw.log) on disk.
Key timing is matched to within ~0.1-0.3 s of the original, so the strict
findings reproduce exactly; the first round of a test can show a "disagrees"
NOTE that the original run didn't have.
"""
import codecs, fcntl, json, os, pty, re, select, struct, sys, termios, time
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parents[1]
LOG = "logs/20261105_233405_sw.log"
MARKS = TOOL_DIR / "logs/20261105_233405_sw.marks"
OUT = sys.argv[1] if len(sys.argv) > 1 else "canlog-session.cast"
PY = sys.executable
COLS, ROWS = 120, 42
LEARN = 10.0                     # canlog --learn default (baseline countdown)
CUSTOM_TEST = "Fog lights: low beam + fog on, high beam + fog off"

with open(TOOL_DIR / LOG) as f:
    t0 = float(re.match(r"\((\d+\.\d+)\)", f.readline()).group(1))

# Key schedule as (capture time, key), rebuilt from the .marks file.
sched = []
for line in open(MARKS):
    line = line.strip()
    m = re.match(r"(.+?) @ (\d+\.\d+)$", line)
    if m:
        what, ts = m.group(1), float(m.group(2))
        if what == "BASELINE":
            sched.append((ts - LEARN, "b"))
        elif what.startswith("TEST ") and what.endswith(" START"):
            name = what[5:-6]
            if name == "Headlight switch":
                sched += [(ts - 1.2, "t"), (ts, "1")]
            elif name == "High beams":
                sched += [(ts - 1.2, "t"), (ts, "2")]
            else:  # added from the test menu with [+]
                sched += [(ts - 7.0, "t"), (ts - 6.2, "+")]
                sched += [(ts - 5.6 + i * 0.09, ch) for i, ch in enumerate(CUSTOM_TEST)]
                sched.append((ts, "\r"))
    m = re.match(r"window (\d+\.\d+) (\d+\.\d+)$", line)
    if m:
        sched.append((float(m.group(1)), " "))   # SPACE starts each step's capture
last = max(t for t, _ in sched)
sched += [(last + 8.0, "q"), (last + 9.5, "q")]
sched.sort(key=lambda x: x[0])

events, start = [], time.time()


def emit(text):
    events.append([round(time.time() - start, 4), "o", text])


emit("\x1b[32m$\x1b[0m ")
time.sleep(0.6)
for ch in f"python3 canlog.py --replay {LOG}":
    emit(ch)
    time.sleep(0.035)
time.sleep(0.4)
emit("\r\n")

pid, fd = pty.fork()
if pid == 0:
    os.chdir(TOOL_DIR)
    os.environ["TERM"] = "xterm-256color"
    os.execvp(PY, [PY, "canlog.py", "--replay", LOG, "--speed", "1", "--refresh", "0.2"])
    os._exit(1)
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))

dec = codecs.getincrementaldecoder("utf-8")("replace")
replay_t0, i = None, 0          # wall time matching capture time t0; next key
while True:
    now = time.time()
    timeout = 0.05
    if replay_t0 is not None and i < len(sched):
        due = replay_t0 + (sched[i][0] - t0)
        if now >= due:
            os.write(fd, sched[i][1].encode())
            i += 1
            continue
        timeout = min(timeout, due - now)
    r, _, _ = select.select([fd], [], [], timeout)
    if fd in r:
        try:
            data = os.read(fd, 65536)
        except OSError:
            break
        if not data:
            break
        text = dec.decode(data)
        emit(text)
        if replay_t0 is None and re.search(r"frames [1-9]", text):
            replay_t0 = time.time() - 0.1   # first frame lands ~half a refresh earlier
try:
    os.waitpid(pid, 0)
except ChildProcessError:
    pass

with open(OUT, "w") as f:
    f.write(json.dumps({"version": 2, "width": COLS, "height": ROWS,
                        "env": {"TERM": "xterm-256color"}}) + "\n")
    f.writelines(json.dumps(e) + "\n" for e in events)
print(f"{OUT}: {len(events)} events, {events[-1][0]:.1f}s, {i}/{len(sched)} keys sent")
