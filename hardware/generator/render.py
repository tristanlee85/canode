from paths import TMP, GEN, FREEROUTING_JAR
import subprocess, sys
pcb, png = sys.argv[1], sys.argv[2]
layers = sys.argv[3] if len(sys.argv) > 3 else "F.Cu,B.Cu,F.SilkS,F.Fab,Edge.Cuts,F.CrtYd"
subprocess.run(["kicad-cli","pcb","export","svg","--layers",layers,"--exclude-drawing-sheet","--page-size-mode","2","-o",f"{TMP}/r.svg",pcb],check=True,capture_output=True)
import cairosvg
cairosvg.svg2png(url=f"{TMP}/r.svg", write_to=png, output_width=1600, background_color="white")
