import re, sys
src, dst = sys.argv[1], sys.argv[2]
t = open(src).read()
classes = {"power": (["VBAT_IN", "VBATF", "VIN", "VBUS", "AUX_OUT"], 500, 200),
           "supply": (["+3V3", "GND"], 300, 150)}
m = re.search(r'\(class kicad_default ""(.*?)\(circuit', t, re.S)
names = m.group(1).split()
moved = {n for v in classes.values() for n in v[0]}
keep = [n for n in names if n not in moved]
new_default = '(class kicad_default "" ' + " ".join(keep) + "\n      (circuit"
t = t[:m.start()] + new_default + t[m.end():]
extra = ""
for cname, (nets, w, c) in classes.items():
    extra += f"""    (class {cname} {" ".join(nets)}
      (circuit
        (use_via Via[0-1]_600:300_um)
      )
      (rule
        (width {w})
        (clearance {c})
      )
    )
"""
i = t.index("(class kicad_default")
t = t[:i] + extra.lstrip() + "    " + t[i:]
open(dst, "w").write(t)
print("ok")
