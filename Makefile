# Validation + fab targets. Project files are KiCad 10 format (KiCad 10.0+ required).
# macOS: kicad-cli lives inside the app bundle; override with `make KICAD_CLI=/path/to/kicad-cli`.
KICAD_CLI ?= $(shell command -v kicad-cli 2>/dev/null || echo /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli)
PY        ?= python3
SCH       := hardware/kicad/canode.kicad_sch
PCB       := hardware/kicad/canode.kicad_pcb
BUILD     := build
FW_BUILD  := firmware/build

.PHONY: check pins erc drc fab sim renders renders-board test-tools firmware firmware-test firmware-clean flash-dfu flash-stlink clean
check: pins erc drc firmware-test test-tools   ## everything that needs no hardware

pins:                          ## MCU pinout vs ST official pin data
	$(PY) validation/check_pins.py

erc:                           ## schematic electrical rules
	@mkdir -p $(BUILD)
	$(KICAD_CLI) sch erc --severity-all --format report -o $(BUILD)/erc.rpt $(SCH) || true
	$(KICAD_CLI) sch erc --severity-error --exit-code-violations --format json -o $(BUILD)/erc.json $(SCH)

drc:                           ## board design rules + schematic/board parity (footprints and pad nets)
	@mkdir -p $(BUILD)
	$(KICAD_CLI) pcb drc --severity-all --schematic-parity --format report -o $(BUILD)/drc.rpt $(PCB) || true
	$(KICAD_CLI) pcb drc --severity-error --schematic-parity --exit-code-violations --format json -o $(BUILD)/drc.json $(PCB)
	$(PY) validation/check_netparity.py --kicad-cli "$(KICAD_CLI)"

fab:                           ## JLC gerbers/BOM/CPL into build/fab
	$(PY) hardware/scripts/jlc_fab.py --kicad-cli "$(KICAD_CLI)"

sim:                           ## analog sims (ngspice) -> validation/sim/out/summary.txt + plots
	$(PY) validation/sim/run_all.py

renders:                       ## board + enclosure renders -> hardware/docs/renders (needs blender, uv; ~8 min)
	KICAD_CLI="$(KICAD_CLI)" hardware/enclosure/render/build_renders.sh

renders-board:                 ## KiCad views + 3D hero only (enclosure shots keep the old board)
	KICAD_CLI="$(KICAD_CLI)" STAGES=board hardware/enclosure/render/build_renders.sh

test-tools:                    ## offline tests for tools/canlog
	$(PY) tools/canlog/tests/test_canlog.py

firmware:                      ## build canode + nucleo images -> firmware/build
	cmake -S firmware -B $(FW_BUILD)
	cmake --build $(FW_BUILD) -j

firmware-test:                 ## host unit tests for firmware/lib
	firmware/test/run_tests.sh

firmware-clean:
	rm -rf $(FW_BUILD)

flash-dfu: firmware            ## canode over USB DFU: blank chip, or run the 'dfu' shell command first
	dfu-util -d 0483:df11 -a 0 -s 0x08000000:leave -D $(FW_BUILD)/canode.bin

flash-stlink: firmware         ## canode over SWD (J3) with an ST-Link
	st-flash --reset write $(FW_BUILD)/canode.bin 0x08000000

clean:
	rm -rf $(BUILD) $(FW_BUILD)
