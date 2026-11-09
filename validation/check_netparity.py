#!/usr/bin/env python3
"""Pad-by-pad net parity: every footprint pad on the board must sit on the same net as
the matching symbol pin in the schematic netlist.

KiCad's `pcb drc --schematic-parity` checks footprints and fields, but not which net each
pad is on. A pad left on an old `unconnected-(...)` net, or wired to the wrong net, passes it.
This catches that. Stdlib only (reads the .kicad_pcb as text, exports the netlist via kicad-cli).

Usage:  python3 validation/check_netparity.py [--kicad-cli PATH]
Exit 0 = every pad matches, 1 = mismatches.
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCH = ROOT / "hardware/kicad/canode.kicad_sch"
PCB = ROOT / "hardware/kicad/canode.kicad_pcb"


def blocks(text, head):
    """Yield the text of each top-level-ish s-expression starting with `head`."""
    i = 0
    while True:
        i = text.find(head, i)
        if i < 0:
            return
        depth = 0
        for j in range(i, len(text)):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    yield text[i:j + 1]
                    i = j + 1
                    break


def norm(net):
    # schematic-only nets for unconnected pins look like unconnected-(U1-PA4-Pad15)
    return "<nc>" if net.startswith("unconnected-(") or net == "" else net


def netlist_pins(kicad_cli):
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "canode.net"
        subprocess.run([kicad_cli, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", str(out), str(SCH)],
                       check=True, capture_output=True)
        text = out.read_text()
    pins = {}
    nets = text[text.index("(nets"):]
    for blk in blocks(nets, "(net\n") if "(net\n" in nets else blocks(nets, "(net "):
        name = re.search(r'\(name "([^"]*)"\)', blk).group(1)
        for ref, pin in re.findall(r'\(ref "([^"]+)"\)\s*\(pin "([^"]+)"\)', blk):
            pins[(ref, pin)] = norm(name)
    return pins


def board_pads():
    text = PCB.read_text()
    pads = {}
    for fp in blocks(text, "(footprint "):
        m = re.search(r'\(property "Reference" "([^"]+)"', fp)
        if not m:
            continue
        ref = m.group(1)
        for pad in blocks(fp, "(pad "):
            num = re.match(r'\(pad "([^"]*)"', pad).group(1)
            if not num:
                continue          # mechanical holes / pegs
            n = re.search(r'\(net (?:\d+ )?"([^"]*)"\)', pad)
            net = norm(n.group(1) if n else "")
            # several pads can share a number (e.g. exposed pad + thermal vias): all must agree
            pads.setdefault((ref, num), set()).add(net)
    return pads


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kicad-cli", default="kicad-cli")
    a = ap.parse_args()
    sch = netlist_pins(a.kicad_cli)
    pcb = board_pads()
    bad = []
    for key, nets in sorted(pcb.items()):
        want = sch.get(key, "<nc>")
        for got in nets:
            if got != want:
                bad.append(f"  {key[0]} pad {key[1]}: board {got!r}, schematic {want!r}")
    for key, want in sorted(sch.items()):
        if key not in pcb and not key[0].startswith("#"):
            bad.append(f"  {key[0]} pin {key[1]} ({want}): no such pad on the board")
    if bad:
        print(f"net parity: {len(bad)} mismatch(es)")
        print("\n".join(bad))
        sys.exit(1)
    print(f"net parity: {len(pcb)} pads match the schematic netlist")


if __name__ == "__main__":
    main()
