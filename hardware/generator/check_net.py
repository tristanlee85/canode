import sys, json
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from sexp import parse, find, find1
import design
net = parse(open(sys.argv[1]).read())[0]
kn = {}
for n in find(find1(net, "nets"), "net"):
    name = find1(n, "name")[1].lstrip("/")
    for node in find(n, "node"):
        ref = find1(node, "ref")[1]; pin = find1(node, "pin")[1]
        kn[(ref, pin)] = name
want = {}
for p in design.PARTS:
    if p["ref"].startswith("#"): continue
    for pin, n in p["nets"].items(): want[(p["ref"], pin)] = n
errs = 0
for k, v in want.items():
    got = kn.get(k)
    if got != v: print("MISMATCH", k, "want", v, "got", got); errs += 1
for k, v in kn.items():
    if k[0].startswith("#"): continue
    if k not in want and not v.startswith("unconnected-"): print("EXTRA", k, v); errs += 1
# single-pin nets
from collections import Counter
c = Counter(v for k, v in want.items())
for n, cnt in c.items():
    if cnt < 2: print("SINGLE-PIN NET", n); errs += 1
comps = find(find1(net, "components"), "comp")
print(len(comps), "components;", len(set(want.values())), "nets;", errs, "errors")
