#!/usr/bin/env python3
"""Generate JLCPCB fab + assembly outputs from the KiCad project (not from generator/).

Outputs (default build/fab/):
  gerbers/ + canode_gerbers_JLC.zip   Gerbers + Excellon drills
  canode_BOM_JLC.csv                   Comment, Designator, Footprint, LCSC Part #, Qty, MPN
  canode_CPL_JLC.csv                   Designator, Mid X, Mid Y, Layer, Rotation
  canode_HAND_SOLDER.csv               parts with no LCSC number (connectors, headers)

A part is sent to JLC assembly when its symbol has a non-empty "LCSC" field and is not
DNP / excluded from BOM. Tested with kicad-cli 10.
Usage: python3 hardware/scripts/jlc_fab.py [--kicad-cli PATH] [--out DIR]
"""
import argparse, csv, re, shutil, subprocess, sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hardware" / "generator"))
from sexp import parse, find, find1  # noqa: E402

SCH = ROOT / "hardware" / "kicad" / "canode.kicad_sch"
PCB = ROOT / "hardware" / "kicad" / "canode.kicad_pcb"
LAYERS = "F.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts"


def natkey(r):
    m = re.match(r"([A-Za-z]+)(\d+)", r)
    return (m.group(1), int(m.group(2))) if m else (r, 0)


def run(cli, *args):
    r = subprocess.run([cli, *args], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"kicad-cli failed: {' '.join(args)}\n{r.stdout}\n{r.stderr}")


def components(netlist):
    n = parse(open(netlist).read())[0]
    out = {}
    for c in find(find1(n, "components"), "comp"):
        props = {}
        for p in find(c, "property"):
            name = find1(p, "name")[1]
            val = find1(p, "value")
            props[name] = val[1] if val else True
        out[find1(c, "ref")[1]] = dict(value=find1(c, "value")[1], footprint=find1(c, "footprint")[1],
                                       lcsc=props.get("LCSC", "") or "", mpn=props.get("MPN", "") or "",
                                       excluded=bool(props.get("exclude_from_bom") or props.get("dnp")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kicad-cli", default=shutil.which("kicad-cli") or "kicad-cli")
    ap.add_argument("--out", default=str(ROOT / "build" / "fab"))
    a = ap.parse_args()
    out = Path(a.out); gdir = out / "gerbers"
    shutil.rmtree(out, ignore_errors=True); gdir.mkdir(parents=True)

    run(a.kicad_cli, "pcb", "export", "gerbers", "-o", str(gdir) + "/", "--layers", LAYERS,
        "--subtract-soldermask", str(PCB))
    run(a.kicad_cli, "pcb", "export", "drill", "-o", str(gdir) + "/", "--format", "excellon",
        "--excellon-units", "mm", "--excellon-separate-th", str(PCB))
    with zipfile.ZipFile(out / "canode_gerbers_JLC.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(gdir.iterdir()):
            if f.suffix in (".gbrjob",) or "map" in f.name: continue
            z.write(f, f.name)

    net = out / "canode.net"; pos = out / "pos.csv"
    run(a.kicad_cli, "sch", "export", "netlist", "-o", str(net), str(SCH))
    run(a.kicad_cli, "pcb", "export", "pos", "-o", str(pos), "--side", "front", "--format", "csv",
        "--units", "mm", str(PCB))
    comps = components(net)
    posrows = {r["Ref"]: r for r in csv.DictReader(open(pos))}

    asm = {r: c for r, c in comps.items() if c["lcsc"] and not c["excluded"]}
    groups = {}
    for r, c in asm.items():
        groups.setdefault((c["lcsc"], c["footprint"].split(":")[-1]), []).append(r)
    with open(out / "canode_BOM_JLC.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #", "Qty", "MPN"])
        for (lcsc, fp), refs in sorted(groups.items(), key=lambda kv: natkey(min(kv[1], key=natkey))):
            refs.sort(key=natkey)
            w.writerow([comps[refs[0]]["value"], ",".join(refs), fp, lcsc, len(refs), comps[refs[0]]["mpn"]])
    problems = []
    with open(out / "canode_CPL_JLC.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for r in sorted(asm, key=natkey):
            p = posrows.get(r)
            if p is None:
                problems.append(f"{r} has an LCSC number but is not in the position file"); continue
            w.writerow([r, f'{float(p["PosX"]):.3f}mm', f'{float(p["PosY"]):.3f}mm',
                        "Top" if p["Side"] == "top" else "Bottom", f'{float(p["Rot"]):.0f}'])
            if p["Side"] != "top": problems.append(f"{r} is on the bottom side (Economic PCBA is top-only)")
    with open(out / "canode_HAND_SOLDER.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["Designator", "Value", "MPN", "Footprint"])
        for r in sorted(comps, key=natkey):
            c = comps[r]
            if not c["lcsc"] and not r.startswith(("H", "JP", "#")) and c["footprint"]:
                w.writerow([r, c["value"], c["mpn"], c["footprint"]])
    for extra in sorted(set(posrows) - set(asm), key=natkey):
        problems.append(f"{extra} is in the position file but has no LCSC number (will not be placed)")
    print(f"{len(groups)} BOM lines, {len(asm)} placements -> {out}")
    for p in problems: print("WARN", p)


if __name__ == "__main__":
    main()
