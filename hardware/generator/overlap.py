import sys, pcbnew
b = pcbnew.LoadBoard(sys.argv[1])
fps = list(b.GetFootprints())
boxes = []
for f in fps:
    bb = f.GetCourtyard(pcbnew.F_CrtYd).BBox() if f.GetCourtyard(pcbnew.F_CrtYd).OutlineCount() else f.GetBoundingBox(False, False)
    boxes.append((f.GetReference(), bb))
ec = b.GetBoardEdgesBoundingBox()
for i in range(len(boxes)):
    r, bb = boxes[i]
    for j in range(i + 1, len(boxes)):
        r2, bb2 = boxes[j]
        if bb.Intersects(bb2):
            print("OVERLAP", r, r2)
    if not ec.Contains(bb) and r not in ("J1",):
        print("OUTSIDE", r, pcbnew.ToMM(bb.GetLeft()) - 100, pcbnew.ToMM(bb.GetTop()) - 100, pcbnew.ToMM(bb.GetRight()) - 100, pcbnew.ToMM(bb.GetBottom()) - 100)
