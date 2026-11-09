# CAN node hardware, rev A (prototype)

This is a 2-channel CAN interface board for in-vehicle sniffing and gatewaying. It is built around an STM32G0B1, which has two FDCAN controllers and crystal-less USB. It has two 3.3 V CAN transceivers and a 12 V automotive input, and it fits JLCPCB's **Economic PCBA**: every SMD part is on the top side, and only the through-hole connectors are left for you to solder by hand.

> **Status: unreviewed first pass.** The schematic was generated from a parts and nets list, and the board was **autorouted** (Freerouting). DRC shows 0 unrouted nets and 0 clearance errors. Please go through the checklist at the bottom before ordering.

## What's in the folder

| Path | What it is |
|---|---|
| `kicad/canode.kicad_pro` | **Open this in KiCad 8 or 9.** It was made with KiCad 7.0; newer versions upgrade it when you save. |
| `kicad/canode.kicad_sch` | Single-sheet schematic. Nets connect by **name labels**, not drawn wires: two pins with the same label are connected. |
| `kicad/canode.kicad_pcb` | 2-layer, 85 × 50 mm board with GND pours on both layers and stitching vias. |
| `kicad/canode.kicad_sym`, `sym-lib-table` | Project library holding the one custom symbol (TPS7B6933). |
| `fab/canode_gerbers_JLC.zip` | **Upload this to JLCPCB.** Gerbers and Excellon drills. |
| `fab/canode_BOM_JLC.csv` | BOM for JLC assembly (Comment / Designator / Footprint / LCSC Part #). |
| `fab/canode_CPL_JLC.csv` | Pick-and-place file (Designator / Mid X / Mid Y / Layer / Rotation). |
| `fab/canode_HAND_SOLDER.csv` | Parts JLC does **not** place: J2 Micro-Fit and the J3/J4/J5 pin headers. |
| `docs/canode_schematic.pdf` | Schematic PDF for reviewing on paper. |
| `docs/*.png` | Copper, silk and Gerber previews. |
| `scripts/jlc_fab.py` | Regenerates the JLC files from the KiCad project after you edit it (`make fab`). |
| `generator/` | Python scripts that produced the first version. `design.py` defines the parts, nets and LCSC numbers; `layout.py` defines placement. Written against the KiCad 7 Python API; once you edit in KiCad, treat KiCad as the source of truth and don't re-run it (it re-autoroutes and overwrites the board). |

## Block summary

**Power.** The J2 12 V pin feeds a 500 mA PTC (F1), then a 24 V unidirectional TVS (D3, SMBJ24A), then an SS34 diode (D1). Behind the diode is a 40 V-rated 3.3 V LDO (U2, TPS7B6933-Q1, 15 µA quiescent). USB VBUS is diode-ORed onto the same node through D2, so the board runs from USB on the bench or from the car in the vehicle. If the battery is connected backwards, D1 blocks and the TVS conducts until the PTC trips.

**MCU.** STM32G0B1CBT6 (LQFP-48, 128 KB flash) with a 12 MHz crystal for an accurate CAN bit clock. USB runs from the internal 48 MHz oscillator with clock recovery (CRS).

**CAN (×2).**
- Each channel has an SN65HVD230 transceiver and an NUP2105L CAN ESD diode.
- Each has a 120 Ω terminator that only connects when you bridge a solder jumper (JP1 / JP2). The jumpers are **open by default**, so termination is off.
- The Rs pin has a **10k pull-up**, so the transceiver sits in **standby (not driving the bus)** until firmware pulls Rs low. The bus stays silent while the MCU is resetting, blank or crashed.
- For true listen-only, use FDCAN *bus monitoring* mode, which sends no ACKs, with Rs low.

**Sense and output.**
- VBAT and AUX_IN each go to an ADC pin through a 100k:10k divider with a 100 nF filter. Full scale is about 36 V, about 9 mV per count.
- AUX_OUT is a low-side AO3400A switch with an SS34 flyback diode to VBAT. It can drive a relay coil or an LED, or pull down a factory switch input.

**Debug.** SWD header (J3), UART header (J4), 4 spare GPIO (J5), RESET and BOOT buttons, and power / two status LEDs.

### J2: Molex Micro-Fit 3.0, 2×4 vertical (43045-0812)

| Pin | Signal | Pin | Signal |
|---|---|---|---|
| 1 | +12 V (battery / switched) | 5 | GND |
| 2 | CAN1_H | 6 | CAN1_L |
| 3 | CAN2_H | 7 | CAN2_L |
| 4 | AUX_IN (0–36 V sense) | 8 | AUX_OUT (low-side switch) |

H/L pairs are stacked across the two rows, so each twisted pair lands on adjacent pins. The pinout is also printed on the back silkscreen.

### MCU pin map (for firmware)

| Function | Pin | Notes |
|---|---|---|
| FDCAN1 RX / TX | PD0 / PD1 | AF3 |
| CAN1 Rs (standby) | PD2 | drive LOW to enable transceiver |
| FDCAN2 RX / TX | PB0 / PB1 | AF3 |
| CAN2 Rs (standby) | PB2 | drive LOW to enable transceiver |
| USB DM / DP | PA11 / PA12 | |
| HSE | PF0 / PF1 | 12 MHz, 30 pF load caps |
| VBAT sense | PA0 (ADC IN0) | V = adc × 3.3/4096 × 11 |
| AUX_IN sense | PA1 (ADC IN1) | same divider |
| AUX_OUT gate | PA8 | TIM1_CH1 if you want PWM |
| LED1 / LED2 | PA5 / PA6 | active high |
| Debug UART | PA2 TX / PA3 RX | USART2 |
| Spare GPIO | PB6, PB7, PB8, PB9 | PB6/PB7 = I2C1 or USART1 |
| SWD | PA13 SWDIO / PA14 SWCLK | PA14 is also BOOT0 |

## Ordering at JLCPCB

1. **Upload `canode_gerbers_JLC.zip`.** JLC should detect a 2-layer, 85 × 50 mm board.
2. **Choose the board options.**
   - 1.6 mm thickness, any color, HASL lead-free or ENIG.
   - Leave *Remove order number* at its default (or pay to remove it).
   - The PCB minimum is 5 boards.
3. **Turn on PCB Assembly.**
   - Choose **Economic**, **Top side**, and **2** for the assembly quantity.
4. **Upload the BOM and CPL.**
   - BOM is `canode_BOM_JLC.csv`; CPL is `canode_CPL_JLC.csv`.
   - Every line should match an LCSC part. If one shows out of stock, pick an equivalent and note the change.
5. **Check part rotation and polarity in the placement preview.** KiCad and JLC sometimes disagree on a footprint's zero angle. Check that pin 1 or the polarity mark lines up on:
   - U1 (LQFP pin-1 dot)
   - U2 (SOT-223 tab)
   - U3 and U5 (SOIC pin 1)
   - U4, U6 and Q1 (SOT-23)
   - U7 (SOT-23-6)
   - D1, D2, D3 and D7 (cathode band)
   - D4, D5 and D6 (LED cathode)
   - J1 (USB-C)

   You can rotate parts right in the preview, and JLC's DFM engineers also check.
6. **Order the hand-solder parts separately** (Digi-Key / Mouser / LCSC):
   - Molex **43045-0812**, plus mating housing 43025-0800 and crimp terminals 43030-0001 (or a pre-crimped Micro-Fit pigtail).
   - Straight 2.54 mm headers: 1×5, 1×3 and 1×6.

Ballpark cost: about $2 for the PCBs, plus Economic PCBA setup (about $8 + stencil). Expect roughly 6–8 extended-part fees at $3 each (MCU, LDO, transceiver, CAN ESD diode, USB-C, PTC, TVS, ...) on top of parts. That comes to something like $40–60 for 2 assembled boards before shipping; JLC's quote is the real number.

## First power-up and programming

1. Power from USB-C only. The PWR LED should light and 3.3 V should appear on J3 pin 1.
2. A blank STM32G0 boots straight into the ROM **USB DFU bootloader**, so it shows up as "STM32 BOOTLOADER". Flash it with `dfu-util` or STM32CubeProgrammer, with no debugger needed. After the first flash, use SWD (J3, ST-Link) or re-enter DFU from firmware.
3. The BOOT button only works after you set the option bytes **nBOOT_SEL = 0** (use the BOOT0 pin). With the factory defaults it is ignored.
4. Bench test: bridge JP1 and JP2 to terminate both buses and connect CAN1↔CAN2 with a short twisted pair. Each channel can then talk to the other in loopback.

## Review checklist (things I want your eyes on)

**Electrical decisions**
- [ ] **PTC voltage rating.** BSMD1206-050-30V is rated 30 V, but the TVS clamps near 39 V during a load dump. That is fine for bench and sniffing use. For a permanent install, swap to a 60 V-rated PTC or a fuse.
- [ ] **AUX_OUT FET is 30 V.** It covers relays and LEDs, but a severe load dump can exceed it. Use a 40–60 V FET (for example in SOT-23) if AUX_OUT will be permanently wired.
- [ ] **Quiescent draw on an always-hot 12 V feed.**
  - PWR LED about 1.3 mA.
  - Two SN65HVD230 in standby about 0.7 mA.
  - VBAT divider about 0.1 mA.

  For a permanent install, mark D4 not-fitted or move the power LED to a GPIO. Ideally feed J2 pin 1 from a switched or ignition source.
- [ ] **Crystal load caps.** 30 pF assumes CL = 20 pF and about 5 pF stray. Fine-tune if the measured frequency is off.
- [ ] **CAN transceivers.** SN65HVD230 (3.3 V) is standard and interoperates with 5 V CAN, but it is specified only to 1 Mbps. That covers classic CAN; for CAN-FD with a faster data phase, swap to an FD-rated transceiver such as TCAN1044 (similar SOIC-8 pinout family, so check the pin mapping first).

**Layout**
- [ ] **Autorouted, not hand-optimized.** Signal tracks are 0.25 mm; power tracks are 0.5 mm (VBAT / VIN / VBUS / AUX_OUT) and 0.3 mm (3V3 / GND). USB D+/D- are not length-matched; at 12 Mbps full-speed that is fine. Re-routing the crystal and USB pairs by hand is the main tidy-up if you want it.
- [ ] **USB-C overhang.** Check in the 3D viewer (`Alt+3`) that J1 sits flush with the board edge.
- [ ] **One thermal-relief warning** on U5 pin 2 (GND). That pin also has a routed track, so it is electrically fine.
- [ ] **Two silk reference labels** (C5, C7) sit close to neighbors in the dense decoupling area. Cosmetic only.

**Process**
- [ ] **Re-run ERC and DRC.** Open in KiCad 8/9 and run **ERC** (Inspect → Electrical Rules Checker) and **DRC** (Inspect → Design Rules Checker). The headless KiCad 7 used here can't run ERC from the command line. I checked the netlist with a script instead (61 parts, 45 nets, 0 mismatches against the design table) and ran DRC through the Python API.
- [ ] **Check LCSC stock** at order time; the numbers were checked against JLC's catalog in Nov 2026.

## Modern KiCad crash course (since ExpressPCB)

- **Projects.** Schematic, PCB and rules are tied together by `.kicad_pro`. Edit the schematic, then press **F8** (*Update PCB from Schematic*) in the PCB editor. Footprints stay linked to their symbols by ID, so moved parts keep their positions.
- **Net labels.** This schematic uses "label stubs" instead of drawn wires. Hover a label and press the backtick key (`` ` ``) to highlight that net everywhere. To tidy it up, delete the stubs and draw wires; connectivity is identical.
- **Routing tools.**
  - **X** routes a track; **V** while routing drops a via.
  - **D** drags a track and its neighbors follow.
  - **B** refills the copper zones after you edit tracks.
  - **Edit → Global Deletions… (Tracks)** if you want to start the routing over.
- **Board Setup** (File → Board Setup) holds the net classes and design rules. Power/Supply classes already set the wider tracks.
- **Fab outputs**: run `make fab` from the repo root (writes `build/fab/`), or use File → Fabrication Outputs. The "Fabrication Toolkit" plugin (Plugin & Content Manager) is a GUI alternative.
