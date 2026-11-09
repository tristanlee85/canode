from paths import TMP, GEN, FREEROUTING_JAR
import sys, subprocess, os
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
import pcbnew
from ses_import import import_ses, add_gnd_zones
import layout
src, out = sys.argv[1], sys.argv[2]
b = pcbnew.LoadBoard(src)
for it in range(6):
    pcbnew.ExportSpecctraDSN(b, f"{TMP}/it.dsn")
    subprocess.run([sys.executable, str(GEN / "dsn_rules.py"), f"{TMP}/it.dsn", f"{TMP}/it2.dsn"], check=True)
    if os.path.exists(f"{TMP}/it.ses"): os.remove(f"{TMP}/it.ses")
    subprocess.run(["java", "-jar", str(FREEROUTING_JAR), "--gui.enabled=false",
                    "--router.optimizer.enabled=false", "-de", f"{TMP}/it2.dsn", "-do", f"{TMP}/it.ses",
                    "-mp", "100", "-mt", "1"], stdout=open(f"{TMP}/fr{it}.log", "w"), stderr=subprocess.STDOUT, timeout=1200)
    # remove existing tracks; SES contains the complete wiring (incl. preexisting)
    for t in list(b.GetTracks()): b.Remove(t)
    print("iter", it, "imported", import_ses(b, f"{TMP}/it.ses"))
    b.BuildConnectivity()
    n = b.GetConnectivity().GetUnconnectedCount(True)
    print("  unrouted:", n)
    if n == 0: break
add_gnd_zones(b, layout.W, layout.H)
b.BuildConnectivity()
print("final unrouted (with zones):", b.GetConnectivity().GetUnconnectedCount(True))
b.Save(out)
