"""Crop, resize and compress raw renders into hardware/docs/renders/.

usage: postprocess.py RAW_DIR OUT_DIR
Transparent KiCad renders are trimmed to the board plus a margin; everything is
scaled to 1600 px wide, then squeezed with pngquant/oxipng when available.
"""
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

WIDTH = 1600
# raw name -> published name
NAMES = {
    "board_hero.png": "canode_board_3d.png",
    "board_top.png": "canode_board_top.png",
    "board_bottom.png": "canode_board_bottom.png",
    "board_iso_kicad.png": "canode_board_iso_kicad.png",
    "enclosure_closed.png": "canode_enclosure_closed.png",
    "enclosure_exploded.png": "canode_enclosure_exploded.png",
    "enclosure_open.png": "canode_enclosure_open.png",
    "enclosure_top.png": "canode_enclosure_top_scale.png",
    "vehicle_ford.png": "canode_vehicle_ford.png",
    "vehicle_gm.png": "canode_vehicle_gm.png",
    "vehicle_bmw.png": "canode_vehicle_bmw.png",
}


def process(src: Path, dst: Path):
    im = Image.open(src)
    if im.mode == "RGBA":
        bbox = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
        if bbox:
            pad = int(0.04 * (bbox[2] - bbox[0]))
            bbox = (max(bbox[0] - pad, 0), max(bbox[1] - pad, 0),
                    min(bbox[2] + pad, im.width), min(bbox[3] + pad, im.height))
            im = im.crop(bbox)
    if im.width != WIDTH:
        im = im.resize((WIDTH, round(im.height * WIDTH / im.width)), Image.LANCZOS)
    im.save(dst, optimize=True)
    if shutil.which("pngquant"):
        subprocess.run(["pngquant", "--force", "--skip-if-larger", "--quality", "70-95",
                        "--speed", "1", "--output", str(dst), str(dst)], check=False)
    if shutil.which("oxipng"):
        subprocess.run(["oxipng", "-q", "-o", "4", "--strip", "safe", str(dst)], check=False)
    print(f"{dst}  {dst.stat().st_size // 1024} KB  {im.width}x{im.height}")


def main():
    raw, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    for src_name, dst_name in NAMES.items():
        src = raw / src_name
        if src.exists():
            process(src, out / dst_name)


if __name__ == "__main__":
    main()
