#!/bin/sh
# Regenerates everything from design.py + layout.py (KiCad 7+ python, Java 21, freerouting.jar).
# NOTE: re-running this re-autoroutes and overwrites any hand edits in the .kicad_pcb.
set -e
K=../kicad
python3 gen_sch.py $K/canode.kicad_sch
python3 gen_pcb.py $K/canode_unrouted.kicad_pcb $K/canode.kicad_sch.json
python3 route_loop.py $K/canode_unrouted.kicad_pcb $K/canode_routed.kicad_pcb   # expects freerouting.jar path inside
python3 stitch.py $K/canode_routed.kicad_pcb $K/canode_routed.kicad_pcb
python3 post.py $K/canode_routed.kicad_pcb $K/canode.kicad_pcb
