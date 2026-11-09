"""Silkscreen cleanup + legends on the routed board."""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import pcbnew
mm = pcbnew.FromMM
OX = OY = 100.0
def V(x, y): return pcbnew.VECTOR2I(mm(OX + x), mm(OY + y))
F, B = pcbnew.F_SilkS, pcbnew.B_SilkS

FRONT = []
for i, t in enumerate(["3V3", "B6", "B7", "B8", "B9", "GND"]): FRONT.append((24.0 + 2.54 * i, 44.4, t, 0.8))
for i, t in enumerate(["3V3", "CLK", "GND", "DIO", "RST"]): FRONT.append((43.0 + 2.54 * i, 44.4, t, 0.8))
for i, t in enumerate(["GND", "TX", "RX"]): FRONT.append((58.5 + 2.54 * i, 44.4, t, 0.8))
FRONT += [(24.0 + 6.35, 48.9, "GPIO", 0.8), (43.0 + 5.08, 48.9, "SWD", 0.8), (58.5 + 2.54, 48.9, "UART", 0.8)]
BACK = [
    (42.5, 37.0, "CAN NODE  rev A  (2026-11)", 1.2),
    (42.5, 39.4, "STM32G0B1 + 2x SN65HVD230", 0.9),
    (10.0, 30.0, "J2 Micro-Fit (top view mirror)", 0.8),
    (10.0, 31.6, "1 12V     5 GND", 0.8),
    (10.0, 33.2, "2 CAN1H   6 CAN1L", 0.8),
    (10.0, 34.8, "3 CAN2H   7 CAN2L", 0.8),
    (10.0, 36.4, "4 AUX_IN  8 AUX_OUT", 0.8),
]
EXTRA_FRONT = {"SW1": "RST", "SW2": "BOOT", "JP1": "TERM1", "JP2": "TERM2", "D4": "PWR", "J1": "USB"}

def text(b, x, y, s, size, layer):
    t = pcbnew.PCB_TEXT(b); t.SetText(s); t.SetPosition(V(x, y)); t.SetLayer(layer)
    t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size))); t.SetTextThickness(mm(max(0.12, size * 0.15)))
    if layer == B: t.SetMirrored(True)
    b.Add(t); return t

def run(path, out):
    b = pcbnew.LoadBoard(path)
    for d in list(b.GetDrawings()):
        if d.GetClass() == "PCB_TEXT": b.Delete(d)
    obstacles = []
    for f in b.GetFootprints():
        for p in f.Pads(): obstacles.append(p.GetBoundingBox())
        for g in f.GraphicalItems():
            if g.GetLayer() == F and not isinstance(g, pcbnew.FP_TEXT): obstacles.append(g.GetBoundingBox())
    placed = []
    for x, y, s, sz in FRONT: placed.append(text(b, x, y, s, sz, F).GetBoundingBox())
    for x, y, s, sz in BACK: text(b, x, y, s, sz, B)
    edge = b.GetBoardEdgesBoundingBox(); edge.Inflate(-mm(0.4))
    fps = sorted(b.GetFootprints(), key=lambda f: -f.GetBoundingBox(False, False).GetArea())
    def place(item, bb):
        cx, cyy = bb.GetCenter().x, bb.GetCenter().y
        cands = []
        for ang in (0, 90):
            item.SetTextAngleDegrees(ang)
            tb = item.GetBoundingBox(); tw, th = tb.GetWidth(), tb.GetHeight()
            g = mm(0.25)
            cands += [(ang, cx, bb.GetTop() - g - th // 2), (ang, cx, bb.GetBottom() + g + th // 2),
                      (ang, bb.GetLeft() - g - tw // 2, cyy), (ang, bb.GetRight() + g + tw // 2, cyy)]
        best = None
        for ang, x, y in cands:
            item.SetTextAngleDegrees(ang); item.SetPosition(pcbnew.VECTOR2I(int(x), int(y)))
            tb = item.GetBoundingBox()
            score = sum(1 for o in obstacles if o.Intersects(tb)) * 10 + sum(1 for o in placed if o.Intersects(tb)) * 10
            if not edge.Contains(tb): score += 100
            score += ang // 90
            if best is None or score < best[0]: best = (score, ang, x, y)
        _, ang, x, y = best
        item.SetTextAngleDegrees(ang); item.SetPosition(pcbnew.VECTOR2I(int(x), int(y)))
        placed.append(item.GetBoundingBox())
        return best[0]
    for f in fps:
        r = f.Reference()
        ref = f.GetReference()
        if ref.startswith("H"):
            r.SetVisible(False); continue
        r.SetTextSize(pcbnew.VECTOR2I(mm(0.8), mm(0.8))); r.SetTextThickness(mm(0.13))
        r.SetKeepUpright(True)
        cy = f.GetCourtyard(pcbnew.F_CrtYd)
        bb = cy.BBox() if cy.OutlineCount() else f.GetBoundingBox(False, False)
        if place(r, bb) >= 10: print("could not cleanly place", ref)
        if ref in EXTRA_FRONT:
            t = text(b, 0, 0, EXTRA_FRONT[ref], 0.8, F)
            bb2 = pcbnew.BOX2I(bb.GetOrigin(), bb.GetSize()); bb2.Merge(r.GetBoundingBox())
            if place(t, bb2) >= 10: print("could not cleanly place label", EXTRA_FRONT[ref])
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    b.Save(out)

if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2])
