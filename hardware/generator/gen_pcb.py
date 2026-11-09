"""Build canode.kicad_pcb from design.py (placement + nets); no routing."""
import sys, json
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import pcbnew
import design

from paths import FPDIR
OX, OY = 100.0, 100.0          # board origin offset in KiCad coords (mm)
mm = pcbnew.FromMM
def V(x, y): return pcbnew.VECTOR2I(mm(OX + x), mm(OY + y))

POWER_NETS = ["VBAT_IN", "VBATF", "VIN", "VBUS", "+3V3", "GND", "AUX_OUT"]

def build(out, uuids_json):
    uu = json.load(open(uuids_json))["uuids"]
    b = pcbnew.BOARD()
    b.SetCopperLayerCount(2)
    ds = b.GetDesignSettings()
    ds.m_TrackMinWidth = mm(0.15)
    ds.m_ViasMinSize = mm(0.6)
    ds.m_ViasMinDrill = mm(0.3)
    ds.m_MinClearance = mm(0.15)
    ds.m_HoleToHoleMin = mm(0.5)
    ds.m_CopperEdgeClearance = mm(0.3)
    ns = ds.m_NetSettings
    dflt = ns.m_DefaultNetClass
    dflt.SetClearance(mm(0.15)); dflt.SetTrackWidth(mm(0.25))
    dflt.SetViaDiameter(mm(0.6)); dflt.SetViaDrill(mm(0.3))

    nets = {}
    def net(name):
        if name not in nets:
            ni = pcbnew.NETINFO_ITEM(b, name)
            b.Add(ni)
            nets[name] = ni
        return nets[name]
    for p in design.PARTS:
        for n in p["nets"].values(): net(n)

    for p in design.PARTS:
        if p["pcb"] is None: continue
        lib, name = p["fp"].split(":")
        fp = pcbnew.FootprintLoad(f"{FPDIR}/{lib}.pretty", name)
        if fp is None: raise SystemExit("missing fp " + p["fp"])
        fp.SetFPIDAsString(p["fp"])
        fp.SetReference(p["ref"]); fp.SetValue(p["value"])
        x, y, rot = PLACE.get(p["ref"], p["pcb"])
        b.Add(fp)
        fp.SetPosition(V(x, y))
        fp.SetOrientationDegrees(rot)
        fp.SetPath(pcbnew.KIID_PATH("/" + uu[p["ref"]]))
        if p["lcsc"]: fp.SetProperty("LCSC", p["lcsc"])
        if p["mpn"]: fp.SetProperty("MPN", p["mpn"])
        if not p["jlc"]:
            fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
        for pad in fp.Pads():
            num = pad.GetNumber()
            if num in p["nets"]:
                pad.SetNet(nets[p["nets"][num]])
            elif num and p["nets"]:
                pass  # unconnected pad (NC)
        # shrink ref text a bit for density
        r = fp.Reference()
        r.SetTextSize(pcbnew.VECTOR2I(mm(0.8), mm(0.8))); r.SetTextThickness(mm(0.12))
        fp.Value().SetVisible(False)

    # outline with 2 mm corner radius
    W, H, Rr = design.BOARD_W, design.BOARD_H, 2.0
    def line(x1, y1, x2, y2):
        s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(V(x1, y1)); s.SetEnd(V(x2, y2)); s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(mm(0.1)); b.Add(s)
    def arc(cx, cy, sx, sy, ang):
        s = pcbnew.PCB_SHAPE(b); s.SetShape(pcbnew.SHAPE_T_ARC)
        s.SetCenter(V(cx, cy)); s.SetStart(V(sx, sy)); s.SetArcAngleAndEnd(pcbnew.EDA_ANGLE(ang, pcbnew.DEGREES_T))
        s.SetLayer(pcbnew.Edge_Cuts); s.SetWidth(mm(0.1)); b.Add(s)
    line(Rr, 0, W - Rr, 0); line(W, Rr, W, H - Rr); line(W - Rr, H, Rr, H); line(0, H - Rr, 0, Rr)
    arc(W - Rr, Rr, W - Rr, 0, 90); arc(W - Rr, H - Rr, W, H - Rr, 90)
    arc(Rr, H - Rr, Rr, H, 90); arc(Rr, Rr, 0, Rr, 90)

    def silk(txt, x, y, size=1.0, layer=pcbnew.F_SilkS, rot=0, just=None):
        t = pcbnew.PCB_TEXT(b); t.SetText(txt); t.SetPosition(V(x, y)); t.SetLayer(layer)
        t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size))); t.SetTextThickness(mm(size * 0.15))
        if rot: t.SetTextAngleDegrees(rot)
        if just == "left": t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
        if layer == pcbnew.B_SilkS: t.SetMirrored(True)
        b.Add(t)
    for (x, y, txt, size, layer, rot, just) in SILK:
        silk(txt, x, y, size, layer, rot, just)
    b.Save(out)
    return b

SILK = []  # filled by layout module
PLACE = {}

if __name__ == "__main__":
    import layout
    SILK.extend(layout.SILK); PLACE.update(layout.PLACE)
    design.BOARD_W, design.BOARD_H = layout.W, layout.H
    build(sys.argv[1], sys.argv[2])
    print("saved", sys.argv[1])
