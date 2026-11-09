import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import pcbnew
from sexp import parse, find, find1
mm = pcbnew.FromMM

def import_ses(board, ses_path):
    s = parse(open(ses_path).read())[0]
    routes = find1(s, "routes")
    res = find1(routes, "resolution")
    scale = {"um": 1e-3, "mm": 1.0, "mil": 0.0254}[str(res[1])] / float(res[2])   # unit -> mm
    nets = {n.GetNetname(): n for n in board.GetNetInfo().NetsByName().values()} if False else None
    netmap = board.GetNetsByName()
    layers = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu}
    nt = nv = 0
    for net in find(find1(routes, "network_out"), "net"):
        name = str(net[1])
        ni = netmap[name]
        for w in find(net, "wire"):
            path = find1(w, "path")
            lay = layers[str(path[1])]; width = float(path[2]) * scale
            pts = [float(v) * scale for v in path[3:]]
            xy = [(pts[i], -pts[i + 1]) for i in range(0, len(pts), 2)]
            for (x1, y1), (x2, y2) in zip(xy, xy[1:]):
                t = pcbnew.PCB_TRACK(board)
                t.SetStart(pcbnew.VECTOR2I(mm(x1), mm(y1))); t.SetEnd(pcbnew.VECTOR2I(mm(x2), mm(y2)))
                t.SetWidth(mm(width)); t.SetLayer(lay); t.SetNet(ni)
                board.Add(t); nt += 1
        for v in find(net, "via"):
            x, y = float(v[2]) * scale, -float(v[3]) * scale
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
            via.SetDrill(mm(0.3)); via.SetWidth(mm(0.6)); via.SetNet(ni)
            via.SetViaType(pcbnew.VIATYPE_THROUGH)
            board.Add(via); nv += 1
    return nt, nv

def add_gnd_zones(board, W, H, OX=100.0, OY=100.0):
    gnd = board.GetNetsByName()["GND"]
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer); z.SetNet(gnd)
        z.SetLocalClearance(mm(0.25)); z.SetMinThickness(mm(0.2))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetThermalReliefGap(mm(0.3)); z.SetThermalReliefSpokeWidth(mm(0.4))
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        ol = z.Outline(); ol.NewOutline()
        for x, y in ((0.3, 0.3), (W - 0.3, 0.3), (W - 0.3, H - 0.3), (0.3, H - 0.3)):
            ol.Append(mm(OX + x), mm(OY + y))
        z.SetAssignedPriority(0)
        board.Add(z)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())

if __name__ == "__main__":
    pcb, ses, out = sys.argv[1:4]
    import layout
    b = pcbnew.LoadBoard(pcb)
    print("tracks/vias", import_ses(b, ses))
    add_gnd_zones(b, layout.W, layout.H)
    b.BuildConnectivity()
    c = b.GetConnectivity()
    print("unrouted connections:", c.GetUnconnectedCount(True))
    b.Save(out)
