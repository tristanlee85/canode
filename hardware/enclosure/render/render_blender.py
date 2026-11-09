"""Photoreal renders of the canode board and enclosure (Blender 4.2+/5.x, Cycles).

Run headless (build_renders.sh does this):
    blender -b --factory-startup -P hardware/enclosure/render/render_blender.py -- \
        --out build/renders/raw [--samples 160] [--scenes board_hero,enc_closed,...]

Inputs (made by build_renders.sh):
    build/renders/board/canode.glb          board + components (kicad-cli pcb export glb)
    build/renders/enclosure/{base,lid,plug}.stl   board-frame meshes (enclosure.py)

Frame: metres, X = KiCad x, Y = -KiCad y, Z = 0 at the PCB bottom (KiCad's own 3D export frame).
"""
import argparse
import math
import sys
from pathlib import Path

import bpy
from mathutils import Euler, Matrix, Vector

ROOT = Path(__file__).resolve().parents[3]
GLB = ROOT / "build/renders/board/canode.glb"
ENC = ROOT / "build/renders/enclosure"
MM = 0.001
LIGHT_SCALE = 1.0
RES = (1600, 1000)

# geometry shared with enclosure.py (mm, board frame)
PCB_T = 1.6
Z_BOT, Z_SPLIT, Z_TOP = -6.0, 12.0, 14.0
H1, H2 = (103.5, -103.5), (181.5, -146.5)
J2_PINS = [(110.5, -114.0 - 3 * i) for i in range(4)] + [(107.5, -114.0 - 3 * i) for i in range(4)]
PLUG_TOP = PCB_T + 17.27
USB_Y, USB_ZC, WALL_X = -125.0, PCB_T + 1.63, 187.5
LEDS = {"D4": (153.5, -103.0, (0.1, 1.0, 0.15)), "D5": (161.5, -103.0, (1.0, 0.75, 0.05)),
        "D6": (161.5, -105.5, (1.0, 0.08, 0.04))}
# wire colours by J2 pin (1..8): 12V, CAN1H, CAN2H, AUX_IN, GND, CAN1L, CAN2L, AUX_OUT
WIRE_COL = [(0.55, 0.02, 0.02), (0.75, 0.55, 0.02), (0.85, 0.85, 0.82), (0.25, 0.05, 0.35),
            (0.015, 0.015, 0.015), (0.03, 0.30, 0.06), (0.02, 0.10, 0.45), (0.25, 0.25, 0.25)]


def v(x, y, z):
    return Vector((x * MM, y * MM, z * MM))


# ----------------------------------------------------------------------------- materials
def principled(name, color, rough=0.5, metal=0.0, alpha=1.0, coat=0.0, emit=None, strength=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1.0)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    b.inputs["Alpha"].default_value = alpha
    if coat:
        b.inputs["Coat Weight"].default_value = coat
        b.inputs["Coat Roughness"].default_value = 0.08
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1.0)
        b.inputs["Emission Strength"].default_value = strength
    return m


def mjf_nylon(name="MJF PA12 black"):
    """Matte, slightly grainy dyed-black MJF nylon."""
    m = principled(name, (0.022, 0.022, 0.024), rough=0.82)
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 9000.0
    noise.inputs["Detail"].default_value = 2.0
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.25
    bump.inputs["Distance"].default_value = 0.00004
    nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    b.inputs["Specular IOR Level"].default_value = 0.35
    return m


MATS = {}


def mats():
    if MATS:
        return MATS
    MATS.update(
        mask=principled("soldermask", (0.004, 0.06, 0.018), rough=0.5, alpha=0.88),
        silk=principled("silkscreen", (0.92, 0.92, 0.90), rough=0.6),
        fr4=principled("FR4", (0.55, 0.50, 0.30), rough=0.7),
        tin=principled("tin", (0.78, 0.78, 0.80), rough=0.22, metal=1.0),
        gold=principled("gold", (0.95, 0.72, 0.36), rough=0.2, metal=1.0),
        steel=principled("steel", (0.62, 0.63, 0.66), rough=0.28, metal=1.0),
        black_epoxy=principled("epoxy", (0.018, 0.018, 0.02), rough=0.45),
        black_nylon=principled("nylon", (0.012, 0.012, 0.013), rough=0.5),
        ceramic=principled("ceramic", (0.33, 0.22, 0.13), rough=0.55),
        light_plastic=principled("led body", (0.85, 0.85, 0.8), rough=0.35),
        marking=principled("marking", (0.45, 0.45, 0.45), rough=0.6),
        mjf=mjf_nylon(),
        brass=principled("brass", (0.85, 0.65, 0.32), rough=0.3, metal=1.0),
        screw=principled("screw", (0.04, 0.04, 0.045), rough=0.35, metal=1.0),
        pvc_black=principled("pvc", (0.006, 0.006, 0.007), rough=0.55),
        sleeve=principled("sleeve", (0.012, 0.012, 0.014), rough=0.7),
        floor=principled("floor", (0.80, 0.80, 0.79), rough=0.55),
        ruler=principled("ruler", (0.70, 0.71, 0.72), rough=0.35, metal=1.0),
        ink=principled("ink", (0.02, 0.02, 0.02), rough=0.6),
    )
    return MATS


def classify(mat):
    """Map KiCad GLB materials (STEP colours, metallic=1/rough=1) onto real ones."""
    b = mat.node_tree.nodes.get("Principled BSDF") if mat.use_nodes else None
    if b is None:
        return None
    r, g, bl, _ = b.inputs["Base Color"].default_value
    metal = b.inputs["Metallic"].default_value
    rough = b.inputs["Roughness"].default_value
    alpha = b.inputs["Alpha"].default_value
    M = mats()
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * bl
    if not (metal > 0.99 and rough > 0.99):           # board layers
        if alpha < 0.88 and g > r:
            return M["mask"]
        if alpha < 0.95 and lum > 0.9:
            return M["silk"]
        if metal > 0.5:
            return M["tin"]
        return M["fr4"]
    if lum < 0.06:
        return M["black_epoxy"]
    if r > 0.6 and bl < 0.35 and r - bl > 0.3:
        return M["gold"]
    if abs(r - g) < 0.05 and abs(g - bl) < 0.08 and lum > 0.42:
        return M["light_plastic"] if lum > 0.7 else M["tin"]
    if r > 0.7 and bl > 0.55:
        return M["light_plastic"]
    if r < 0.15 and g > 0.3:                           # LED lens
        return None
    if r > g > bl and lum < 0.12:
        return M["ceramic"]
    return M["marking"]


def import_board():
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(GLB))
    objs = [o for o in bpy.data.objects if o not in before]
    for o in objs:
        if o.type != "MESH":
            continue
        for slot in o.material_slots:
            if slot.material is None:
                continue
            new = classify(slot.material)
            if new is None and o.name in LEDS:
                col = LEDS[o.name][2]
                new = principled(f"lens {o.name}", col, rough=0.15, emit=col, strength=0.0)
                new["led"] = o.name
            elif new is None:
                new = mats()["light_plastic"]
            slot.material = new
    root = bpy.data.objects.new("BOARD", None)
    bpy.context.scene.collection.objects.link(root)
    for o in objs:
        if o.parent is None:
            o.parent = root
    return root


def set_leds(on):
    for m in bpy.data.materials:
        if "led" in m:
            m.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = \
                (25.0 if on.get(m["led"]) else 0.0)


def import_stl(name, mat):
    bpy.ops.wm.stl_import(filepath=str(ENC / f"{name}.stl"), global_scale=MM)
    o = bpy.context.selected_objects[0]
    o.name = name
    o.data.materials.clear()
    o.data.materials.append(mat)
    # auto-smooth: smooth curved faces, keep hard edges
    try:
        bpy.ops.object.shade_auto_smooth(angle=math.radians(35))
    except Exception:
        try:
            bpy.ops.object.shade_smooth_by_angle(angle=math.radians(35))
        except Exception:
            pass
    return o


# ----------------------------------------------------------------------------- props
def curve_obj(name, pts, radius, mat, res=24):
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = radius
    cu.bevel_resolution = 4
    cu.resolution_u = res
    cu.use_fill_caps = True
    sp = cu.splines.new("BEZIER")
    sp.bezier_points.add(len(pts) - 1)
    for bp, p in zip(sp.bezier_points, pts):
        bp.co = p
        bp.handle_left_type = bp.handle_right_type = "AUTO"
    o = bpy.data.objects.new(name, cu)
    o.data.materials.append(mat)
    bpy.context.scene.collection.objects.link(o)
    return o


def harness(lift=0.0, loom=None):
    """Eight wires out of the Micro-Fit plug, gathered into a loom heading off to -X.
    loom: optional list of extra (x, y, z) mm points the loom follows after the default start."""
    objs = []
    cx, cy = 109.0, -118.5
    for i, (x, y) in enumerate(J2_PINS):
        col = WIRE_COL[i]
        m = principled(f"wire{i + 1}", col, rough=0.38)
        dx, dy = x - cx, y - cy
        z0 = PLUG_TOP - 1.5 + lift
        pts = [v(x, y, z0), v(x, y, z0 + 7), v(cx + dx * 0.55, cy + dy * 0.55, z0 + 17),
               v(cx - 12 + dx * 0.35, cy + dy * 0.35, z0 + 26), v(cx - 24 + dx * 0.3, cy + dy * 0.3, z0 + 29)]
        objs.append(curve_obj(f"wire{i + 1}", pts, 0.8 * MM, m))
    if loom is None:
        pts = [v(cx - 21, cy, PLUG_TOP + 28.6 + lift), v(cx - 45, cy + 3, PLUG_TOP + 31 + lift),
               v(cx - 85, cy + 14, PLUG_TOP + 27 + lift), v(cx - 140, cy + 30, PLUG_TOP + 18 + lift)]
    else:
        pts = [v(cx - 21, cy, PLUG_TOP + 28.6 + lift), v(cx - 40, cy + 2, PLUG_TOP + 29 + lift)] + \
              [v(*p) for p in loom]
    objs.append(curve_obj("loom", pts, 4.2 * MM, mats()["sleeve"]))
    return objs


def rounded_box(name, size, bevel, mat, loc):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.active_object
    o.name = name
    o.scale = size
    bpy.ops.object.transform_apply(scale=True)
    mod = o.modifiers.new("bevel", "BEVEL")
    mod.width = bevel
    mod.segments = 6
    o.data.materials.append(mat)
    bpy.ops.object.shade_smooth()
    return o


def usb_cable():
    """Generic USB-C cable plugged into J1 through the +X wall."""
    objs = []
    L = 22.0
    objs.append(rounded_box("usb_overmold", (L * MM, 12.0 * MM, 6.2 * MM), 2.6 * MM,
                            mats()["pvc_black"], v(WALL_X + 0.6 + L / 2, USB_Y, USB_ZC)))
    objs.append(rounded_box("usb_shell", (7.0 * MM, 8.2 * MM, 2.4 * MM), 1.1 * MM,
                            mats()["steel"], v(WALL_X - 2.5, USB_Y, USB_ZC)))
    strain = [v(WALL_X + L, USB_Y, USB_ZC), v(WALL_X + L + 8, USB_Y, USB_ZC)]
    objs.append(curve_obj("usb_strain", strain, 2.6 * MM, mats()["pvc_black"]))
    cable = [v(WALL_X + L + 6, USB_Y, USB_ZC), v(WALL_X + L + 30, USB_Y - 4, USB_ZC - 1),
             v(WALL_X + L + 60, USB_Y - 25, Z_BOT + 2.2), v(WALL_X + L + 110, USB_Y - 60, Z_BOT + 2.0)]
    objs.append(curve_obj("usb_cable", cable, 2.0 * MM, mats()["pvc_black"]))
    return objs


def screw(x, y, z_head, name):
    """M3 button-head (ISO 7380) x 16, black oxide; z_head = underside of the head (mm)."""
    objs = []
    bpy.ops.mesh.primitive_uv_sphere_add(radius=2.85 * MM, location=v(x, y, z_head), segments=48, ring_count=24)
    head = bpy.context.active_object
    head.scale = (1, 1, 1.65 / 2.85)
    bpy.ops.object.transform_apply(scale=True)
    # cut the lower half + hex socket
    bpy.ops.mesh.primitive_cube_add(size=8 * MM, location=v(x, y, z_head - 4))
    cut = bpy.context.active_object
    bpy.ops.mesh.primitive_cylinder_add(vertices=6, radius=1.15 * MM, depth=3 * MM,
                                        location=v(x, y, z_head + 1.65))
    hexs = bpy.context.active_object
    for c in (cut, hexs):
        mod = head.modifiers.new("cut", "BOOLEAN")
        mod.object = c
        mod.operation = "DIFFERENCE"
        bpy.context.view_layer.objects.active = head
        bpy.ops.object.modifier_apply(modifier=mod.name)
        bpy.data.objects.remove(c)
    head.name = name
    head.data.materials.clear()          # booleans can leave an empty slot 0 behind
    head.data.materials.append(mats()["screw"])
    bpy.ops.object.select_all(action="DESELECT")
    head.select_set(True)
    bpy.context.view_layer.objects.active = head
    bpy.ops.object.shade_smooth()
    objs.append(head)
    bpy.ops.mesh.primitive_cylinder_add(radius=1.45 * MM, depth=16 * MM, vertices=32,
                                        location=v(x, y, z_head - 8))
    sh = bpy.context.active_object
    sh.name = name + "_shank"
    sh.data.materials.append(mats()["screw"])
    objs.append(sh)
    return objs


def insert(x, y, z_top, name):
    bpy.ops.mesh.primitive_cylinder_add(radius=2.3 * MM, depth=4 * MM, vertices=40,
                                        location=v(x, y, z_top - 2))
    o = bpy.context.active_object
    o.name = name
    bpy.ops.mesh.primitive_cylinder_add(radius=1.25 * MM, depth=5 * MM, vertices=24,
                                        location=v(x, y, z_top - 2))
    c = bpy.context.active_object
    mod = o.modifiers.new("hole", "BOOLEAN")
    mod.object = c
    mod.operation = "DIFFERENCE"
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(c)
    o.data.materials.clear()
    o.data.materials.append(mats()["brass"])
    return o


def light_pipes(dz=0.0):
    """Optional 1.5 mm PMMA light-pipe ends glowing in the lid holes."""
    objs = []
    for ref, (x, y, col) in LEDS.items():
        m = principled(f"pipe {ref}", col, rough=0.2, emit=col, strength=1.2)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.78 * MM, depth=0.4 * MM, vertices=24,
                                            location=v(x, y, Z_TOP - 0.25 + dz))
        o = bpy.context.active_object
        o.data.materials.append(m)
        objs.append(o)
    return objs


def ruler(x0, y0, length=150):
    """Steel rule with mm ticks and cm numbers, lying on the floor (for scale)."""
    w = 19.0
    objs = [rounded_box("ruler", (length * MM + 6 * MM, w * MM, 0.8 * MM), 0.3 * MM,
                        mats()["ruler"], v(x0 + length / 2, y0, Z_BOT + 0.4))]
    bm_verts = []
    for i in range(length + 1):
        L = 6.0 if i % 10 == 0 else (4.5 if i % 5 == 0 else 3.0)
        bpy.ops.mesh.primitive_cube_add(size=1, location=v(x0 + i, y0 + w / 2 - L / 2, Z_BOT + 0.81))
        t = bpy.context.active_object
        t.scale = (0.18 * MM, L * MM, 0.02 * MM)
        bm_verts.append(t)
        if i % 10 == 0:
            cu = bpy.data.curves.new(f"n{i}", "FONT")
            cu.body = str(i // 10)
            cu.size = 3.2 * MM
            cu.align_x = "CENTER"
            to = bpy.data.objects.new(f"n{i}", cu)
            to.location = v(x0 + i, y0 + w / 2 - 10.5, Z_BOT + 0.81)
            to.data.materials.append(mats()["ink"])
            bpy.context.scene.collection.objects.link(to)
            objs.append(to)
    bpy.ops.object.select_all(action="DESELECT")
    for t in bm_verts:
        t.select_set(True)
    bpy.context.view_layer.objects.active = bm_verts[0]
    bpy.ops.object.join()
    ticks = bpy.context.active_object
    ticks.data.materials.append(mats()["ink"])
    cu = bpy.data.curves.new("cmlabel", "FONT")
    cu.body = "cm"
    cu.size = 2.6 * MM
    lab = bpy.data.objects.new("cmlabel", cu)
    lab.location = v(x0 + length - 9, y0 - w / 2 + 3.5, Z_BOT + 0.81)
    lab.data.materials.append(mats()["ink"])
    bpy.context.scene.collection.objects.link(lab)
    return objs + [ticks, lab]


# ----------------------------------------------------------------------------- per-vehicle T-harness
# Representative housings only: pin count, colour and lock style suggest each vehicle's
# connector family, they are not dimensioned copies of the OEM parts. The real connector is
# picked per vehicle once the tap point (module and pins) is confirmed on the car.
VEHICLES = {
    "ford": dict(title="Ford Bronco Sport: inline at the gateway module (GWM)",
                 rows=2, cols=12, pitch=2.8, body=(0.014, 0.014, 0.015), lock="lever",
                 lock_col=(0.30, 0.31, 0.33), module="GWM"),
    "gm": dict(title="Chevrolet Silverado 3500: inline at a body-network module",
               rows=2, cols=8, pitch=3.5, body=(0.40, 0.41, 0.43), lock="cpa",
               lock_col=(0.80, 0.10, 0.05), module="MODULE"),
    "bmw": dict(title="BMW F80 M3: inline at a body-network module",
                rows=3, cols=9, pitch=2.5, body=(0.014, 0.014, 0.015), lock="slider",
                lock_col=(0.42, 0.20, 0.55), module="MODULE"),
}


class Frame:
    """Local placement: origin (mm) plus a rotation about Z in degrees (multiples of 90)."""

    def __init__(self, x, y, z, deg):
        self.x, self.y, self.z, self.deg = x, y, z, deg

    def p(self, lx, ly, lz):
        a = math.radians(self.deg)
        c, s = math.cos(a), math.sin(a)
        return (self.x + lx * c - ly * s, self.y + lx * s + ly * c, self.z + lz)

    def box(self, name, size, local, mat, bevel=0.3):
        sx, sy, sz = size
        if self.deg % 180:
            sx, sy = sy, sx
        return rounded_box(name, (sx * MM, sy * MM, sz * MM), bevel * MM, mat, v(*self.p(*local)))


def conn_size(spec):
    return spec["cols"] * spec["pitch"] + 5.0, spec["rows"] * spec["pitch"] + 5.0   # W, H


def oem_connector(name, fr, spec, gender, body_mat, lock_mat, D=20.0):
    """Mating face at local x=0 facing +X, body toward -X, cable boot behind it.
    gender 'f' = harness receptacle (terminal cavities, lock); 'm' = inline header (shroud, pins).
    Returns (objects, rear cable exit point in mm)."""
    r, c, p = spec["rows"], spec["cols"], spec["pitch"]
    W, H = conn_size(spec)
    dark = mats()["black_epoxy"]
    objs = []
    grid = [((j - (c - 1) / 2) * p, (i - (r - 1) / 2) * p) for i in range(r) for j in range(c)]
    if gender == "f":
        objs.append(fr.box(f"{name}_body", (D, W, H), (-D / 2, 0, 0), body_mat, 1.0))
        for k, (ly, lz) in enumerate(grid):
            objs.append(fr.box(f"{name}_cav{k}", (0.3, p * 0.55, p * 0.55), (0.06, ly, lz), dark, 0.05))
        if spec["lock"] == "lever":
            for sgn in (-1, 1):
                objs.append(fr.box(f"{name}_lever{sgn}", (9, 1.2, H * 0.9), (-D * 0.45, sgn * (W / 2 + 0.7), 0),
                                   lock_mat, 0.4))
            objs.append(fr.box(f"{name}_leverbar", (3.5, W + 2.6, 1.6), (-D * 0.45 - 3, 0, H / 2 + 0.9),
                               lock_mat, 0.5))
        elif spec["lock"] == "cpa":
            objs.append(fr.box(f"{name}_latch", (7, 7, 2.0), (-4.5, 0, H / 2 + 0.9), body_mat, 0.4))
            objs.append(fr.box(f"{name}_cpa", (4, 4.5, 1.6), (-10, 0, H / 2 + 1.0), lock_mat, 0.4))
        else:
            objs.append(fr.box(f"{name}_slider", (D * 0.6, W * 0.8, 1.3), (-D * 0.55, 0, H / 2 + 0.55),
                               lock_mat, 0.4))
    else:
        S, t = 9.0, 1.2
        Wo, Ho = W + 2 * t + 0.6, H + 2 * t + 0.6          # shroud fits over the receptacle
        objs.append(fr.box(f"{name}_body", (D - S, Wo, Ho), (-(D + S) / 2, 0, 0), body_mat, 1.0))
        for sgn in (-1, 1):
            objs.append(fr.box(f"{name}_wz{sgn}", (S, Wo, t), (-S / 2, 0, sgn * (Ho - t) / 2), body_mat, 0.3))
            objs.append(fr.box(f"{name}_wy{sgn}", (S, t, Ho - 2 * t), (-S / 2, sgn * (Wo - t) / 2, 0),
                               body_mat, 0.3))
        objs.append(fr.box(f"{name}_floor", (0.3, Wo - 2 * t, Ho - 2 * t), (-S + 0.1, 0, 0), dark, 0.05))
        for k, (ly, lz) in enumerate(grid):
            objs.append(fr.box(f"{name}_pin{k}", (S - 2.2, 0.64, 0.64), (-S + (S - 2.2) / 2, ly, lz),
                               mats()["tin"], 0.1))
        objs.append(fr.box(f"{name}_ramp", (3, 6, 1.0), (-2.5, 0, Ho / 2 + 0.4), body_mat, 0.3))
        W, H = Wo, Ho
    objs.append(fr.box(f"{name}_boot", (9, W * 0.62, H * 0.75), (-D - 4, 0, 0), mats()["pvc_black"],
                       min(W, H) * 0.3))
    return objs, fr.p(-D - 8.5, 0, 0)


def module_box(name, fr, spec, label):
    """A control module seen from its connector side: header face at local x=0 facing +X."""
    W, H = conn_size(spec)
    body = principled("module", (0.018, 0.018, 0.02), rough=0.55)
    objs = [fr.box(f"{name}_body", (42, 74, 30), (-21, 0, 0), body, 1.5)]
    t = 1.6
    for sgn in (-1, 1):   # header shroud the receptacle sits in
        objs.append(fr.box(f"{name}_sz{sgn}", (6, W + 2 * t + 1, t), (3, 0, sgn * (H / 2 + 0.5 + t / 2)), body, 0.3))
        objs.append(fr.box(f"{name}_sy{sgn}", (6, t, H + 1), (3, sgn * (W / 2 + 0.5 + t / 2), 0), body, 0.3))
    objs.append(fr.box(f"{name}_label", (24, 40, 0.2), (-22, 0, 15.05),
                       principled("label", (0.86, 0.86, 0.84), rough=0.6), 0.05))
    txt = floor_text(f"{name}_txt", label, fr.p(-22, 0, 15.2), 5.0)
    return objs + [txt]


def floor_text(name, body, at_mm, size_mm, rot=0.0, mat=None):
    cu = bpy.data.curves.new(name, "FONT")
    cu.body = body
    cu.size = size_mm * MM
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    o = bpy.data.objects.new(name, cu)
    o.location = v(*at_mm)
    o.rotation_euler = (0, 0, math.radians(rot))
    o.data.materials.append(mat or mats()["ink"])
    bpy.context.scene.collection.objects.link(o)
    return o


def vehicle_harness(veh):
    """canode's J2 loom running to a T-harness that sits between a module and its factory
    connector. CAN H/L from the factory side go to CAN1, the module side's to CAN2; every
    other pin passes straight through; +12 V and GND are taken from the same connector."""
    spec = VEHICLES[veh]
    body = principled(f"{veh} housing", spec["body"], rough=0.45)
    lock = principled(f"{veh} lock", spec["lock_col"], rough=0.4)
    W, H = conn_size(spec)
    fl = Z_BOT
    X0 = -25.0
    zc_mod = fl + 15.0
    objs = []
    # module, with the adapter's receptacle plugged into its header
    objs += module_box("module", Frame(X0, -182.0, zc_mod, 90), spec, spec["module"])
    o, rear_m = oem_connector("adapter_mod", Frame(X0, -182.0, zc_mod, -90), spec, "f", body, lock)
    objs += o
    # adapter's inline header that the factory connector plugs into
    zc_hdr = fl + H / 2 + 2.6
    o, rear_h = oem_connector("adapter_hdr", Frame(X0, -62.0, zc_hdr, 90), spec, "m", body, lock)
    objs += o
    # factory connector, unplugged from the module and pulled back from the adapter
    o, rear_f = oem_connector("factory", Frame(X0, -46.0, zc_hdr, -90), spec, "f", body, lock)
    objs += o
    # splice (heat-shrink) where canode's loom joins the two legs
    sp = (X0, -118.0, fl + 5.0)
    objs.append(rounded_box("splice", (11 * MM, 26 * MM, 10 * MM), 4.5 * MM, mats()["pvc_black"], v(*sp)))
    leg = mats()["sleeve"]
    objs.append(curve_obj("leg_hdr", [v(*rear_h), v(rear_h[0], rear_h[1] - 8, fl + 5.5),
                                      v(sp[0], sp[1] + 13, sp[2])], 3.0 * MM, leg))
    objs.append(curve_obj("leg_mod", [v(*rear_m), v(rear_m[0], rear_m[1] + 9, fl + 9),
                                      v(sp[0], sp[1] - 13, sp[2])], 3.0 * MM, leg))
    factory_loom = curve_obj("factory_loom", [v(*rear_f), v(rear_f[0], rear_f[1] + 16, fl + 7),
                                              v(X0 - 30, 18, fl + 6.5), v(X0 - 120, 50, fl + 6.5), v(X0 - 260, 90, fl + 6.5)],
                             5.0 * MM, mats()["pvc_black"])
    # canode's J2 loom: up out of the plug, then down to the floor and into the splice
    loom = [(60.0, -116.0, 30.0), (30.0, -117.0, fl + 7.0), (X0 + 5.5, sp[1], sp[2])]
    objs += harness(loom=loom)
    # labels on the floor
    objs.append(floor_text("lbl_factory", "factory connector", (X0 + 48, -40, fl + 0.05), 7.0))
    objs.append(floor_text("lbl_header", "adapter", (X0 + 34, -76, fl + 0.05), 7.0))
    objs.append(floor_text("lbl_adapter", "per-vehicle T-harness", (X0 + 62, -136, fl + 0.05), 7.0))
    objs.append(floor_text("lbl_module", "adapter into module", (X0 + 80, -186, fl + 0.05), 7.0))
    objs.append(floor_text("lbl_title", spec["title"], (60, -236, fl + 0.05), 7.5))
    return objs, factory_loom


# ----------------------------------------------------------------------------- stage
def stage(floor_z):
    sc = bpy.context.scene
    world = bpy.data.worlds.new("studio")
    sc.world = world
    world.use_nodes = True
    nt = world.node_tree
    bg = nt.nodes["Background"]
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    hdri = Path(bpy.utils.system_resource("DATAFILES")) / "studiolights/world/studio.exr"
    if hdri.exists():
        env.image = bpy.data.images.load(str(hdri))
        nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.25 * LIGHT_SCALE
    # camera rays see a plain light-grey studio instead of the HDRI
    lp = nt.nodes.new("ShaderNodeLightPath")
    plain = nt.nodes.new("ShaderNodeBackground")
    plain.inputs["Color"].default_value = (0.78, 0.78, 0.77, 1)
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs["Fac"])
    nt.links.new(bg.outputs["Background"], mix.inputs[1])
    nt.links.new(plain.outputs["Background"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], nt.nodes["World Output"].inputs["Surface"])

    bpy.ops.mesh.primitive_plane_add(size=4.0, location=(0.14, -0.12, floor_z))
    fl = bpy.context.active_object
    fl.name = "floor"
    fl.data.materials.append(mats()["floor"])

    def area(name, loc, size, energy, color=(1, 1, 1)):
        ld = bpy.data.lights.new(name, "AREA")
        ld.size = size
        ld.energy = energy
        ld.color = color
        o = bpy.data.objects.new(name, ld)
        o.location = loc
        sc.collection.objects.link(o)
        d = Vector((0.1425, -0.125, 0.0)) - Vector(loc)
        o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        return o

    k = LIGHT_SCALE
    area("key", (0.02, -0.33, 0.30), 0.30, 5.0 * k, (1.0, 0.97, 0.93))
    area("fill", (0.42, -0.30, 0.10), 0.35, 1.4 * k, (0.92, 0.95, 1.0))
    area("rim", (-0.06, 0.16, 0.08), 0.25, 2.5 * k)    # low, behind-left: no specular hotspot on the mask
    area("top", (0.30, 0.05, 0.45), 0.5, 1.0 * k)


def look_at(cam, target):
    d = target - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def fit_camera(objs, direction, lens=85.0, margin=1.08, ortho=False, aspect=1.6, target_shift=(0, 0, 0)):
    pts = []
    dg = bpy.context.evaluated_depsgraph_get()
    for o in objs:
        if o.type not in ("MESH", "CURVE", "FONT"):
            continue
        eo = o.evaluated_get(dg)
        for c in eo.bound_box:
            pts.append(eo.matrix_world @ Vector(c))
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    center = (lo + hi) / 2 + Vector(target_shift)
    d = Vector(direction).normalized()
    cd = bpy.data.cameras.new("cam")
    cam = bpy.data.objects.new("cam", cd)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    cam.location = center + d
    look_at(cam, center)
    bpy.context.view_layer.update()
    # project bbox corners into camera space to size the shot
    inv = cam.matrix_world.inverted()
    corners = [Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
    cs = [inv @ c for c in corners]
    if ortho:
        cd.type = "ORTHO"
        w = max(c.x for c in cs) - min(c.x for c in cs)
        h = max(c.y for c in cs) - min(c.y for c in cs)
        cd.ortho_scale = max(w, h * aspect) * margin
        cam.location = center + d * 1.0
        cd.clip_end = 5
        return cam
    cd.lens = lens
    cd.sensor_width = 36
    fov_x = 2 * math.atan(18 / lens)
    fov_y = 2 * math.atan(18 / aspect / lens)
    # distance so every corner fits
    dist = 0.0
    for c in corners:
        rel = c - center
        # components along camera axes (no translation)
        r = cam.matrix_world.to_3x3().inverted() @ rel
        need_x = abs(r.x) / math.tan(fov_x / 2) + r.z
        need_y = abs(r.y) / math.tan(fov_y / 2) + r.z
        dist = max(dist, need_x, need_y)
    cam.location = center + d * dist * margin
    cd.clip_start = 0.005
    cd.clip_end = 10
    # gentle depth of field on the focus point
    cd.dof.use_dof = True
    cd.dof.focus_distance = (cam.location - center).length
    cd.dof.aperture_fstop = 28.0
    return cam


def render(path, samples=160):
    w, h = RES
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    try:
        prefs.compute_device_type = "METAL"
        prefs.get_devices()
        for dvc in prefs.devices:
            dvc.use = True
        sc.cycles.device = "GPU"
    except Exception:
        sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    sc.cycles.max_bounces = 8
    sc.cycles.transparent_max_bounces = 16
    sc.render.resolution_x, sc.render.resolution_y = w, h
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = False
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    try:
        sc.view_settings.view_transform = "AgX"
        sc.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        pass
    sc.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    print(f"RENDERED {path}")


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    MATS.clear()


def move(objs, dz=0.0, dx=0.0, dy=0.0):
    for o in objs:
        o.location += v(dx, dy, dz)


def all_meshes():
    return [o for o in bpy.data.objects if o.type in ("MESH", "CURVE", "FONT") and o.name != "floor"]


# ----------------------------------------------------------------------------- scenes
def sc_board_hero(out, samples):
    reset()
    import_board()
    set_leds({"D4": True, "D5": True})
    stage(floor_z=-1.45 * MM)
    fit_camera(all_meshes(), (0.42, -1.0, 0.78), lens=70, margin=1.12)
    render(out / "board_hero.png", samples=samples)


def sc_enc_closed(out, samples):
    reset()
    import_board()
    import_stl("base", mats()["mjf"])
    import_stl("lid", mats()["mjf"])
    import_stl("plug", mats()["black_nylon"])
    harness()
    usb_cable()
    for i, (x, y) in enumerate((H1, H2)):
        screw(x, y, Z_TOP - 1.8, f"screw{i}")
    light_pipes()
    stage(floor_z=Z_BOT * MM)
    frame = [bpy.data.objects[n] for n in ("base", "lid", "plug", "usb_overmold")]
    fit_camera(frame, (0.55, -1.0, 0.85), lens=60, margin=1.25, target_shift=(-0.004, 0, 0.004))
    render(out / "enclosure_closed.png", samples=samples)


def sc_enc_exploded(out, samples):
    reset()
    board = import_board()
    base = import_stl("base", mats()["mjf"])
    lid = import_stl("lid", mats()["mjf"])
    set_leds({"D4": True})
    ins = [insert(x, y, 0.0, f"insert{i}") for i, (x, y) in enumerate((H1, H2))]
    scr = []
    for i, (x, y) in enumerate((H1, H2)):
        scr += screw(x, y, Z_TOP - 1.8, f"screw{i}")
    board.location.z += 22 * MM
    move(ins, dz=7)
    lid.location.z += 52 * MM
    move(scr, dz=78)
    stage(floor_z=Z_BOT * MM)
    fit_camera([base, lid] + scr, (0.75, -1.0, 0.95), lens=55, margin=1.05)
    render(out / "enclosure_exploded.png", samples=samples)


def sc_enc_open(out, samples):
    reset()
    import_board()
    base = import_stl("base", mats()["mjf"])
    lid = import_stl("lid", mats()["mjf"])
    set_leds({"D4": True, "D5": True, "D6": True})
    # lid flipped over and set down behind the base, showing the light guides and poke tubes
    lid.rotation_euler = (math.pi, 0, 0)
    bpy.context.view_layer.update()
    lid.location = (0, 2 * -0.125 + 0.068, (Z_TOP + Z_BOT) * MM)
    stage(floor_z=Z_BOT * MM)
    fit_camera([base, lid], (0.35, -1.0, 1.25), lens=55, margin=1.06)
    render(out / "enclosure_open.png", samples=samples)


def sc_enc_top(out, samples):
    reset()
    import_board()
    import_stl("base", mats()["mjf"])
    import_stl("lid", mats()["mjf"])
    import_stl("plug", mats()["black_nylon"])
    harness()
    light_pipes()
    for i, (x, y) in enumerate((H1, H2)):
        screw(x, y, Z_TOP - 1.8, f"screw{i}")
    r = ruler(84.0, -164.0, 140)
    stage(floor_z=Z_BOT * MM)
    frame = [bpy.data.objects[n] for n in ("base", "lid")] + r
    fit_camera(frame, (0.0, -0.0001, 1.0), ortho=True, margin=1.12)
    render(out / "enclosure_top.png", samples=samples)


def sc_vehicle(veh):
    def run(out, samples):
        reset()
        import_board()
        set_leds({"D4": True, "D5": True})
        import_stl("base", mats()["mjf"])
        import_stl("lid", mats()["mjf"])
        import_stl("plug", mats()["black_nylon"])
        for i, (x, y) in enumerate((H1, H2)):
            screw(x, y, Z_TOP - 1.8, f"screw{i}")
        light_pipes()
        objs, _factory_loom = vehicle_harness(veh)
        stage(floor_z=Z_BOT * MM)
        frame = [bpy.data.objects[n] for n in ("base", "lid", "plug")] + \
                [o for o in objs if o.type in ("MESH", "FONT")]
        fit_camera(frame, (0.30, -1.0, 1.05), lens=50, margin=1.0)
        render(out / f"vehicle_{veh}.png", samples=samples)
    return run


SCENES = {"board_hero": sc_board_hero, "enc_closed": sc_enc_closed,
          "enc_exploded": sc_enc_exploded, "enc_open": sc_enc_open, "enc_top": sc_enc_top,
          "veh_ford": sc_vehicle("ford"), "veh_gm": sc_vehicle("gm"), "veh_bmw": sc_vehicle("bmw")}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "build/renders/raw"))
    ap.add_argument("--samples", type=int, default=160)
    ap.add_argument("--scenes", default=",".join(SCENES))
    ap.add_argument("--res", default="1600x1000", help="WxH (use 800x500 for previews)")
    ap.add_argument("--light", type=float, default=1.0)
    a = ap.parse_args(argv)
    global LIGHT_SCALE, RES
    LIGHT_SCALE = a.light
    RES = tuple(int(x) for x in a.res.split("x"))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for name in a.scenes.split(","):
        SCENES[name](out, a.samples)


main()
