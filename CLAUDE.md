# CLAUDE.md: canode (dual-CAN vehicle interface)

## What this is
A small STM32G0B1 board with two CAN channels, for sniffing and gatewaying vehicle CAN. Target vehicles: 2021 Bronco Sport (Ford GWM, HS/MS-CAN), 2019 Silverado 3500 (GM), possibly a 2016 BMW F80. It's an inline/MITM node: CAN1 on the car side, CAN2 on the module side. Example use: suppressing auto start-stop or changing body-module behavior.

The owner (T) is a software engineer and mechanic. He has built standalone ECUs before, but last did PCB work with ExpressPCB, so explain modern KiCad steps briefly when you ask him to do something in the GUI.

**Status (2026-11-09):** Rev A passes ERC/DRC and validation steps 1–7 and 9, and is ready to order once J2's pin order and U1's pin-1 mark (JLC preview) are checked. Input protection was updated for the 35 V suppressed load dump (`validation/reports/2026-11-09_protection.md`). U1 is now the STM32G0B1CEU6 (UFQFPN-48). Firmware builds for canode and NUCLEO-G0B1RE; untested on hardware.

## Resume point (updated 2026-11-09)
Work is on branch `rev-a-kicad10` (pushed; not yet merged to `main`, no PR opened). `make check` was clean at the last commit.

Done on this branch: KiCad 10 upgrade, DRC fixes, U1 → STM32G0B1CEU6 (UFQFPN-48, `validation/reports/2026-11-09_u1-qfn.md`), firmware (canode + Nucleo, host tests), ngspice sims, enclosure + renders, input-protection redesign (`validation/reports/2026-11-09_protection.md`), firmware Stop 1 sleep.

Next steps, in order:
1. **T decides: sleep while gatewaying.** Today the board never auto-sleeps once TX/gateway has been enabled since boot (~8–9 mA forever on an always-hot inline install), and wakes into listen-only. Options to discuss: (a) gateway mode allowed to sleep, waking straight back into gateway with the first frame(s) lost; (b) pass-through relay/bypass so the car works while the node sleeps (hardware change); (c) keep as is and power from a switched feed. Code: `firmware/src/sleep.c`, `firmware/lib/power.c`.
2. **Pre-order checks (T, by hand):** J2 Molex 43045 pin order vs the Molex drawing; U1 pin-1 mark and D3 (SMC, new package) orientation in JLC's placement preview.
3. **Order rev A** from `hardware/fab/` (or `make fab` → `build/fab/`). Then open a PR / merge `rev-a-kicad10` → `main` if T wants.
4. **Bench bring-up once boards arrive** (see `validation/README.md` for the full plan): sleep current at J2 (`sleep timeout 5`), wake on each bus at 125k/500k/1M, USB re-enumerates after RESET, `rslisten high` reception at 500k, crank-dip behavior of +3V3.
5. Optional: tidy autorouted crystal/USB traces (ask T first: layout taste); consider a stiffer PTC if one appears at JLC (F1 37.8/40 A Imax in reverse-battery sim).

## Layout
```
hardware/kicad/        KiCad project: SOURCE OF TRUTH (canode.kicad_pro/.kicad_sch/.kicad_pcb)
hardware/fab/          JLC outputs as delivered for rev A (regenerate with `make fab` -> build/fab/)
hardware/docs/         schematic PDF + board renders
hardware/scripts/      jlc_fab.py: gerbers/BOM/CPL from the KiCad files
hardware/generator/    one-shot scripts that created rev A (KiCad 7 Python API). Do NOT re-run
                       build_all.sh unless T asks: it re-autoroutes and overwrites the board.
validation/            check_pins.py + README.md (the validation plan and its status table)
validation/reports/    dated results of each validation step (create as you go)
hardware/enclosure/    build123d enclosure (own Python 3.12 venv via uv) + Blender render pipeline
hardware/3dmodels/     stand-in STEP models for J1, J2, SW1/SW2 and the mating plug
firmware/              CMake + HAL + TinyUSB firmware (canode + NUCLEO-G0B1RE); lib/ is host-tested
validation/sim/        ngspice power-input simulations (vendor models fetched, not committed)
tools/canlog/          terminal CAN logger/diff tool for STN adapters (OBDLink MX+), tests offline
scripts/setup_mac.sh   one-time toolchain install (Homebrew)
```

## Setup
- **Preferred platform: macOS** (Homebrew, native USB for ST-Link/CANable). Run `scripts/setup_mac.sh`, then `source .venv/bin/activate`.
- On Windows, use the KiCad 10 installer plus winget/Python. Everything in the Makefile also works from Git Bash, given `KICAD_CLI="C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"`.
- **KiCad 10** (current stable). The project files are KiCad 10 format (upgraded 2026-11-09), so older KiCad can't open them. Version numbers in older planning notes aren't requirements: use current stable releases of tools and libraries.
- If Homebrew fails with "not writable" errors: `/opt/homebrew` is shared with another admin account on this Mac. Re-run `sudo chmod -R g+w /opt/homebrew`.

## Commands
```
make pins        # MCU pinout vs ST official pin data (fetches STM32_open_pin_data into validation/.cache)
make erc         # schematic ERC  -> build/erc.rpt, build/erc.json
make drc         # DRC + schematic parity -> build/drc.rpt, build/drc.json
make check       # pins + erc + drc + firmware-test + test-tools
make firmware    # build canode + nucleo images -> firmware/build/
make sim         # ngspice simulations -> validation/sim/out/
make renders     # board + enclosure renders -> hardware/docs/renders/ (~8 min)
make fab         # JLC gerber zip, BOM, CPL, hand-solder list -> build/fab/
make test-tools  # offline tests for tools/canlog
```

## How to work here
- Follow `validation/README.md` in order and update its status table. Write each step's findings to `validation/reports/YYYY-MM-DD_<step>.md`: what was checked, what passed, what changed.
- **ERC on this schematic:** nets connect by label stubs, not drawn wires. Expect possible warnings about PWR_FLAG or power-pin driving. Fix real errors in the schematic; explain anything you decide to leave.
- **Editing KiCad files:** the S-expression files can be edited as text, but keep changes small and surgical. After any edit, run `make check` and `make fab`, and say what changed. Ask T to make anything involving layout or routing taste in the GUI, or propose the exact change.
- If the schematic changes, the PCB must be updated with *Update PCB from Schematic* (F8) in the GUI. `make drc` with `--schematic-parity` catches drift.
- **Don't run *Update Symbols/Footprints from Library*** on this project. The embedded copies are KiCad 7 originals; KiCad 10's versions moved pins (U1, Y1, JP1/JP2) and renamed the USB-C shield pin, which would disconnect the label stubs. See `validation/reports/2026-11-09_erc.md`.
- Net-class patterns in `canode.kicad_pro` list each power net twice (`VIN` and `/VIN`), because nets are named `/VIN` once synced from the schematic. Keep both forms when adding nets, or the net silently falls back to the Default class.
- **Part choices:** use JLC basic or preferred parts where possible (no $3 extended-part fee). Every part JLC places needs an `LCSC` field on its symbol. Parts with no LCSC number become hand-solder parts.
- Don't commit `build/` or `validation/.cache/`.

## Safety rules (vehicle work)
- Never transmit on a real vehicle bus without T's explicit OK for that specific test. Default to **listen-only**: FDCAN bus-monitoring mode with the transceiver enabled (Rs low). Bus-monitoring mode sends no ACKs.
- Hardware default: the transceiver Rs pins are pulled up, which means **standby** (not driving the bus). Firmware must only drive Rs low after the FDCAN peripheral is configured.
- Bench tests that need termination: bridge JP1/JP2. Never leave them bridged when installing the board in a car, because the car's own network is already terminated.

## Known open issues (from the rev A review checklist)
- Not rated for an unsuppressed (87 V) load dump; designed for the 35 V suppressed dump and ISO 7637-2 pulse 2a (SMCJ33A + R17 10 Ω/C1 10 µF ahead of the LDO + R18 2.2 Ω in the D7 path). F1 reaches 37.8 A of its 40 A Imax in a reverse-battery sim.
- Quiescent draw on an always-hot feed: ~8–9 mA awake. Firmware Stop 1 sleep (`sleep` command, `lib/power.c`, `src/sleep.c`) gets ~1 mA including the power LED (R1 now 4.7 kΩ). Untested on hardware; never auto-sleeps once transmit was enabled since boot. CAN2 wakes via COMP3 on PB0, because PB0 and PD0 share EXTI line 0.
- J2 (Molex 43045) physical pin order is unverified against the Molex drawing: check before crimping a harness.
- SN65HVD230 with Rs high is TI's standby = receiver-only mode, i.e. a hardware listen-only state. Firmware supports `rslisten high`; bench-test reception at 500k before making it the default.
- When used inline (MITM), each cut bus segment may need its own termination: measure each segment before deciding on JP1/JP2.
- Autorouted layout: tidy the crystal and USB traces if time allows.
- JLC part rotation must be checked in their placement preview at order time.

## MCU pin map (also in firmware/README.md)
FDCAN1 PD0 RX / PD1 TX (AF3), CAN1 Rs = PD2 · FDCAN2 PB0 RX / PB1 TX (AF3), CAN2 Rs = PB2 · USB PA11/PA12 · HSE 12 MHz PF0/PF1 · VBAT sense PA0 (ADC1_IN0, ×11 divider) · AUX_IN sense PA1 (ADC1_IN1) · AUX_OUT gate PA8 (TIM1_CH1 AF2) · LEDs PA5/PA6 · USART2 PA2/PA3 (AF1) · spare PB6/PB7 (I2C1 AF6 or USART1)/PB8/PB9 · SWD PA13/PA14 (PA14 = BOOT0).
