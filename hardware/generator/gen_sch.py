import uuid, sys, copy
from sexp import parse, dump, Sym, find, find1
from libs import get_symbol, pins as sym_pins
import design

S = Sym
PROJECT = "canode"
ROOT = str(uuid.uuid5(uuid.NAMESPACE_URL, "canode-root"))
_ctr = [0]
def uid(tag=None):
    _ctr[0] += 1
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"canode-{tag or _ctr[0]}"))

TPS = parse('''
(symbol "TPS7B6933" (pin_names (offset 0.254)) (in_bom yes) (on_board yes)
  (property "Reference" "U" (at -5.08 3.81 0) (effects (font (size 1.27 1.27)) (justify left)))
  (property "Value" "TPS7B6933" (at 0 3.81 0) (effects (font (size 1.27 1.27)) (justify left)))
  (property "Footprint" "Package_TO_SOT_SMD:SOT-223-3_TabPin2" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))
  (property "Datasheet" "https://www.ti.com/lit/ds/symlink/tps7b69-q1.pdf" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))
  (property "ki_description" "150mA 40V automotive LDO, 3.3V fixed, 15uA Iq, SOT-223" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))
  (symbol "TPS7B6933_0_1"
    (rectangle (start -5.08 2.54) (end 5.08 -5.08) (stroke (width 0.254) (type default)) (fill (type background))))
  (symbol "TPS7B6933_1_1"
    (pin power_in line (at -7.62 0 0) (length 2.54) (name "IN" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
    (pin power_in line (at 0 -7.62 90) (length 2.54) (name "GND" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27)))))
    (pin power_out line (at 7.62 0 180) (length 2.54) (name "OUT" (effects (font (size 1.27 1.27)))) (number "3" (effects (font (size 1.27 1.27)))))))
''')[0]

def load_symbol(lib_id):
    lib, name = lib_id.split(":")
    if lib == "canode":
        return copy.deepcopy(TPS)
    return get_symbol(lib, name)

def font(size=1.27, hide=False, justify=None, bold=False):
    f = [S("font"), [S("size"), size, size]]
    if bold: f.append(S("bold"))
    e = [S("effects"), f]
    if justify: e.append([S("justify")] + [S(j) for j in justify.split()])
    if hide: e.append(S("hide"))
    return e

def r2(v): return round(v * 100) / 100

def build():
    items = []
    lib_syms = {}
    pin_nets = {}   # endpoint -> net (to detect collisions)
    netlist = {}    # ref -> {pin: net}
    for p in design.PARTS:
        lib_id = p["lib"]
        if lib_id not in lib_syms:
            s = load_symbol(lib_id)
            s[1] = lib_id
            lib_syms[lib_id] = s
        sym = lib_syms[lib_id]
        X, Y = p["sch"]
        is_power = p["ref"].startswith("#")
        props = []
        def lib_prop(name):
            for e in find(sym, "property"):
                if e[1] == name:
                    at = find1(e, "at"); eff = find1(e, "effects")
                    j = find1(eff, "justify") if eff else None
                    return (r2(X + float(at[1])), r2(Y - float(at[2])), float(at[3]) if len(at) > 3 else 0,
                            " ".join(str(x) for x in j[1:]) if j else None)
            return (X, Y, 0, None)
        rx, ry, ra, rj = lib_prop("Reference")
        vx, vy, va, vj = lib_prop("Value")
        props.append([S("property"), "Reference", p["ref"], [S("at"), rx, ry, ra],
                      font(justify=rj, hide=is_power)])
        props.append([S("property"), "Value", p["value"], [S("at"), vx, vy, va],
                      font(justify=vj)])
        props.append([S("property"), "Footprint", p["fp"], [S("at"), X, Y, 0], font(hide=True)])
        ds = find1(sym, "property")
        dsv = [e for e in find(sym, "property") if e[1] == "Datasheet"]
        props.append([S("property"), "Datasheet", dsv[0][2] if dsv else "~", [S("at"), X, Y, 0], font(hide=True)])
        if not is_power:
            props.append([S("property"), "LCSC", p["lcsc"], [S("at"), X, Y, 0], font(hide=True)])
            props.append([S("property"), "MPN", p["mpn"], [S("at"), X, Y, 0], font(hide=True)])
            if not p["jlc"]:
                props.append([S("property"), "JLC", "hand-solder / not assembled", [S("at"), X, Y, 0], font(hide=True)])
        spins = sym_pins(sym)
        su = str(uid(f"sym-{p['ref']}"))
        p["uuid"] = su
        inst = [S("symbol"), [S("lib_id"), lib_id], [S("at"), X, Y, 0], [S("unit"), 1],
                [S("in_bom"), S("no" if is_power or not p["mpn"] else "yes")],
                [S("on_board"), S("no" if is_power else "yes")],
                [S("dnp"), S("yes" if p["dnp"] else "no")], [S("uuid"), su]] + props
        for sp in spins:
            inst.append([S("pin"), sp["number"], [S("uuid"), uid(f"pin-{p['ref']}-{sp['number']}")]])
        inst.append([S("instances"), [S("project"), PROJECT, [S("path"), "/" + ROOT,
                      [S("reference"), p["ref"]], [S("unit"), 1]]]])
        items.append(inst)
        # wires + labels / no-connects
        nets = p["nets"]
        netlist[p["ref"]] = {}
        seen = set()
        from collections import Counter
        vert_multi = Counter()
        for sp in spins:
            if sp["number"] in nets:
                vert_multi[{0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}[sp["angle"]]] += 1
        for sp in spins:
            ex, ey = r2(X + sp["x"]), r2(Y - sp["y"])
            a = sp["angle"]
            dx, dy = {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}[a]
            net = nets.get(sp["number"])
            if net is None:
                if p["nets"] and not is_power:
                    key = (ex, ey, "NC")
                    if key not in seen:
                        seen.add(key)
                        items.append([S("no_connect"), [S("at"), ex, ey], [S("uuid"), uid()]])
                continue
            netlist[p["ref"]][sp["number"]] = net
            prev = pin_nets.get((ex, ey))
            if prev and prev != net:
                raise SystemExit(f"pin collision at {(ex, ey)} {prev} vs {net} ({p['ref']}.{sp['number']})")
            pin_nets[(ex, ey)] = net
            key = (ex, ey, net)
            if key in seen: continue
            seen.add(key)
            L = 2.54
            lx, ly = r2(ex + dx * L), r2(ey + dy * L)
            items.append([S("wire"), [S("pts"), [S("xy"), ex, ey], [S("xy"), lx, ly]],
                          [S("stroke"), [S("width"), 0], [S("type"), S("default")]], [S("uuid"), uid()]])
            if dy != 0 and vert_multi.get((dx, dy), 0) > 1:
                ang, just = (90, "left bottom") if dy < 0 else (270, "right bottom")
            else:
                ang, just = (180, "right bottom") if dx < 0 else (0, "left bottom")
            items.append([S("label"), net, [S("at"), lx, ly, ang], [S("fields_autoplaced")],
                          font(justify=just), [S("uuid"), uid()]])
    # check nets referencing nonexistent pins
    for p in design.PARTS:
        sp = {x["number"] for x in sym_pins(lib_syms[p["lib"]])}
        bad = set(p["nets"]) - sp
        if bad: raise SystemExit(f"{p['ref']}: nets on unknown pins {bad}")
    for (x, y), t in design.NOTES:
        items.append([S("text"), t, [S("at"), x, y, 0], font(size=2.0, bold=True, justify="left bottom"),
                      [S("uuid"), uid()]])
    sch = [S("kicad_sch"), [S("version"), 20230121], [S("generator"), S("eeschema")], [S("uuid"), ROOT],
           [S("paper"), "A3"],
           [S("title_block"), [S("title"), "CAN node - dual FDCAN vehicle interface"], [S("date"), "2026-11-09"],
            [S("rev"), "A"], [S("company"), "prototype - review before ordering"],
            [S("comment"), 1, "Generated by gen_sch.py; nets are connected by local labels"],
            [S("comment"), 2, "JLC Economic PCBA: all SMD top side; J2-J5 + JP1/JP2 hand-finished"]],
           [S("lib_symbols")] + list(lib_syms.values())] + items + \
          [[S("sheet_instances"), [S("path"), "/", [S("page"), "1"]]]]
    return sch, netlist

if __name__ == "__main__":
    out = sys.argv[1]
    sch, netlist = build()
    open(out, "w").write(dump(sch) + "\n")
    import json
    json.dump({"netlist": netlist, "uuids": {p["ref"]: p["uuid"] for p in design.PARTS}},
              open(out + ".json", "w"), indent=1)
    print("ok", len(design.PARTS), "parts")
