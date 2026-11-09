#!/usr/bin/env python3
"""Make a render-only copy of the board with working 3D-model paths.

The board was generated with KiCad 7, so its footprints point at
  ${KICAD6_3DMODEL_DIR}/... .wrl  and  ${KICAD7_3DMODEL_DIR}/... .wrl
KiCad 10 defines neither variable and its library ships only .step files.
Three footprints (J1, J2, SW1/SW2) have no model in KiCad's library at all;
for those we use the stand-ins in hardware/3dmodels/.

This never touches hardware/kicad/*. It writes build/renders/board/canode.kicad_pcb.
Stdlib only.
"""
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "hardware" / "kicad"
LOCAL = ROOT / "hardware" / "3dmodels"
DST = ROOT / "build" / "renders" / "board"

LOCAL_MODELS = {
    "Molex_Micro-Fit_3.0_43045-1212_2x06_P3.00mm_Vertical",
    "USB_C_Receptacle_HRO_TYPE-C-31-M-12",
    "SW_Push_1P1T_XKB_TS-1187A",
}

MODEL_RE = re.compile(r'\(model "\$\{KICAD\d+_3DMODEL_DIR\}/([^"]+?)\.(?:wrl|step|stp)"')


def fix(m):
    rel = m.group(1)                      # e.g. Package_SO.3dshapes/SOIC-8_...
    name = rel.split("/")[-1]
    if name in LOCAL_MODELS:
        return f'(model "{LOCAL / name}.step"'
    return f'(model "${{KICAD10_3DMODEL_DIR}}/{rel}.step"'


def main():
    DST.mkdir(parents=True, exist_ok=True)
    text = (SRC / "canode.kicad_pcb").read_text()
    new, n = MODEL_RE.subn(fix, text)
    # project-relative models (e.g. after the board file points at hardware/3dmodels/):
    # the copy lives in build/, so make ${KIPRJMOD} paths absolute
    new, n2 = re.subn(r'\(model "\$\{KIPRJMOD\}/', f'(model "{SRC}/', new)
    n += n2
    (DST / "canode.kicad_pcb").write_text(new)
    shutil.copy(SRC / "canode.kicad_pro", DST / "canode.kicad_pro")
    missing = [n for n in LOCAL_MODELS if not (LOCAL / f"{n}.step").exists()]
    if missing:
        sys.exit(f"missing local models {missing}: run hardware/3dmodels/make_models.py")
    print(f"prep_board: rewrote {n} model paths -> {DST / 'canode.kicad_pcb'}")


if __name__ == "__main__":
    main()
