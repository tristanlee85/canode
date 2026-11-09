# CAN node hardware, rev A (prototype)

This is a 2-channel CAN interface board for in-vehicle sniffing and gatewaying. It is built around an STM32G0B1, which has two FDCAN controllers and crystal-less USB. It has two 3.3 V CAN transceivers and a 12 V automotive input, and it fits JLCPCB's **Economic PCBA**: every SMD part is on the top side, and only the through-hole connectors are left for you to solder by hand.

> **Status: unreviewed first pass.** The schematic was generated from a parts and nets list, and the board was **autorouted** (Freerouting). DRC shows 0 unrouted nets and 0 clearance errors. Please go through the checklist at the bottom before ordering.

## What's in the folder

| Path | What it is |
|---|---|
| `kicad/canode.kicad_pro` | **Open this in KiCad 10.** Generated with KiCad 7.0, upgraded to KiCad 10 format on 2026-11-09. |
| `kicad/canode.kicad_sch` | Single-sheet schematic. Nets connect by **name labels**, not drawn wires: two pins with the same label are connected. |
| `kicad/canode.kicad_pcb` | 2-layer, 85 × 50 mm board with GND pours on both layers and stitching vias. |
| `kicad/canode.kicad_sym`, `sym-lib-table` | Project library holding the one custom symbol (TPS7B6933). |
| `fab/canode_gerbers_JLC.zip` | **Upload this to JLCPCB.** Gerbers and Excellon drills. |
| `fab/canode_BOM_JLC.csv` | BOM for JLC assembly (Comment / Designator / Footprint / LCSC Part #). |
| `fab/canode_CPL_JLC.csv` | Pick-and-place file (Designator / Mid X / Mid Y / Layer / Rotation). |
| `fab/canode_HAND_SOLDER.csv` | Parts JLC does **not** place: J2 Micro-Fit and the J3/J4/J5 pin headers. |
| `docs/canode_schematic.pdf` | Schematic PDF for reviewing on paper (regenerate: `kicad-cli sch export pdf`). |
| `docs/renders/` | 3D board and enclosure renders (`make renders`). |
| `3dmodels/` | Stand-in 3D models for J1, J2, SW1/SW2 and the mating plug (KiCad has none). |
| `enclosure/` | Parametric MJF-nylon enclosure, STEP files and the render pipeline. |
| `scripts/jlc_fab.py` | Regenerates the JLC files from the KiCad project after you edit it (`make fab`). |
| `generator/` | Python scripts that produced the first version. `design.py` defines the parts, nets and LCSC numbers; `layout.py` defines placement. Written against the KiCad 7 Python API; once you edit in KiCad, treat KiCad as the source of truth and don't re-run it (it re-autoroutes and overwrites the board). |

## Block summary

**Power.** The J2 12 V pin feeds a 500 mA PTC (F1), then a 1500 W unidirectional TVS (D3, SMCJ33A, 36.7 V minimum breakdown), then an SS36 diode (D1). An RC filter (R17 10 Ω, C1 10 µF/50 V) follows the diode, then a 40 V-rated 3.3 V LDO (U2, TPS7B6933-Q1, 15 µA quiescent). The TVS stays off in a 35 V suppressed load dump. The filter holds fast spikes (ISO 7637-2 pulse 2a) under 30 V at the LDO. USB VBUS is diode-ORed onto the LDO input through D2, after the filter, so the board runs from USB on the bench or from the car in the vehicle. If the battery is connected backwards, D1 blocks and the TVS conducts until the PTC trips. Not rated for an unsuppressed (87 V) load dump. See `validation/reports/2026-11-09_protection.md`.

**MCU.** STM32G0B1CEU6 (UFQFPN-48, 512 KB flash; changed from the LQFP-48 CBT6 on 2026-11-09 because the LQFP was out of stock everywhere. Same pin numbering. The exposed pad is soldered to GND through a 3×3 via grid) with a 12 MHz crystal for an accurate CAN bit clock. USB runs from the internal 48 MHz oscillator with clock recovery (CRS).

**CAN (×2).**
- Each channel has an SN65HVD230 transceiver and an NUP2105L CAN ESD diode.
- Each has a 120 Ω terminator that only connects when you bridge a solder jumper (JP1 / JP2). The jumpers are **open by default**, so termination is off.
- The Rs pin has a **10k pull-up**, so the transceiver sits in **standby (not driving the bus)** until firmware pulls Rs low. The bus stays silent while the MCU is resetting, blank or crashed.
- For true listen-only, use FDCAN *bus monitoring* mode, which sends no ACKs, with Rs low.

**Sense and output.**
- VBAT, AUX_IN, IGN_IN and AUX_IN2 each go to an ADC pin through a 100k:10k divider with a 100 nF filter. Full scale is about 36 V, about 9 mV per count.
- HARNESS_ID (J2 pin 11): 10 kΩ pull-up to 3.3 V, then 10 kΩ + 100 nF into the ADC. The T-harness puts an ID resistor from pin 11 to pin 12 (GND). A wiring fault that puts 12–36 V on the pin pushes at most ~3 mA into the pin's clamp and the 3.3 V rail through 10 kΩ.
- AUX_OUT is a low-side AO3422 (55 V) switch with an SS36 (60 V) flyback diode to VBAT, through R18 (2.2 Ω), which keeps reverse-battery current out of Q1's body diode. It can drive a relay coil or an LED, or pull down a factory switch input.

**Debug.** SWD header (J3), UART header (J4), 4 spare GPIO (J5), RESET and BOOT buttons, and power / two status LEDs.

### J2: Molex Micro-Fit 3.0, 2×6 vertical (43045-1212)

| Pin | Signal | Pin | Signal |
|---|---|---|---|
| 1 | +12 V (battery or switched) | 7 | GND |
| 2 | CAN1_H (car side) | 8 | CAN1_L |
| 3 | CAN2_H (module side) | 9 | CAN2_L |
| 4 | AUX_IN (0–36 V sense) | 10 | AUX_OUT (low-side switch) |
| 5 | IGN_IN (0–36 V sense: ignition / accessory feed) | 11 | HARNESS_ID (resistor to GND in the T-harness) |
| 6 | AUX_IN2 (0–36 V sense) | 12 | GND (ID resistor return, shield drain) |

H/L pairs are stacked across the two rows, so each twisted pair lands on adjacent pins. The pinout is also printed on the back silkscreen.

### MCU pin map (for firmware)

| Function | Pin | Notes |
|---|---|---|
| FDCAN1 RX / TX | PD0 / PD1 | AF3 |
| CAN1 Rs (standby) | PD2 | drive LOW to enable transceiver |
| FDCAN2 RX / TX | PB0 / PB1 | AF3 |
| CAN2 Rs (standby) | PB2 | drive LOW to enable transceiver |
| USB DM / DP | PA11 / PA12 | |
| HSE | PF0 / PF1 | 12 MHz, 20 pF load caps |
| VBAT sense | PA0 (ADC IN0) | V = adc × 3.3/4096 × 11 |
| AUX_IN sense | PA1 (ADC IN1) | same divider |
| IGN_IN sense | PB10 (ADC IN11) | same divider |
| AUX_IN2 sense | PB11 (ADC IN15) | same divider |
| HARNESS_ID | PB12 (ADC IN16) | 10k pull-up; V = 3.3 × R / (R + 10k) |
| AUX_OUT gate | PA8 | TIM1_CH1 if you want PWM |
| LED1 / LED2 | PA5 / PA6 | active high |
| Debug UART | PA2 TX / PA3 RX | USART2 |
| Spare GPIO | PB6, PB7, PB8, PB9 | PB6/PB7 = I2C1 or USART1 |
| SWD | PA13 SWDIO / PA14 SWCLK | PA14 is also BOOT0 |

## Harness: pigtail and T-harness

canode never plugs straight into a car. Three pieces sit between them, so one board serves every vehicle:

```
canode J2 ──pigtail (~20 cm)──▶ universal inline connector ◀── per-vehicle T-harness ──▶ factory connector ⇄ CAN gateway
 (Micro-Fit 2×6)                 (12-way, sealed)               (made once per vehicle)
```

1. **Pigtail (the same for every car).** It runs from a Micro-Fit 43025-1200 housing on J2 to the universal connector, wired pin for pin (J2 pin n = universal pin n). Use 20–22 AWG automotive wire (TXL/GXL), and twist each CAN pair (2/8 and 3/9) at about 30–40 twists per metre.
2. **Universal inline connector.** The suggested part is a **Deutsch DTM 12-way** pair: sealed, cheap, and stocked everywhere. The pigtail end is a DTM04-12PA receptacle with pin contacts and a WM-12P wedge. The T-harness end is a DTM06-12SA plug with socket contacts and a WM-12S wedge. Contacts are size 20, crimped with the matching tool. Confirm the part numbers against the TE/Deutsch catalogue before ordering. This uses the usual automotive convention: the side that carries battery power (the T-harness) gets the **sockets**, so no live pin is exposed when it's unplugged. canode's side has no power on its pins when unplugged.
3. **T-harness (one per vehicle).** It has an inline male/female pair matching the factory connector at that vehicle's CAN gateway, plus the DTM06 branch:
   - every factory pin passes straight through, except the one CAN pair being intercepted;
   - the car side of that pair goes to pins 2/8 (CAN1) and the gateway side to pins 3/9 (CAN2);
   - +12 V comes from the gateway's battery feed, through an inline 2 A fuse close to the tap, to pin 1, and its ground goes to pin 7;
   - an ignition or accessory feed, if the connector has one, goes to pin 5;
   - the harness's ID resistor sits between pins 11 and 12, inside the DTM06 boot.

Which bus, which pins and which connector to use are per-vehicle research (service-info pinouts plus a sniff on the car). Record each finished harness in `hardware/harness/<vehicle>.md` with its connector part numbers, pin table and ID resistor value.

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
   - U1 (QFN pin-1 corner mark; the part changed from LQFP, so check this one carefully)
   - U2 (SOT-223 tab)
   - U3 and U5 (SOIC pin 1)
   - U4, U6 and Q1 (SOT-23)
   - U7 (SOT-23-6)
   - D1, D2, D3 and D7 (cathode band)
   - D4, D5 and D6 (LED cathode)
   - J1 (USB-C)

   You can rotate parts right in the preview, and JLC's DFM engineers also check.
6. **Order the hand-solder parts separately** (Digi-Key / Mouser / LCSC):
   - Molex **43045-1212**, plus mating housing 43025-1200 and crimp terminals 43030-0001 for the pigtail (see [Harness](#harness-pigtail-and-t-harness)).
   - Straight 2.54 mm headers: 1×5, 1×3 and 1×6.

Ballpark cost: about $2 for the PCBs, plus Economic PCBA setup (about $8 + stencil). Expect 8 extended-part fees at $3 each (per `validation/reports/2026-11-09_lcsc.md`) on top of parts. That comes to something like $40–60 for 2 assembled boards before shipping; JLC's quote is the real number.

## First power-up and programming

1. Power from USB-C only. The PWR LED should light and 3.3 V should appear on J3 pin 1.
2. A blank STM32G0 boots straight into the ROM **USB DFU bootloader**, so it shows up as "STM32 BOOTLOADER". Flash it with `dfu-util` or STM32CubeProgrammer, with no debugger needed. After the first flash, use SWD (J3, ST-Link) or re-enter DFU from firmware.
3. The BOOT button only works after you set the option bytes **nBOOT_SEL = 0** (use the BOOT0 pin). With the factory defaults it is ignored.
4. Bench test: bridge JP1 and JP2 to terminate both buses and connect CAN1↔CAN2 with a short twisted pair. Each channel can then talk to the other in loopback.

## Review checklist (things I want your eyes on)

**Electrical decisions**
- [x] **Input TVS (D3) and protection chain.** Done 2026-11-09: SMCJ33A (1500 W, 36.7 V min breakdown) replaces the SMBJ24A, which would have absorbed 16–49 J in a 35 V suppressed load dump. Added R17 10 Ω + C1 10 µF ahead of the LDO and R18 2.2 Ω in the D7 path. Simulated: D3 carries 0 A at 35 V, the LDO sees ≤ 34.5 V, Q1 ≤ 49.4 V of 55 V (`validation/reports/2026-11-09_protection.md`). Still not rated for an *unsuppressed* load dump.
- [x] **PTC voltage rating.** With D3 sized as above, F1 only sees ≤ 13 V (when tripped by a reversed battery), so the 30 V BSMD1206 stays. No 60 V PTC exists in 1206 at JLC. Its 40 A Imax is the tightest margin left: 37.8 A peak in the reverse-battery sim.
- [x] **AUX_OUT FET.** Now AO3422 (55 V). Flyback diode D7 and the OR diodes D1/D2 are now SS36 (60 V); D2 saw ~44 V reverse in ISO 7637-2 pulse 2a.
- [x] **Quiescent draw on an always-hot 12 V feed.** Awake: ~9 mA (the MCU at 64 MHz dominates). The firmware now drops to STM32 Stop 1 after 60 s of bus silence and wakes on CAN1, CAN2 or a UART key. R1 went from 1 kΩ to 4.7 kΩ so the always-on PWR LED draws ~0.1–0.17 mA. Estimated sleep total: about 1 mA (two SN65HVD230s in standby 0.74 mA, VBAT divider 0.11 mA, LED, LDO, MCU). Measure on the bench (`firmware/README.md`, Sleep).
- [x] **Crystal load caps.** Changed 30 → 20 pF (step 7: ST's ~10 pF stray estimate left almost no oscillator start-up margin at 30 pF). Fine-tune if the measured frequency is off.
- [ ] **CAN transceivers.** SN65HVD230 (3.3 V) is standard and interoperates with 5 V CAN, but it is specified only to 1 Mbps. That covers classic CAN; none of the target vehicles use CAN-FD. If FD is ever needed, TCAN337GDR is a true drop-in (TCAN1044 needs a 5 V supply this board doesn't have). See `validation/reports/2026-11-09_lcsc.md`.

**Layout**
- [ ] **Autorouted, not hand-optimized.** Signal tracks are 0.25 mm; power tracks are 0.5 mm (VBAT / VIN / VBUS / AUX_OUT) and 0.3 mm (3V3 / GND). USB D+/D- are not length-matched; at 12 Mbps full-speed that is fine. Re-routing the crystal and USB pairs by hand is the main tidy-up if you want it.
- [ ] **USB-C overhang.** Check in the 3D viewer (`Alt+3`) that J1 sits flush with the board edge.
- [x] **Thermal relief on U5 pin 2** (GND): fixed 2026-11-09 by giving that pad a solid zone connection.
- [x] **Overlapping silk labels** (C5 / Y1): fixed 2026-11-09 by moving Y1's label 2.2 mm left.

**Process**
- [x] **Re-run ERC and DRC.** Done with KiCad 10 on 2026-11-09: 0 ERC errors, 0 DRC errors, schematic parity clean. See `validation/reports/2026-11-09_erc.md` and `2026-11-09_drc.md`.
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
