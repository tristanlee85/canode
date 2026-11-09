"""canode enclosure, rev A: two-part MJF nylon box (base + lid), parametric.

Everything is modelled in the *board frame*, which is the same frame KiCad's
STEP/GLB export uses:
    X = KiCad x (mm), Y = -KiCad y, Z = 0 at the PCB's bottom face.
That lets us test clearances directly against the exported board and drop the
meshes straight into Blender. The files meant for ordering are re-based so the
part sits on Z=0 at the origin.

Outputs (hardware/enclosure/out/):
    canode_enclosure_base.step / .stl   order this (STEP is committed; STL is gitignored, regenerate)
    canode_enclosure_lid.step  / .stl   order this
build/renders/enclosure/canode_enclosure_assembly.step   base + lid + board, for a CAD viewer
build/renders/enclosure/*.stl           board-frame meshes for the Blender renders

Run:  hardware/enclosure/.venv/bin/python hardware/enclosure/enclosure.py [--check]
--check also imports build/renders/board/canode.step (made by render/build_renders.sh) and
reports any interference between the enclosure and the populated board.
"""
import argparse
import sys
from pathlib import Path

from build123d import (Align, Axis, Box, Compound, Cylinder, FontStyle, Location,
                       Pos, Rot, RectangleRounded, SlotCenterToCenter, Text,
                       export_step, export_stl, extrude, fillet, import_step)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / "out"
RENDER_OUT = ROOT / "build" / "renders" / "enclosure"
BOARD_STEP = ROOT / "build" / "renders" / "board" / "canode.step"

# --------------------------------------------------------------------------- board facts
# (read from hardware/kicad/canode.kicad_pcb; KiCad y is negated here)
BX0, BX1, BY0, BY1 = 100.0, 185.0, -150.0, -100.0      # Edge.Cuts, 85 x 50
BOARD_R = 2.0
PCB_T = 1.6
H1 = (103.5, -103.5)                                    # M3 mounting holes
H2 = (181.5, -146.5)
J2_PINS_X = (107.5, 110.5)                              # Micro-Fit rows (pin 7-12, pin 1-6)
J2_Y = (-114.0, -129.0)                                 # pin 1 .. pin 6 (3.00 pitch)
J2_HEADER_TOP = PCB_T + 9.91                            # Molex 43045 height
USB_Y, USB_ZC = -125.0, PCB_T + 1.63                    # J1 centre line (HRO shell 3.26 tall)
LEDS = {"D4": (153.5, -103.0), "D5": (161.5, -103.0), "D6": (161.5, -105.5)}
SW = {"SW1": (170.0, -142.5), "SW2": (176.5, -135.0)}   # RESET, BOOT (TS-1187A, 1.5 tall)
HEADER_ROW_Y = -146.5                                   # J3/J4/J5 pin row

# --------------------------------------------------------------------------- design parameters
CLEAR = 0.5            # board edge to inner wall
WALL = 2.0
FLOOR = 2.0
STANDOFF = 4.0         # floor top to PCB bottom (THT tails are 3.0 below the top copper)
LID_T = 2.0
LID_GAP = 0.5          # J2 header top to lid underside
LIP_H, LIP_T, LIP_GAP = 2.0, 1.2, 0.3   # lid locating lip (MJF tolerance ~ +-0.3)
R_OUT = 4.5

IX0, IX1 = BX0 - CLEAR, BX1 + CLEAR                     # inner cavity
IY0, IY1 = BY0 - CLEAR, BY1 + CLEAR
OX0, OX1 = IX0 - WALL, IX1 + WALL                       # outer shell
OY0, OY1 = IY0 - WALL, IY1 + WALL
Z_BOT = -(STANDOFF + FLOOR)                             # -6.0
Z_FLOOR = -STANDOFF                                     # -4.0
Z_SPLIT = round(J2_HEADER_TOP + LID_GAP, 2)             # 12.0: base wall top / lid underside
Z_TOP = Z_SPLIT + LID_T                                 # 14.0

CX, CY = (OX0 + OX1) / 2, (OY0 + OY1) / 2
OW, OD = OX1 - OX0, OY1 - OY0
IW, ID = IX1 - IX0, IY1 - IY0

# screws: M3 button head (ISO 7380) x 16 through the lid into M3 heat-set inserts in the base
SCREW_D = 3.4
CBORE_D, CBORE_DEPTH = 6.4, 1.8
BOSS_D = 8.0
INSERT_D, INSERT_DEPTH = 4.0, 5.0      # M3 x 4 mm heat-set insert, 4.0 mm hole
LID_TUBE_D = 6.6

# USB-C: opening sized for the cable's overmold (USB-IF max 12.35 x 6.5) so the
# plug seats fully even though the receptacle face sits 2.85 mm behind the outside wall.
USB_W, USB_H, USB_R = 13.2, 7.4, 3.0

# J2 harness opening in the lid: header footprint + plug latch + finger room
J2_OPEN_X = (IX0, 114.0)
J2_OPEN_Y = (-133.8, -109.2)

LED_BORE = 1.5         # 1.0 mm wall between D5/D6 (JLC MJF: >1.0 mm walls); optional 1.0 mm PMMA fibre light pipe
LED_TUBE_BOTTOM = PCB_T + 1.4
POKE_D, POKE_TUBE_D = 2.0, 4.4
POKE_TUBE_BOTTOM = PCB_T + 1.5 + 1.0    # 1 mm above the switch plunger

EAR_LEN, EAR_W, EAR_T = 11.0, 20.0, 3.0
EAR_SLOT_W, EAR_SLOT_L = 5.0, 7.0       # M4 / #8 screw, or zip-ties up to 4.8 mm

ENGRAVE = 0.4
FONT = "Arial Rounded MT Bold"
STAMP = "2026-11-09T00:00:00"   # fixed STEP header timestamp so regenerating gives stable diffs


def rounded_block(x0, x1, y0, y1, z0, z1, r):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, z0) * extrude(
        RectangleRounded(x1 - x0, y1 - y0, r), amount=z1 - z0)


def box(x0, x1, y0, y1, z0, z1):
    return Pos((x0 + x1) / 2, (y0 + y1) / 2, z0) * Box(
        x1 - x0, y1 - y0, z1 - z0, align=(Align.CENTER, Align.CENTER, Align.MIN))


def cyl(x, y, z0, z1, d):
    return Pos(x, y, z0) * Cylinder(d / 2, z1 - z0, align=(Align.CENTER, Align.CENTER, Align.MIN))


def text(s, size, x, y, rot=0.0, style=FontStyle.BOLD):
    try:
        t = Text(s, font_size=size, font=FONT, font_style=style)
    except Exception:          # font not installed: fall back to build123d's default
        t = Text(s, font_size=size, font_style=style)
    return Pos(x, y, Z_TOP - ENGRAVE) * Rot(0, 0, rot) * extrude(t, amount=ENGRAVE + 1)


# --------------------------------------------------------------------------- base
def make_base():
    shell = rounded_block(OX0, OX1, OY0, OY1, Z_BOT, Z_SPLIT, R_OUT)
    shell -= rounded_block(IX0, IX1, IY0, IY1, Z_FLOOR, Z_SPLIT + 1, BOARD_R + CLEAR)

    # mounting ears at both short ends, flush with the bottom (VHB-friendly flat base)
    for sgn, xw in ((-1, OX0), (1, OX1)):
        x0, x1 = sorted((xw - sgn * 2, xw + sgn * EAR_LEN))
        ear = rounded_block(x0, x1, CY - EAR_W / 2, CY + EAR_W / 2, Z_BOT, Z_BOT + EAR_T, 3.0)
        sx = xw + sgn * (EAR_LEN / 2 + 0.3)
        ear -= Pos(sx, CY, Z_BOT - 1) * extrude(
            SlotCenterToCenter(EAR_SLOT_L - EAR_SLOT_W, EAR_SLOT_W), amount=EAR_T + 2)
        shell += ear
        # two small gussets per ear
        for gy in (CY - EAR_W / 2 + 1.5, CY + EAR_W / 2 - 1.5):
            g = box(min(xw, xw + sgn * 4), max(xw, xw + sgn * 4), gy - 0.75, gy + 0.75,
                    Z_BOT, Z_BOT + EAR_T + 3)
            shell += g

    # PCB supports: screw bosses with insert holes, corner pegs, ribs under the connectors
    for (x, y) in (H1, H2):
        shell += cyl(x, y, Z_FLOOR - 0.01, 0, BOSS_D)
    for (x, y) in ((182.5, -102.5), (102.5, -147.5),        # free corners
                   (181.0, -125.0),                         # under USB-C (between shield legs)
                   SW["SW1"], SW["SW2"]):                   # under the poke buttons
        shell += cyl(x, y, Z_FLOOR - 0.01, 0, 3.0)
    shell += box(101.0, 103.0, -133.0, -110.0, Z_FLOOR - 0.01, 0)   # J2 mating force
    shell += box(121.0, 166.0, -149.6, -148.4, Z_FLOOR - 0.01, 0)   # J3-J5 mating force
    # keep the cavity clean: re-cut anything that grew into the wall clearance above the PCB
    for (x, y) in (H1, H2):
        shell -= cyl(x, y, -INSERT_DEPTH, 0.1, INSERT_D)

    # USB-C opening in the +X wall
    shell -= Pos(OX1, USB_Y, USB_ZC) * Rot(0, 90, 0) * extrude(
        RectangleRounded(USB_H, USB_W, USB_R), amount=10, both=True)

    # bottom label (engraved): pinout for the installer
    lbl = [("canode rev A", 4.0, CX, CY + 16),
           ("J2: 1 +12V  2 CAN1H  3 CAN2H  4 AUX IN  5 IGN  6 AUX2", 2.4, CX, CY + 6),
           ("7 GND  8 CAN1L  9 CAN2L  10 AUX OUT  11 ID  12 GND", 2.4, CX, CY + 1),
           ("Micro-Fit 3.0  43025-1200", 2.4, CX, CY - 5)]
    for s, size, x, y in lbl:
        try:
            t = Text(s, font_size=size, font=FONT)
        except Exception:
            t = Text(s, font_size=size)
        # mirror so it reads correctly when the box is flipped over
        shell -= Pos(x, y, Z_BOT - 1) * Rot(0, 180, 0) * extrude(t, amount=-(1 + ENGRAVE))
    return shell


# --------------------------------------------------------------------------- lid
def make_lid():
    lid = rounded_block(OX0, OX1, OY0, OY1, Z_SPLIT, Z_TOP, R_OUT)
    # locating lip that drops inside the base walls
    lx0, lx1 = IX0 + LIP_GAP, IX1 - LIP_GAP
    ly0, ly1 = IY0 + LIP_GAP, IY1 - LIP_GAP
    lip = rounded_block(lx0, lx1, ly0, ly1, Z_SPLIT - LIP_H, Z_SPLIT + 0.01, BOARD_R + CLEAR - LIP_GAP)
    lip -= rounded_block(lx0 + LIP_T, lx1 - LIP_T, ly0 + LIP_T, ly1 - LIP_T,
                         Z_SPLIT - LIP_H - 1, Z_SPLIT + 1, 1.0)
    lid += lip

    # screw tubes clamp the PCB onto the base bosses
    for (x, y) in (H1, H2):
        lid += cyl(x, y, PCB_T, Z_SPLIT + 0.01, LID_TUBE_D)
        lid -= cyl(x, y, PCB_T - 1, Z_TOP + 1, SCREW_D)
        lid -= cyl(x, y, Z_TOP - CBORE_DEPTH, Z_TOP + 1, CBORE_D)

    # LED light guides: one tube for D4, a twin block for D5/D6 (2.5 mm apart)
    d4 = LEDS["D4"]
    lid += cyl(*d4, LED_TUBE_BOTTOM, Z_SPLIT + 0.01, LED_BORE + 1.6)
    d5, d6 = LEDS["D5"], LEDS["D6"]
    lid += cyl(*d5, LED_TUBE_BOTTOM, Z_SPLIT + 0.01, LED_BORE + 1.6)
    lid += cyl(*d6, LED_TUBE_BOTTOM, Z_SPLIT + 0.01, LED_BORE + 1.6)
    lid += box(d5[0] - (LED_BORE + 1.6) / 2, d5[0] + (LED_BORE + 1.6) / 2, d6[1], d5[1],
               LED_TUBE_BOTTOM, Z_SPLIT + 0.01)
    for p in LEDS.values():
        lid -= cyl(*p, LED_TUBE_BOTTOM - 1, Z_TOP + 1, LED_BORE)

    # paper-clip holes for RESET / BOOT with guide tubes and a lead-in chamfer
    for p in SW.values():
        lid += cyl(*p, POKE_TUBE_BOTTOM, Z_SPLIT + 0.01, POKE_TUBE_D)
        lid -= cyl(*p, POKE_TUBE_BOTTOM - 1, Z_TOP + 1, POKE_D)
        lid -= cyl(*p, Z_TOP - 0.6, Z_TOP + 1, POKE_D + 1.0)      # lead-in

    # harness opening over J2 (through the lid and its lip)
    x0, x1 = J2_OPEN_X
    y0, y1 = J2_OPEN_Y
    lid -= rounded_block(x0, x1, y0, y1, Z_SPLIT - LIP_H - 1, Z_TOP + 1, 1.2)
    lid -= box(IX0 - 0.01, x0 + 1.3, y0, y1, Z_SPLIT - LIP_H - 1, Z_SPLIT)   # lip ends square

    # engraving
    cuts = [
        text("canode", 7.5, 149.0, -126.0),
        text("dual CAN", 2.6, 149.0, -132.5, style=FontStyle.REGULAR),
        text("PWR", 2.2, LEDS["D4"][0], -108.8),
        text("1", 2.2, 164.6, -103.0),
        text("2", 2.2, 164.6, -105.5),
        text("RST", 2.2, SW["SW1"][0], -147.0),
        text("BOOT", 2.2, SW["SW2"][0], -139.6),
        text("USB", 2.2, 181.0, -117.0),
    ]
    # J2 legend, one row per pin pair, left column = pins 7-12, right column = pins 1-6
    rows = [("GND", "+12V"), ("CAN1 L", "H"), ("CAN2 L", "H"), ("AUX OUT", "IN"), ("ID", "IGN"), ("GND", "AUX2")]
    for i, (a, b) in enumerate(rows):
        y = J2_Y[0] - 3.0 * i
        cuts.append(text(f"{a} | {b}", 2.0, 124.0, y))
    cuts.append(text("J2", 2.2, 116.5, -108.0))
    for c in cuts:
        lid -= c
    return lid


def interference_report(parts):
    if not BOARD_STEP.exists():
        print(f"--check: {BOARD_STEP} missing; run render/build_renders.sh first")
        return 1
    board = import_step(str(BOARD_STEP))
    plug_path = ROOT / "hardware" / "3dmodels" / "Molex_Micro-Fit_3.0_43025-1200_plug_mated.step"
    plug = Pos(110.5, -114.0, PCB_T) * Rot(0, 0, -90) * import_step(str(plug_path))
    solids = list(board.solids()) + list(plug.solids())
    print(f"--check: {len(solids)} board/plug solids vs enclosure")
    bad = 0
    for name, part in parts.items():
        for s in solids:
            if not s.bounding_box().overlaps(part.bounding_box()):
                continue
            inter = part & s
            v = sum(x.volume for x in inter.solids()) if inter else 0.0
            if v > 1e-3:
                bb = s.bounding_box()
                print(f"  INTERFERENCE {name}: {v:.3f} mm3 with solid at "
                      f"x[{bb.min.X:.1f},{bb.max.X:.1f}] y[{-bb.max.Y:.1f},{-bb.min.Y:.1f}] "
                      f"z[{bb.min.Z:.1f},{bb.max.Z:.1f}] (kicad coords)")
                bad += 1
    print("--check: no interference" if not bad else f"--check: {bad} interferences")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    base, lid = make_base(), make_lid()
    print(f"outer {OW:.1f} x {OD:.1f} x {Z_TOP - Z_BOT:.1f} mm "
          f"({OW + 2 * (EAR_LEN - 2):.1f} long with ears); "
          f"base {base.volume / 1000:.1f} cm3, lid {lid.volume / 1000:.1f} cm3")

    OUT.mkdir(exist_ok=True)
    RENDER_OUT.mkdir(parents=True, exist_ok=True)
    # order files: each part re-based to the origin, resting on Z=0 (MJF needs no orientation)
    to_origin = Location((-CX, -CY, -Z_BOT))
    lid_origin = Location((-CX, -CY, -(Z_SPLIT - LIP_H)))
    base_o, lid_o = to_origin * base, lid_origin * lid
    for nm, shp in (("base", base_o), ("lid", lid_o)):
        export_step(shp, OUT / f"canode_enclosure_{nm}.step", write_pcurves=False, timestamp=STAMP)
        export_stl(shp, OUT / f"canode_enclosure_{nm}.stl", tolerance=0.03, angular_tolerance=0.2)
    # board-frame meshes for Blender
    export_stl(base, RENDER_OUT / "base.stl", tolerance=0.01, angular_tolerance=0.1)
    export_stl(lid, RENDER_OUT / "lid.stl", tolerance=0.01, angular_tolerance=0.1)
    plug = import_step(str(ROOT / "hardware" / "3dmodels" /
                           "Molex_Micro-Fit_3.0_43025-1200_plug_mated.step"))
    plug = Pos(110.5, -114.0, PCB_T) * Rot(0, 0, -90) * plug
    export_stl(plug, RENDER_OUT / "plug.stl", tolerance=0.01, angular_tolerance=0.1)

    if BOARD_STEP.exists():
        asm = Compound(children=[base, lid, import_step(str(BOARD_STEP))])
        export_step(asm, RENDER_OUT / "canode_enclosure_assembly.step", timestamp=STAMP)

    if args.check:
        sys.exit(interference_report({"base": base, "lid": lid}))


if __name__ == "__main__":
    main()
