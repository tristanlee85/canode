#!/usr/bin/env bash
# Regenerate every board + enclosure render into hardware/docs/renders/.
#
#   hardware/enclosure/render/build_renders.sh            # everything (~10-15 min on an M1 Pro)
#   STAGES=board   hardware/enclosure/render/build_renders.sh   # KiCad renders + board_hero only
#   SAMPLES=64     ...                                     # faster, noisier Blender renders
#
# Needs: kicad-cli (KiCad 10), blender (4.2+), uv, pngquant + oxipng (optional, for size).
# Never touches hardware/kicad/*; intermediates go to build/renders/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

KICAD_CLI="${KICAD_CLI:-$(command -v kicad-cli || echo /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli)}"
BLENDER="${BLENDER:-$(command -v blender || echo /Applications/Blender.app/Contents/MacOS/Blender)}"
SAMPLES="${SAMPLES:-160}"
STAGES="${STAGES:-all}"            # all | board
ENC=hardware/enclosure
EPY="$ENC/.venv/bin/python"
B=build/renders/board
RAW=build/renders/raw
OUT=hardware/docs/renders
mkdir -p "$B" "$RAW" "$OUT"

# 0. python env for build123d (separate from the repo .venv, which is Python 3.9)
if [ ! -x "$EPY" ]; then
  uv venv --python 3.12 "$ENC/.venv"
  uv pip install --python "$EPY" -r "$ENC/requirements.txt"
fi

# 1. stand-in models for parts KiCad's 3D library lacks (J1, J2, SW1/2, mating plug)
for m in Molex_Micro-Fit_3.0_43045-0812_2x04_P3.00mm_Vertical USB_C_Receptacle_HRO_TYPE-C-31-M-12 \
         SW_Push_1P1T_XKB_TS-1187A Molex_Micro-Fit_3.0_43025-0800_plug_mated; do
  [ -f "hardware/3dmodels/$m.step" ] || { "$EPY" hardware/3dmodels/make_models.py; break; }
done

# 2. render-only board copy with working model paths, then GLB (Blender) + STEP (fit check)
python3 "$ENC/render/prep_board.py"
"$KICAD_CLI" pcb export glb -f --subst-models --include-tracks --include-pads --include-zones \
  --include-silkscreen --include-soldermask -o "$B/canode.glb" "$B/canode.kicad_pcb" >/dev/null
"$KICAD_CLI" pcb export step -f --subst-models -o "$B/canode.step" "$B/canode.kicad_pcb" >/dev/null

# 3. KiCad raytraced views (transparent background)
KR=("$KICAD_CLI" pcb render -w 2000 -h 1250)
"${KR[@]}" --side top    --quality user -o "$RAW/board_top.png"    "$B/canode.kicad_pcb" >/dev/null
"${KR[@]}" --side bottom --quality user -o "$RAW/board_bottom.png" "$B/canode.kicad_pcb" >/dev/null
"${KR[@]}" --quality high --perspective --rotate '-55,0,-30' --zoom 0.95 \
  -o "$RAW/board_iso_kicad.png" "$B/canode.kicad_pcb" >/dev/null

# 4. enclosure solids + interference check against the populated board and mated plug
if [ "$STAGES" = all ]; then
  "$EPY" "$ENC/enclosure.py" --check
  SCENES="${SCENES:-board_hero,enc_closed,enc_exploded,enc_open,enc_top,veh_ford,veh_gm,veh_bmw}"
else
  [ -f build/renders/enclosure/base.stl ] || "$EPY" "$ENC/enclosure.py"
  SCENES="${SCENES:-board_hero}"
fi

# 5. Blender (Cycles) scenes
"$BLENDER" -b --factory-startup -P "$ENC/render/render_blender.py" -- \
  --out "$RAW" --samples "$SAMPLES" --scenes "$SCENES" 2>&1 | grep -E "RENDERED|Error|Traceback" || true

# 6. crop / resize / compress into the docs folder
"$EPY" "$ENC/render/postprocess.py" "$RAW" "$OUT"
