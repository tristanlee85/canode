"""Simplified 3D models for canode parts that KiCad's library has no STEP for.

KiCad 10's footprints for these parts reference STEP files that the official
kicad-packages3D library does not ship (checked against gitlab master and all
release tags, Nov 2026):

  J1      USB_C_Receptacle_HRO_TYPE-C-31-M-12
  J2      Molex_Micro-Fit_3.0_43045-0812_2x04_P3.00mm_Vertical
  SW1/2   SW_Push_1P1T_XKB_TS-1187A

These are envelope-accurate stand-ins (outline, height, pin positions from the
footprints and the datasheets), good for 3D viewing, renders and enclosure
fit checks. They are not manufacturer models.

Also written: the mating Micro-Fit plug (43025-0800 housing), positioned as
mated on the 43045-0812 footprint. It is used only by the enclosure renders.

Coordinates follow KiCad's 3D-model convention: origin = footprint origin,
X = footprint X, Y = -(footprint Y), Z up from the board's top surface, mm.

Run:  hardware/enclosure/.venv/bin/python hardware/3dmodels/make_models.py
"""
from pathlib import Path

from build123d import (Align, Axis, Box, Color, Compound, Cylinder, Location,
                       Pos, Rot, SlotOverall, export_step, extrude, fillet,
                       Plane, Polyline, make_face)

OUT = Path(__file__).resolve().parent

NYLON_BLACK = Color(0.06, 0.06, 0.065)
NYLON_NATURAL = Color(0.86, 0.84, 0.78)
TIN = Color(0.80, 0.80, 0.82)
STEEL = Color(0.72, 0.73, 0.75)
GOLD = Color(0.85, 0.68, 0.30)
DARK = Color(0.12, 0.12, 0.13)

C = (Align.CENTER, Align.CENTER, Align.MIN)  # centered in XY, sitting on Z=0


def fp(x, y, z=0.0):
    """Footprint coordinates (Y down) to model coordinates (Y up)."""
    return Pos(x, -y, z)


def colored(shape, color, label):
    shape.color = color
    shape.label = label
    return shape


def save(parts, name):
    comp = Compound(children=parts, label=name)
    export_step(comp, OUT / f"{name}.step", timestamp="2026-11-09T00:00:00")  # stable diffs
    bb = comp.bounding_box()
    print(f"{name}.step  bbox x[{bb.min.X:.2f},{bb.max.X:.2f}] "
          f"y[{bb.min.Y:.2f},{bb.max.Y:.2f}] z[{bb.min.Z:.2f},{bb.max.Z:.2f}]")


# --------------------------------------------------------------------------
# J2: Molex Micro-Fit 3.0 43045-0812, 2x4 vertical header
# Footprint: pad 1 at origin, pitch 3.00 along +X, second row at +3.00 Y.
# Body (F.Fab) X -3.575..12.575, Y -2.47..4.90, latch ramp at Y 4.9..6.3.
# Height above PCB 9.91 mm (Molex), mated height 17.27 mm.
# --------------------------------------------------------------------------
MF_H = 9.91
MF_X0, MF_X1 = -3.575, 12.575
MF_Y0, MF_Y1 = -2.47, 4.90
MF_FLOOR = 3.0                      # top of the cavity floor
MF_IN_X0, MF_IN_X1 = -2.05, 11.05    # cavity (plug body fits here)
MF_IN_Y0, MF_IN_Y1 = -1.45, 4.25


def box_fp(x0, x1, y0, y1, z0, z1):
    """Axis-aligned box from footprint-space extents."""
    return fp((x0 + x1) / 2, (y0 + y1) / 2, z0) * Box(
        x1 - x0, y1 - y0, z1 - z0, align=C)


def microfit_header():
    body = box_fp(MF_X0, MF_X1, MF_Y0, MF_Y1, 0, MF_H)
    body -= box_fp(MF_IN_X0, MF_IN_X1, MF_IN_Y0, MF_IN_Y1, MF_FLOOR, MF_H + 1)
    # latch window in the latch-side wall and the external latch ramp
    body -= box_fp(3.6, 5.4, MF_IN_Y1 - 0.1, MF_Y1 + 0.1, 5.2, 7.6)
    body += box_fp(3.8, 5.2, MF_Y1, 6.3, 5.0, 7.4)
    # stand-off feet / chamfered corners on the far side
    body -= box_fp(-0.5, 0.5, MF_Y0 - 0.1, -1.97, 0, 1.0)
    # polarizing ribs inside the cavity (keyed positions)
    for x in (1.5, 7.5):
        body += box_fp(x - 0.4, x + 0.4, MF_IN_Y0, MF_IN_Y0 + 0.5, MF_FLOOR, MF_H - 0.6)
    housing = colored(body, NYLON_BLACK, "housing")

    pins = []
    for i in range(4):
        for row in (0, 3):
            x = 3.0 * i
            pins.append(fp(x, row, -3.0) * Box(0.64, 0.64, MF_FLOOR + 5.2 + 3.0, align=C))
    pegs = [fp(x, 3.94, -2.4) * Cylinder(0.5, 2.4 + 0.1, align=C) for x in (-3, 12)]
    return [housing,
            colored(Compound(pins), TIN, "pins"),
            colored(Compound(pegs), NYLON_BLACK, "pegs")]


def microfit_plug():
    """43025-0800 receptacle housing, mated, plus the start of the wire seals."""
    z0, z1 = MF_FLOOR + 0.2, 17.27
    body = box_fp(MF_IN_X0 + 0.15, MF_IN_X1 - 0.15, MF_IN_Y0 + 0.12, MF_IN_Y1 - 0.12, z0, z1)
    # wire entry holes on top
    for i in range(4):
        for row in (0, 3):
            body -= fp(3.0 * i, row, z1 - 2.0) * Cylinder(0.95, 2.5, align=C)
    # latch: cantilever outside the shroud, hinge bridge, hook and thumb pad
    body += box_fp(3.3, 5.7, MF_IN_Y1 - 0.2, 6.9, 12.0, 13.6)     # bridge
    body += box_fp(3.3, 5.7, 6.4, 7.2, 5.2, 16.6)                 # arm
    body += box_fp(3.3, 5.7, 6.0, 6.4, 5.2, 6.8)                  # hook
    body += box_fp(2.8, 6.2, 6.6, 8.1, 15.2, 16.8)                # thumb pad
    for zz in (15.5, 16.1):                                        # grip ribs
        body += box_fp(2.8, 6.2, 8.1, 8.4, zz, zz + 0.3)
    return [colored(body, NYLON_BLACK, "plug_housing")]


# --------------------------------------------------------------------------
# J1: HRO TYPE-C-31-M-12 USB-C receptacle (top mount, 16P)
# Footprint: shell X +-4.47, Y -3.65..+3.65 (front/mating face at +Y),
# SMD tails at Y -4.045, THT shield legs at X +-4.32, Y -3.13 / +1.05.
# Shell 8.94 x 3.26 mm.
# --------------------------------------------------------------------------
def usb_c():
    w, h, y0, y1 = 8.94, 3.26, -3.65, 3.65
    length = y1 - y0
    outer = SlotOverall(w, h)
    inner = SlotOverall(w - 0.6, h - 0.6)
    # slot profile in a plane facing +Y (front), extruded backwards
    pl = Plane(origin=(0, -y1, h / 2), x_dir=(1, 0, 0), z_dir=(0, 1, 0))
    shell = extrude(pl * outer, amount=length)
    shell -= extrude(pl * inner, amount=length - 0.6)
    tongue = fp(0, (y0 + y1) / 2 + 0.6, h / 2 - 0.35) * Box(6.6, length - 1.6, 0.7, align=C)
    rear_ins = fp(0, y0 + 0.5, 0.25) * Box(w - 0.8, 1.0, h - 0.5, align=C)
    legs = [fp(sx * 4.32, ly, -1.2) * Box(0.55, 1.4 if ly < 0 else 1.0, 1.2 + 0.4, align=C)
            for sx in (-1, 1) for ly in (-3.13, 1.05)]
    tails = [fp(x, -4.045, 0) * Box(0.25, 0.9, 0.12, align=C)
             for x in (-3.25, -2.45, -1.75, -1.25, -0.75, -0.25, 0.25, 0.75, 1.25, 1.75, 2.45, 3.25)]
    contacts = [fp(-2.75 + 0.5 * i, 2.0, h / 2 + 0.0) * Box(0.25, 2.2, 0.06, align=C)
                for i in range(12)]
    return [colored(shell, STEEL, "shell"),
            colored(tongue + rear_ins, DARK, "tongue"),
            colored(Compound(legs + tails), STEEL, "legs"),
            colored(Compound(contacts), GOLD, "contacts")]


# --------------------------------------------------------------------------
# SW1/SW2: XKB TS-1187A 5.1 x 5.1 x 1.5 mm SMD tactile switch
# Footprint: pads at (+-3, +-1.875); body 5.1 sq; plunger dia 2 (F.Fab circle r=1)
# --------------------------------------------------------------------------
def tact():
    base = Box(5.1, 5.1, 0.85, align=C)
    base = fillet(base.edges().filter_by(Axis.Z), 0.25)
    cover = Pos(0, 0, 0.85) * Box(5.0, 5.0, 0.15, align=C)
    dome = Pos(0, 0, 1.0) * Cylinder(1.6, 0.15, align=C)
    plunger = Pos(0, 0, 1.0) * Cylinder(1.0, 0.5, align=C)
    leads = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            leads.append(fp(sx * 3.0, sy * 1.875, 0) * Box(1.0, 0.7, 0.15, align=C))
            leads.append(fp(sx * 2.62, sy * 1.875, 0) * Box(0.25, 0.7, 0.6, align=C))
    return [colored(base, DARK, "base"),
            colored(cover + dome, STEEL, "cover"),
            colored(plunger, DARK, "plunger"),
            colored(Compound(leads), STEEL, "leads")]


if __name__ == "__main__":
    save(microfit_header(), "Molex_Micro-Fit_3.0_43045-0812_2x04_P3.00mm_Vertical")
    save(microfit_plug(), "Molex_Micro-Fit_3.0_43025-0800_plug_mated")
    save(usb_c(), "USB_C_Receptacle_HRO_TYPE-C-31-M-12")
    save(tact(), "SW_Push_1P1T_XKB_TS-1187A")
