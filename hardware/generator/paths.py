"""Machine-specific paths. Override with environment variables."""
import os, sys, tempfile
from pathlib import Path

GEN = Path(__file__).resolve().parent
TMP = Path(os.environ.get("CANODE_TMP", tempfile.gettempdir()))

def _kicad_share():
    if sys.platform == "darwin":
        return Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport")
    if sys.platform == "win32":
        for v in ("9.0", "8.0"):
            p = Path(rf"C:\Program Files\KiCad\{v}\share\kicad")
            if p.exists(): return p
    return Path("/usr/share/kicad")

SYMDIR = Path(os.environ.get("KICAD_SYMBOL_DIR", _kicad_share() / "symbols"))
FPDIR = Path(os.environ.get("KICAD_FOOTPRINT_DIR", _kicad_share() / "footprints"))
FREEROUTING_JAR = Path(os.environ.get("FREEROUTING_JAR", GEN.parent.parent / "tools" / "freerouting" / "freerouting.jar"))
