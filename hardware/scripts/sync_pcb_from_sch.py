"""Do what F8 (Update PCB from Schematic) would for canode's remaining parity warnings.
- copy Value and every symbol field (Datasheet, LCSC, MPN, ...) from schematic symbols to footprints
- clear 'exclude from BOM' on footprints whose symbol is in the BOM (and set it where the symbol isn't)
- give no-connect pads the schematic's unconnected-(...) net names
Usage (KiCad's bundled Python; it ships the pcbnew module):
  kicad-cli sch export netlist -o /tmp/canode.net hardware/kicad/canode.kicad_sch
  /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/3.9/bin/python3 -I \
      hardware/scripts/sync_pcb_from_sch.py /tmp/canode.net "$PWD/hardware/kicad/canode.kicad_pcb"
  kicad-cli pcb drc --refill-zones --save-board -o /tmp/drc.rpt hardware/kicad/canode.kicad_pcb
Use absolute paths for the board. It changes field/value/BOM-flag/no-connect data only, never footprints or copper.
"""
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "generator"))
import pcbnew
from sexp import find, find1, parse

netlist, board_path = sys.argv[1], sys.argv[2]
root = parse(open(netlist).read())[0]

comps = {}
for c in find(find1(root, "components"), "comp"):
    fields = {}
    fl = find1(c, "fields")
    for f in find(fl, "field") if fl else []:
        fields[find1(f, "name")[1]] = f[2] if len(f) > 2 else ""
    props = [find1(p, "name")[1] for p in find(c, "property")]
    comps[find1(c, "ref")[1]] = dict(fields=fields, value=find1(c, "value")[1], excluded="exclude_from_bom" in props)

pad_nets = {}  # (ref, pad) -> net name, only for unconnected-(...) nets
for n in find(find1(root, "nets"), "net"):
    name = find1(n, "name")[1]
    if name.startswith("unconnected-"):
        for node in find(n, "node"):
            pad_nets[(find1(node, "ref")[1], find1(node, "pin")[1])] = name

board = pcbnew.LoadBoard(board_path)
log = []
for fp in board.GetFootprints():
    ref = fp.GetReference()
    c = comps.get(ref)
    if c is None:
        continue
    for name in c["fields"]:
        if name in ("Footprint", "Value", "Reference"):
            continue
        want = c["fields"][name]
        have = fp.GetFieldText(name) if fp.HasField(name) else None
        if have != want:
            fp.SetField(name, want)
            if name != "Datasheet":
                f = fp.GetField(name)
                f.SetVisible(False)
            log.append(f"{ref}: {name} {have!r} -> {want!r}")
    if fp.GetValue() != c["value"]:
        log.append(f"{ref}: Value {fp.GetValue()!r} -> {c['value']!r}")
        fp.SetValue(c["value"])
    attrs = fp.GetAttributes()
    is_excl = bool(attrs & pcbnew.FP_EXCLUDE_FROM_BOM)
    if is_excl != c["excluded"]:
        fp.SetAttributes(attrs ^ pcbnew.FP_EXCLUDE_FROM_BOM)
        log.append(f"{ref}: exclude_from_bom {is_excl} -> {c['excluded']}")
    for pad in fp.Pads():
        name = pad_nets.get((ref, pad.GetNumber()))
        if name and pad.GetNetname() != name:
            assert pad.GetNetname() == "", (ref, pad.GetNumber(), pad.GetNetname())
            net = board.FindNet(name)
            if net is None:
                net = pcbnew.NETINFO_ITEM(board, name)
                board.Add(net)
            pad.SetNet(net)
            log.append(f"{ref}.{pad.GetNumber()}: net -> {name}")

board.Save(board_path)
print("\n".join(log))
print(f"{len(log)} changes")
