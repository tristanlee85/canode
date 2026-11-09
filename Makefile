# Validation + fab targets. Needs KiCad 8 or 9 for erc/drc (kicad-cli 7 has no ERC/DRC).
# macOS: kicad-cli lives inside the app bundle; override with `make KICAD_CLI=/path/to/kicad-cli`.
KICAD_CLI ?= $(shell command -v kicad-cli 2>/dev/null || echo /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli)
PY        ?= python3
SCH       := hardware/kicad/canode.kicad_sch
PCB       := hardware/kicad/canode.kicad_pcb
BUILD     := build

.PHONY: check pins erc drc fab test-tools clean
check: pins erc drc            ## everything that needs no hardware

pins:                          ## MCU pinout vs ST official pin data
	$(PY) validation/check_pins.py

erc:                           ## schematic electrical rules
	@mkdir -p $(BUILD)
	$(KICAD_CLI) sch erc --severity-all --format report -o $(BUILD)/erc.rpt $(SCH) || true
	$(KICAD_CLI) sch erc --severity-error --exit-code-violations --format json -o $(BUILD)/erc.json $(SCH)

drc:                           ## board design rules + schematic/board parity
	@mkdir -p $(BUILD)
	$(KICAD_CLI) pcb drc --severity-all --schematic-parity --format report -o $(BUILD)/drc.rpt $(PCB) || true
	$(KICAD_CLI) pcb drc --severity-error --schematic-parity --exit-code-violations --format json -o $(BUILD)/drc.json $(PCB)

fab:                           ## JLC gerbers/BOM/CPL into build/fab
	$(PY) hardware/scripts/jlc_fab.py --kicad-cli "$(KICAD_CLI)"

test-tools:                    ## offline tests for tools/canlog
	$(PY) tools/canlog/tests/test_canlog.py

clean:
	rm -rf $(BUILD)
