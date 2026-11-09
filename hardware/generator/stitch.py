from paths import TMP, GEN, FREEROUTING_JAR
import sys, re
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import pcbnew, layout
mm = pcbnew.FromMM
path, out = sys.argv[1], sys.argv[2]
b = pcbnew.LoadBoard(path)
gnd = b.GetNetsByName()["GND"]
W, H = layout.W, layout.H
# candidate grid
cands = []
for x in [3 + 3.0 * i for i in range(int((W - 6) / 3.0) + 1)]:
    for y in [3 + 3.0 * j for j in range(int((H - 6) / 3.0) + 1)]:
        cands.append((x, y))
# keep away from mounting holes and footprint courtyards
def blocked(x, y):
    p = pcbnew.VECTOR2I(mm(100 + x), mm(100 + y))
    for f in b.GetFootprints():
        cy = f.GetCourtyard(pcbnew.F_CrtYd)
        if cy.OutlineCount() and cy.Contains(p): return True
        if f.GetReference().startswith("H") and (f.GetPosition() - p).EuclideanNorm() < mm(4.5): return True
    return False
vias = []
for x, y in cands:
    if blocked(x, y): continue
    v = pcbnew.PCB_VIA(b); v.SetPosition(pcbnew.VECTOR2I(mm(100 + x), mm(100 + y)))
    v.SetDrill(mm(0.3)); v.SetWidth(mm(0.6)); v.SetNet(gnd); v.SetViaType(pcbnew.VIATYPE_THROUGH)
    b.Add(v); vias.append(v)
print("candidates", len(vias))
for rnd in range(4):
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.WriteDRCReport(b, f"{TMP}/st.rpt", pcbnew.EDA_UNITS_MILLIMETRES, True)
    txt = open(f"{TMP}/st.rpt").read()
    bad = set()
    for blk in re.split(r"\n(?=\[)", txt):
        if not blk.startswith("[") or "lib_footprint" in blk or "silk" in blk: continue
        for m in re.finditer(r"@\(([\d.]+) mm, ([\d.]+) mm\): Via \[GND\]", blk):
            bad.add((round(float(m.group(1)), 3), round(float(m.group(2)), 3)))
    rm = [v for v in vias if (round(pcbnew.ToMM(v.GetPosition().x), 3), round(pcbnew.ToMM(v.GetPosition().y), 3)) in bad]
    print("round", rnd, "removing", len(rm))
    if not rm: break
    for v in rm: b.Remove(v); vias.remove(v)
print("stitching vias kept", len(vias))
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
b.Save(out)
