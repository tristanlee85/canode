#!/usr/bin/env python3
"""Validate the MCU pinout against ST's official pin data (STM32_open_pin_data).

Checks, for the STM32 (default ref U1):
  1. Every symbol pin number/name in the KiCad netlist matches ST's package pinout
     (catches a wrong or edited symbol).
  2. Every net in REQUIREMENTS lands on a pin that actually supports the required
     signal, and reports the GPIO alternate-function (AF) number to use in firmware.
  3. Power pins sit on the right rails.
  4. Flags pins whose net is not covered by REQUIREMENTS (so new nets get reviewed).

Usage:
  python3 validation/check_pins.py                     # exports netlist via kicad-cli
  python3 validation/check_pins.py --netlist foo.net   # use an existing netlist
Exit code 0 = all checks pass, 1 = failures.
"""
import argparse, subprocess, sys, tempfile, xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hardware" / "generator"))
from sexp import parse, find, find1  # noqa: E402

ST_REPO = "https://github.com/STMicroelectronics/STM32_open_pin_data.git"
CACHE = ROOT / "validation" / ".cache" / "STM32_open_pin_data"
MCU_XML = "STM32G0B1C(B-C-E)Ux.xml"   # UFQFPN48 (U1 = STM32G0B1CEU6); same GP pin numbering as LQFP48
EXPOSED_PAD = "49"                    # UFQFPN48 exposed pad: ST recommends soldering it to ground
GPIO_XML = "GPIO-STM32G0Bx_gpio_v1_0_Modes.xml"

# net name -> signal(s) the pin must support ("GPIO" = plain I/O is enough).
# A list means "any of these"; the first match is reported.
REQUIREMENTS = {
    "CAN1_RX": "FDCAN1_RX", "CAN1_TX": "FDCAN1_TX",
    "CAN2_RX": "FDCAN2_RX", "CAN2_TX": "FDCAN2_TX",
    "CAN1_STBY": "GPIO", "CAN2_STBY": "GPIO",
    "USB_DM": "USB_DM", "USB_DP": "USB_DP",
    "HSE_IN": "RCC_OSC_IN", "HSE_OUT": "RCC_OSC_OUT",
    "SWDIO": "SYS_SWDIO", "SWCLK": "SYS_SWCLK",
    "UART_TX": "USART2_TX", "UART_RX": "USART2_RX",
    "VBAT_SENSE": "ADC1_IN0", "AUX_SENSE": "ADC1_IN1",
    "AUX_DRV": ["TIM1_CH1", "GPIO"],
    "LED1_DRV": "GPIO", "LED2_DRV": "GPIO",
    "GPIO_PB6": ["I2C1_SCL", "USART1_TX", "GPIO"], "GPIO_PB7": ["I2C1_SDA", "USART1_RX", "GPIO"],
    "GPIO_PB8": "GPIO", "GPIO_PB9": "GPIO",
}
POWER = {"VDD": "+3V3", "VBAT": "+3V3", "VREF+": "+3V3", "VSS": "GND"}
SPECIAL = {"NRST": "NRST"}  # net -> substring that must appear in ST's pin name


def ensure_st_data():
    if not (CACHE / "mcu" / MCU_XML).exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        print(f"fetching ST pin data -> {CACHE}")
        subprocess.run(["git", "clone", "--depth", "1", "-q", ST_REPO, str(CACHE)], check=True)
    return CACHE / "mcu" / MCU_XML, CACHE / "mcu" / "IP" / GPIO_XML


def load_st(mcu_xml, gpio_xml):
    ns = {"m": "http://dummy.com"}
    def strip(t): return t.split("}", 1)[-1]
    pins = {}  # position -> list of (name, type, set(signals))
    for p in ET.parse(mcu_xml).getroot():
        if strip(p.tag) != "Pin": continue
        sigs = {s.get("Name") for s in p if strip(s.tag) == "Signal"}
        pins.setdefault(p.get("Position"), []).append((p.get("Name"), p.get("Type"), sigs))
    af = {}  # (pin base name, signal) -> AF string
    for gp in ET.parse(gpio_xml).getroot():
        if strip(gp.tag) != "GPIO_Pin": continue
        base = gp.get("Name").split("-")[0].split(" ")[0]
        for ps in gp:
            if strip(ps.tag) != "PinSignal": continue
            for v in ps.iter():
                if strip(v.tag) == "PossibleValue" and v.text and v.text.startswith("GPIO_AF"):
                    af[(base, ps.get("Name"))] = v.text
    return pins, af


def base_name(st_name):
    return st_name.split("-")[0].split(" ")[0]


def load_netlist(path, ref):
    net = parse(open(path).read())[0]
    out = {}
    for n in find(find1(net, "nets"), "net"):
        name = find1(n, "name")[1].lstrip("/")
        for node in find(n, "node"):
            if find1(node, "ref")[1] != ref: continue
            pf = find1(node, "pinfunction")
            pin = find1(node, "pin")[1]
            # KiCad 10 netlists append "_<pin number>" to pinfunction (e.g. "PA0_11"); strip it
            out[pin] = (name, pf[1].removesuffix(f"_{pin}") if pf else "")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--netlist")
    ap.add_argument("--sch", default=str(ROOT / "hardware" / "kicad" / "canode.kicad_sch"))
    ap.add_argument("--ref", default="U1")
    a = ap.parse_args()
    if not a.netlist:
        a.netlist = str(Path(tempfile.gettempdir()) / "canode_check.net")
        subprocess.run(["kicad-cli", "sch", "export", "netlist", "-o", a.netlist, a.sch], check=True,
                       capture_output=True)
    pins, af = load_st(*ensure_st_data())
    nl = load_netlist(a.netlist, a.ref)
    fails, warns, rows = [], [], []

    for num, (net, kname) in sorted(nl.items(), key=lambda kv: int(kv[0])):
        if num == EXPOSED_PAD:
            ok = net.lstrip("/") == "GND"
            (rows if ok else fails).append(f"pin {num} exposed pad: on {net}" + ("" if ok else " (expected GND)"))
            continue
        cands = pins.get(num)
        if not cands:
            fails.append(f"pin {num}: not a pin position on {MCU_XML}"); continue
        # pick the ST entry whose base name matches the KiCad pin name (handles PA11/PA9 remap pairs)
        kbase = kname.split("/")[0].split("-")[0]
        st = next((c for c in cands if base_name(c[0]) == kbase), None)
        if st is None:
            fails.append(f"pin {num}: KiCad symbol says '{kname}', ST says {[c[0] for c in cands]}")
            st = cands[0]
        st_name, st_type, sigs = st
        b = base_name(st_name)
        if net.startswith("unconnected-"):
            continue
        if b in POWER:
            ok = net == POWER[b]
            (rows if ok else fails).append(f"pin {num} {b}: on {net}" + ("" if ok else f" (expected {POWER[b]})"))
            continue
        if net in SPECIAL:
            ok = SPECIAL[net] in st_name
            (rows if ok else fails).append(f"pin {num} {st_name}: {net}")
            continue
        req = REQUIREMENTS.get(net)
        if req is None:
            warns.append(f"pin {num} {b}: net '{net}' has no requirement entry - review it"); continue
        req = req if isinstance(req, list) else [req]
        hit = next((r for r in req if r in sigs), None)
        if hit is None:
            fails.append(f"pin {num} {b}: net {net} needs {' or '.join(req)}; pin offers "
                         f"{sorted(s for s in sigs if s != 'GPIO')}")
            continue
        if hit.startswith("SYS_SW"):
            afn = "(SWD is the default after reset)"
        else:
            afn = af.get((b, hit), "" if hit == "GPIO" else "(analog/system, no AF)")
        rows.append(f"pin {num:>2} {b:<5} {net:<11} -> {hit:<10} {afn}")

    missing = set(REQUIREMENTS) - {n for n, _ in nl.values()}
    for m in sorted(missing):
        fails.append(f"required net {m} is not connected to {a.ref}")

    print(f"Checked {a.ref} against ST {MCU_XML}\n")
    for r in rows: print("  OK  ", r)
    for w in warns: print("  WARN", w)
    for f in fails: print("  FAIL", f)
    print(f"\n{len(rows)} ok, {len(warns)} warnings, {len(fails)} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
