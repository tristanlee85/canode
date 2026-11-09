# canode: dual-CAN vehicle interface

![canode, assembled board](hardware/docs/renders/canode_board_3d.png)

A small STM32G0B1 board with **two CAN channels**, USB-C and a 12 V automotive input, for sniffing, gatewaying and inline (man-in-the-middle) modification of vehicle CAN traffic. CAN1 faces the car, CAN2 faces the module. A typical job: suppress auto start-stop or change a body-module behaviour without touching the factory wiring.

Target vehicles: 2021 Ford Bronco Sport (HS/MS-CAN), 2019 Chevrolet Silverado 3500 (GM Global A), possibly a 2016 BMW F80. All three use classic CAN, not CAN-FD.

> **Status: rev A, pre-order.** The design passes ERC and DRC, the footprints and parts have been checked against datasheets and LCSC stock, and the analog front end has been simulated. **One open decision blocks ordering:** the input TVS diode (see [Open decisions](#open-decisions)). Firmware builds and its logic is unit-tested, but nothing has run on hardware yet.

| | |
|---|---|
| MCU | STM32G0B1CEU6 (UFQFPN-48): Cortex-M0+ 64 MHz, 2× FDCAN, crystal-less USB FS, 512 KB flash |
| CAN | 2× SN65HVD230 (3.3 V, classic CAN to 1 Mbit/s); held in standby by hardware until firmware enables them; optional 120 Ω termination per channel (solder jumper) |
| Power | 12 V input (PTC, TVS, reverse-polarity diode) or USB, into a TPS7B69 40 V LDO |
| I/O | VBAT and AUX_IN voltage sense, AUX_OUT low-side switch, SWD, UART, 4 spare GPIO |
| Harness | Molex Micro-Fit 3.0, 2×4 |
| Board | 85 × 50 mm, 2 layers; every SMD part on top for JLCPCB Economic assembly |
| Enclosure | 90 × 55 × 20 mm MJF nylon, ordered from JLC3DP (no printer needed) |

## What it looks like

| Closed, harness and USB connected | Exploded |
|---|---|
| ![closed enclosure](hardware/docs/renders/canode_enclosure_closed.png) | ![exploded view](hardware/docs/renders/canode_enclosure_exploded.png) |
| **Lid off** | **Top view, cm scale** |
| ![open enclosure](hardware/docs/renders/canode_enclosure_open.png) | ![top view with ruler](hardware/docs/renders/canode_enclosure_top_scale.png) |

The harness plugs into J2 through the lid. USB-C, the three status LEDs and the RESET/BOOT poke-holes are reachable with the lid on. The debug headers and termination jumpers are inside, two screws away. Mount it with the screw/zip-tie ears or VHB tape. Design, ordering and assembly: [`hardware/enclosure/`](hardware/enclosure/README.md).

<details><summary>Board top and bottom</summary>

![board top](hardware/docs/renders/canode_board_top.png)
![board bottom, with the J2 pinout on the silkscreen](hardware/docs/renders/canode_board_bottom.png)
</details>

Regenerate every image with `make renders` (KiCad 10, Blender, uv; about 8 minutes).

## Harness (J2, Molex Micro-Fit 3.0 2×4)

| Pin | Signal | Pin | Signal |
|---|---|---|---|
| 1 | +12 V (battery or switched) | 5 | GND |
| 2 | CAN1_H | 6 | CAN1_L |
| 3 | CAN2_H | 7 | CAN2_L |
| 4 | AUX_IN (0–36 V sense) | 8 | AUX_OUT (low-side switch) |

Each H/L pair sits on adjacent pins across the two rows, so twisted pairs land cleanly. The pinout is also on the board's back silkscreen and engraved on the enclosure.

## Quick start (macOS)

```bash
scripts/setup_mac.sh            # KiCad 10, ngspice, ARM GCC, CMake, OpenOCD, dfu-util, Blender, Python venv
source .venv/bin/activate
make check                      # pinout check + ERC + DRC + firmware and tool unit tests
make fab                        # JLC upload files -> build/fab/
make firmware                   # canode + NUCLEO-G0B1RE images -> firmware/build/
make sim                        # ngspice power-input simulations
make renders                    # board + enclosure renders
```

Ordering steps are in [`hardware/README.md`](hardware/README.md#ordering-at-jlcpcb).

## Validation

The full plan, with pass criteria, is in [`validation/README.md`](validation/README.md); dated results are in [`validation/reports/`](validation/reports/).

| Check | Result |
|---|---|
| Netlist vs design table | ✅ 61 parts, 45 nets, 0 mismatches |
| MCU pinout vs ST's pin data (UFQFPN-48) | ✅ 29/29 incl. exposed pad on GND |
| Schematic ERC | ✅ 0 errors |
| DRC + schematic parity | ✅ 0 errors, parity clean |
| Footprint ↔ datasheet pinout | ✅ all match; J2's physical pin order still to confirm against the Molex drawing |
| Reference-design comparison | ✅ crystal load caps corrected (30 → 20 pF) |
| LCSC stock | ✅ out-of-stock MCU, TVS and LED replaced |
| Analog simulation | ⚠ see [Open decisions](#open-decisions) |

## Firmware

Bare-metal C, CMake and `arm-none-eabi-gcc`, with ST's HAL for clocks/GPIO/FDCAN and TinyUSB for the USB virtual serial port. It builds for canode and for a **NUCLEO-G0B1RE** dev board, so you can start testing before the PCB arrives. Shell commands, flashing and the safety model are in [`firmware/README.md`](firmware/README.md).

**Safety model.** Both channels boot in FDCAN bus-monitoring mode (no ACKs, no transmit), with the transceivers held in standby until each controller is configured. Transmitting (normal mode, the gateway, sending a frame) requires an explicit shell command for one named channel, and nothing re-enables it automatically: not a bus-off recovery, a reboot, or a self-test.

## Open decisions

1. **Input TVS (D3) and the protection chain.** Simulation shows the SMBJ24A starts conducting at 26.7–29.5 V. In a *suppressed* load dump (about 35 V, which modern alternators produce) it would absorb 16–49 J, several times what it can survive. The fix is an SMBJ33A-class TVS (≥ 36 V breakdown). That lets fast spikes reach about 54 V, above the LDO's 45 V absolute maximum, so it should come with a 10 Ω + ≥ 8 µF filter in front of the LDO and a 60 V AUX_OUT FET. Details and numbers: [`validation/reports/2026-11-09_sim.md`](validation/reports/2026-11-09_sim.md). The board is not rated for an *unsuppressed* load dump (87 V).
2. **Quiescent current on an always-hot feed** is about 9 mA with the MCU running (not the 2 mA once estimated). Feed J2 pin 1 from a switched circuit, or add a firmware stop mode that wakes on CAN.

## Repo map

| Path | What |
|---|---|
| `hardware/kicad/` | KiCad 10 project: **source of truth** |
| `hardware/fab/` | JLC upload files for rev A (regenerate with `make fab`) |
| `hardware/docs/` | Schematic PDF and renders |
| `hardware/enclosure/` | Parametric enclosure (build123d), STEP files, render pipeline |
| `hardware/3dmodels/` | Stand-in 3D models for parts KiCad's library lacks |
| `hardware/generator/` | One-shot scripts that created rev A (don't re-run) |
| `firmware/` | STM32G0B1 firmware + host unit tests |
| `validation/` | Pin check, ngspice simulations, validation plan and reports |
| `tools/canlog/` | Terminal CAN logger and byte-diff tool for STN adapters (OBDLink MX+) |
| `CLAUDE.md` | Context and rules for Claude Code sessions |
