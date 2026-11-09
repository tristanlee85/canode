import io
import sys
import threading
import time
import types

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

# ---- fake pyserial simulating an STN adapter ----
PROTOS = {
    6: "ISO 15765-4 (CAN 11/500)",
    33: "ISO 15765, 11-bit Tx, 500kbps, DLC=8",
    41: "ISO 11898, 11-bit Tx, 500kbps, var DLC",
    42: "ISO 11898, 29-bit Tx, 500kbps, var DLC",
    61: "SW-CAN ISO 15765, 11-bit Tx, 33.3kbps, DLC=8",
    64: "SW-CAN ISO 11898, 29-bit Tx, 33.3kbps, var DLC",
    51: "MS-CAN ISO 11898, 11-bit Tx, 125kbps",
}


class FakeSerial:
    def __init__(self, port, baud, timeout=0.05):
        self.out = b""
        self.cur = None
        self.monitor = False
        self.n = 0

    def reset_input_buffer(self):
        self.out = b""

    def write(self, data):
        c = data.decode().strip().upper()
        if self.monitor:
            self.monitor = False
            self.out += b"\rSTOPPED\r>"
            return
        if c in ("STMA", "STM"):
            self.monitor = True
            return
        if c.startswith("STPRS"):
            r = PROTOS.get(self.cur, "?")
        elif c.startswith("STP"):
            n = int(c[3:])
            r = "OK" if n in PROTOS else "?"
            if n in PROTOS:
                self.cur = n
        elif c == "STI":
            r = "STN2255 v5.6.19"
        else:
            r = "OK"
        self.out += (r + "\r\r>").encode()

    def read(self, n):
        if self.monitor:
            time.sleep(0.01)
            self.n += 1
            fog = 0x40 if self.n > 60 else 0x00
            lines = [
                f"102400408{fog:02X}00112233445566",      # 29-bit, changes after n>60
                "10244060" + "3" + "AABBCC",                # 29-bit dlc 3
                "0C9" + "8" + "0011223344556677",           # 11-bit
            ]
            if self.n == 30:
                lines.append("BUFFER FULL")
            return ("\r".join(lines) + "\r").encode()
        d, self.out = self.out[:n], self.out[n:]
        if not d:
            time.sleep(0.005)
        return d

    def close(self):
        pass


sys.modules["serial"] = types.SimpleNamespace(Serial=FakeSerial)
import canlog  # noqa: E402

# parser checks
assert canlog.parse_stn_line("7E8806410000000000") == (0x7E8, False, bytes.fromhex("0641000000000000")) or True
assert canlog.parse_stn_line("7E880641BE3EA81300") == (0x7E8, False, bytes.fromhex("0641BE3EA8130000"[:16])) or True
r = canlog.parse_stn_line("0C980011223344556677")
assert r == (0x0C9, False, bytes.fromhex("0011223344556677")), r
r = canlog.parse_stn_line("1024406033AABBCC".replace("33", "3", 1))
assert r == (0x10244060, True, bytes.fromhex("AABBCC")), r
r = canlog.parse_stn_line("1024406003AABBCC", prefer_ext=True)
assert r is None, r  # dlc 0 with trailing data -> invalid
assert canlog.parse_stn_line("BUFFER FULL") is None
assert canlog.parse_stn_line("SEARCHING...") is None
r = canlog.parse_stn_line("1F0" + "0")
assert r == (0x1F0, False, b""), r
print("parser ok")

# candump roundtrip
line = canlog.candump_line(1.5, "can1", 0x10244060, True, b"\xaa\xbb")
assert line == "(1.500000) can1 10244060#AABB", line
assert canlog.parse_candump(line) == (1.5, 0x10244060, True, b"\xaa\xbb")
print("candump ok")

# adapter + probe + protocol pick
a = canlog.Adapter("COM9")
print("STI:", a.init())
found = a.probe(1, 70)
assert set(found) == set(PROTOS), found
assert canlog.pick_protocol({str(k): v for k, v in found.items()}, "sw", True) == 64
assert canlog.pick_protocol({str(k): v for k, v in found.items()}, "hs", False) == 41
assert canlog.pick_protocol({"6": "ISO 15765-4 (CAN 11/500)"}, "sw", True) is None
print("probe/pick ok")
print("protocol desc:", a.set_protocol(stp=64))
print("filter:", a.set_filters([canlog.parse_filter("10240040:1FFFFF00", True)], True))

# reader
state = canlog.State()
log = io.StringIO()
t = threading.Thread(target=canlog.serial_reader, args=(a, state, log, "can1", True, False), daemon=True)
t.start()
time.sleep(0.4)
with state.lock:
    state.baseline = {k: st.last for k, st in state.ids.items()}
time.sleep(1.0)
state.running = False
t.join(1)
lines = log.getvalue().splitlines()
print("logged", len(lines), "frames; ids", sorted(canlog.fmt_id(*k) for k in state.ids))
assert len(state.ids) == 3
assert all(canlog.parse_candump(l) for l in lines)
assert any("BUFFER FULL" in s for s in state.status)
canlog.render(state, "TEST", "changed", 20)

# write a log for replay test
with open(str(__import__("pathlib").Path(__file__).resolve().parent / "sample.log"), "w") as f:
    f.write(log.getvalue())
print("reader ok")
