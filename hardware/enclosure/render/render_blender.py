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


def harness(lift=0.0):
    """Eight wires out of the Micro-Fit plug, gathered into a loom heading off to -X."""
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
    loom = [v(cx - 21, cy, PLUG_TOP + 28.6 + lift), v(cx - 45, cy + 3, PLUG_TOP + 31 + lift),
            v(cx - 85, cy + 14, PLUG_TOP + 27 + lift), v(cx - 140, cy + 30, PLUG_TOP + 18 + lift)]
    objs.append(curve_obj("loom", loom, 4.2 * MM, mats()["sleeve"]))
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


SCENES = {"board_hero": sc_board_hero, "enc_closed": sc_enc_closed,
          "enc_exploded": sc_enc_exploded, "enc_open": sc_enc_open, "enc_top": sc_enc_top}


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
