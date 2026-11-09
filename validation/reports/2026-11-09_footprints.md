# Step 5: Footprint ↔ datasheet pin mapping (2026-11-09)

**Result: PASS for every Step 5 row except J2. 0 ❌. J2's physical pin positions are UNVERIFIED** because the Molex drawing couldn't be retrieved; its pad-to-net mapping matches the design. One process caveat: the KENTO LED datasheets number the pins the opposite way from KiCad (see the LEDs section). Polarity there has to be judged by the cathode mark, not the pin number.

## What was checked, and how
For each part, three things were checked:
1. **Datasheet:** what each physical pin is, taken from the datasheet LCSC links for that exact LCSC number. The datasheet URL came from JLC's part record for that number, so the manufacturer is the one JLC will actually place.
2. **Footprint:** which pad number sits at which physical position. Pads and nets were read from a snapshot of `hardware/kicad/canode.kicad_pcb` (md5 `3e046981…`, identical to `HEAD`). Positions are footprint-local with KiCad's +y pointing down.
3. **Symbol:** which pin number the schematic symbol gives to each function, read from the symbols embedded in the schematic. That pin number is the pad number.

Result: datasheet function → pad number → net, compared against `design.py` and `hardware/README.md`.

The lead edited the KiCad files after the snapshot. I re-dumped the in-progress `canode.kicad_pcb` (md5 `5e6f728a…`) for every part in this report: **pad numbers, pad sizes, footprints and nets are identical**. Footprint positions were not compared. Later edits are not covered.

Symbol pin conventions confirmed from the embedded symbols:
- `Device:LED`: 1 = K, 2 = A.
- `Device:D_Zener` and `Diode:SS34`: 1 = K, 2 = A.
- `Transistor_FET:AO3400A`: 1 = G, 2 = S, 3 = D.
- `canode:TPS7B6933`: 1 = IN, 2 = GND, 3 = OUT.
- `SN65HVD230`: 1 D, 2 GND, 3 VCC, 4 R, 5 Vref, 6 CANL, 7 CANH, 8 Rs.
- `USBLC6-2SC6`: 1/6 = I/O1, 2 = GND, 3/4 = I/O2, 5 = VBUS.

---

### U2: TPS7B6933QDCYRQ1, SOT-223 (LCSC C108471, TI)
Datasheet: TI SLVSCJ8B §6, DCY package — https://datasheet.lcsc.com/datasheet/pdf/6f175de08d0a41c78395f46e86f06060.pdf?productCode=C108471

| Datasheet pin | Pad (footprint `SOT-223-3_TabPin2`) | Net | |
|---|---|---|---|
| 1 IN | 1 (−3.15, −2.3) | VIN | ✅ |
| 2 GND | 2 (−3.15, 0) | GND | ✅ |
| 3 OUT | 3 (−3.15, +2.3) | +3V3 | ✅ |
| 4 (tab) GND | tab pad, numbered "2" (+3.15, 0), 2 × 3.8 mm | GND | ✅ |

This is the TI DCY pinout (IN-GND-OUT, tab = GND). It is **not** the 1117-style ADJ/GND-OUT-IN pinout, which is the trap here.

### Q1: AO3400A, SOT-23 (C20917, Alpha & Omega)
Datasheet: AOS AO3400A Rev 3 — https://datasheet.lcsc.com/datasheet/pdf/130876b936da464599428c58fd8de8f6.pdf?productCode=C20917

AOS draws the pins pictorially rather than numbering them. In the top view the pin-1 dot sits at **G**, the single pin is D, and the remaining pin is S. That gives the standard SOT-23 mapping 1 = G, 2 = S, 3 = D.

| Datasheet pin | Pad | Net | |
|---|---|---|---|
| G (pin 1, dot) | 1 (−0.94, −0.95) | AUX_GATE | ✅ |
| S (pin 2) | 2 (−0.94, +0.95) | GND | ✅ |
| D (pin 3, lone pin) | 3 (+0.94, 0) | AUX_OUT | ✅ |

Low-side switch: source to GND, drain to the load. R16 (100k) holds the gate low during reset. ✅

### U4, U6: NUP2105LT1G, SOT-23 (C14486, onsemi)
Datasheet: onsemi NUP2105L (Case 318, Style 27) — https://datasheet.lcsc.com/datasheet/pdf/56f16c73e40041cf92a35c6bb132cc50.pdf?productCode=C14486

Two bidirectional TVS sections run from pin 1 and pin 2 to the common pin 3. In the application figure, CAN_H and CAN_L land on pins 1 and 2 and pin 3 goes to ground.

| Datasheet pin | Pad | U4 net | U6 net | |
|---|---|---|---|---|
| 1 (line 1) | 1 | CAN1_H | CAN2_H | ✅ |
| 2 (line 2) | 2 | CAN1_L | CAN2_L | ✅ |
| 3 (common) | 3 | GND | GND | ✅ |

The part is symmetric, so swapping H and L would also be harmless. V_RWM is 24 V and the clamp is 40 V at 5 A.

### U7: USBLC6-2SC6, SOT-23-6 (C7519, ST)
Datasheet: ST USBLC6-2, Fig. 1 — https://datasheet.lcsc.com/datasheet/pdf/0d3a2ab954b34651a0695e7ccf534db0.pdf?productCode=C7519

| Datasheet pin | Pad | Net | |
|---|---|---|---|
| 1 I/O1 | 1 | USB_DM | ✅ |
| 2 GND | 2 | GND | ✅ |
| 3 I/O2 | 3 | USB_DP | ✅ |
| 4 I/O2 | 4 | USB_DP | ✅ |
| 5 VBUS | 5 | VBUS | ✅ |
| 6 I/O1 | 6 | USB_DM | ✅ |

The flow-through pairs (1↔6 and 3↔4) each sit on one net, as ST intends.

### D1, D2, D7: SS34, SMA (C8678, MDD)
Datasheet: MDD SS32–SS3200, "Polarity: Color band denotes cathode end" — https://datasheet.lcsc.com/datasheet/pdf/dfa1ff67dea875d0135103ba9ada713a.pdf?productCode=C8678

`D_SMA` pad 1 is the cathode (KiCad convention; the symbol has pin 1 = K).

| Ref | Pad 1 = K (band) | Pad 2 = A | Current flows | Intent | |
|---|---|---|---|---|---|
| D1 | VIN | VBATF | VBATF → VIN | Reverse-battery block, OR-ing | ✅ |
| D2 | VIN | VBUS | VBUS → VIN | USB OR-ing | ✅ |
| D7 | VBATF | AUX_OUT | AUX_OUT → VBATF | Flyback from the low-side switch drain to the supply | ✅ |

### D3: SMBJ24A, SMB (C143156, Formosa MS): the cathode is on VBATF ✅
Datasheet: FMS SMBJ series, "Polarity: Indicated by cathode band". JLC lists this part as **Unidirectional**, VRWM 24 V, VBR 26.7–29.5 V, VC 38.9 V. https://datasheet.lcsc.com/datasheet/pdf/74d3e72a6d9960e8110cfe92ff64450f.pdf?productCode=C143156

| Datasheet | Pad (`D_SMB`) | Net | |
|---|---|---|---|
| Cathode (band) | 1 (symbol pin 1 = K) | **VBATF** | ✅ |
| Anode | 2 | GND | ✅ |

A battery connected the right way round reverse-biases the TVS, so it stays off. A reversed battery forward-biases it, which crowbars the input until F1 trips. This is the intended behaviour.

> ⚠ This exact LCSC part has **0 stock** (see `2026-11-09_lcsc.md`). Any replacement must be a **unidirectional** SMBJ24A (not SMBJ24**C**A) and must have a band = cathode marking. The C123819 and C224017 candidates both qualify.

### D4–D6: LEDs (D4 C2297 KT-0805G, D6 C2286 KT-0603R, both Hubei KENTO; D5 C72038 Everlight 19-213)
Datasheets:
- KT-0603R: https://datasheet.lcsc.com/datasheet/pdf/011ec3e8cb1e825f6961d29bc4db4c7a.pdf?productCode=C2286
- KT-0805G: https://datasheet.lcsc.com/datasheet/pdf/de342fde3322df0797012cd7a04e2194.pdf?productCode=C2297

| Ref | KiCad pad 1 (K) | KiCad pad 2 (A) | |
|---|---|---|---|
| D4 | GND | PWR_LED_A (R1 to +3V3) | ✅ |
| D5 | GND | LED1_A (R3 to PA5) | ✅ |
| D6 | GND | LED2_A (R4 to PA6) | ✅ |

**Cathode-mark convention:** in the KENTO package drawing, terminal **② is "−" (cathode)** and carries the green corner mark (top view) and the T-shaped mark (bottom view). Terminal **① is "+" (anode)**. So the mark denotes the cathode ✅, which is the usual convention.

> **Trap: the datasheet numbering is the reverse of KiCad's.** KENTO's pin 1 is the anode, while KiCad's pad 1 is the cathode. The netlist is right because KiCad's pad 1 is the cathode. But in JLC's placement preview, judge polarity by **the mark, which must sit on the GND pad**, not by "pin 1".

The same KENTO drawing (mark on ② = cathode) appears in the KT-0603Y (C2287) and KT-0603W (C2290) datasheets, the proposed D5 replacements.

The Everlight 19-213 datasheet for D5 (C72038) was not image-checked, because that part is out of stock and should be replaced anyway.

### Y1: X322512MSB4SI, 3225 (C9002, YXC)
Datasheet: YXC YSX321SL family; JLC attributes give 12 MHz, CL 20 pF, ESR 80 Ω. https://datasheet.lcsc.com/datasheet/pdf/a84bd8d530dd46e4b0f6d0ee59d8a89c.pdf?productCode=C9002

The datasheet's "Top View Crystal Connection" has #1 bottom-left, #2 bottom-right, #3 top-right and #4 top-left. #1–#3 is the crystal; #2 and #4 are GND.

| Datasheet pin | Pad (position) | Net | |
|---|---|---|---|
| #1 crystal | 1 (−1.1, +0.85) bottom-left | HSE_IN | ✅ |
| #2 GND | 2 (+1.1, +0.85) bottom-right | GND | ✅ |
| #3 crystal | 3 (+1.1, −0.85) top-right | HSE_OUT | ✅ |
| #4 GND | 4 (−1.1, −0.85) top-left | GND | ✅ |

The positions also match the datasheet's corner-to-corner layout, with the crystal on the diagonal.

### J1: HRO TYPE-C-31-M-12 (C165948)
Datasheet: HRO drawing, recommended PCB layout and pin table — https://datasheet.lcsc.com/datasheet/pdf/9e56b777c022540fcce7c7f67825f55e.pdf?productCode=C165948

HRO's pad order, left to right on the component side: A1/B12, A4/B9, B8, A5, B7, A6, A7, B6, A8, B5, B4/A9, B1/A12. The KiCad footprint has the same order: x = −3.25, −2.45, −1.75, −1.25, −0.75, −0.25, +0.25, +0.75, +1.25, +1.75, +2.45, +3.25.

| HRO pin (function) | Pad | Net | |
|---|---|---|---|
| A1, B12, B1, A12 (GND) | A1, B12, B1, A12 | GND | ✅ |
| A4, B9, A9, B4 (VBUS) | A4, B9, A9, B4 | VBUS | ✅ |
| A5 (CC1) | A5 | USB_CC1 (R9 5.1k to GND) | ✅ |
| B5 (CC2) | B5 | USB_CC2 (R10 5.1k to GND) | ✅ |
| A6 (DP1), B6 (DP2) | A6, B6 | USB_DP | ✅ |
| A7 (DN1), B7 (DN2) | A7, B7 | USB_DM | ✅ |
| A8, B8 (SBU) | A8, B8 | not connected | ✅ (fine for a device) |
| Shell (4 THT tabs) | S1 ×4 | GND | ✅ |

### J2: Molex Micro-Fit 3.0 43045-0812 (hand-solder; LCSC C277661 for reference)

| Pad | Net | README / design.py | |
|---|---|---|---|
| 1 | VBAT_IN | +12 V | ✅ |
| 2 | CAN1_H | CAN1_H | ✅ |
| 3 | CAN2_H | CAN2_H | ✅ |
| 4 | AUX_IN | AUX_IN | ✅ |
| 5 | GND | GND | ✅ |
| 6 | CAN1_L | CAN1_L | ✅ |
| 7 | CAN2_L | CAN2_L | ✅ |
| 8 | AUX_OUT | AUX_OUT | ✅ |

Footprint geometry:
- Pads 1–4 are in one row (y = 0); pads 5–8 are in the other (y = 3.00).
- 3.00 mm pitch, so each H/L pair sits across the rows (2/6 and 3/7), as the README describes.
- Two NPTH peg holes sit at (−3, 3.94) and (12, 3.94).

**UNVERIFIED:** that these pad numbers match Molex's circuit numbering and the latch/peg side of the real 43045-0812.
- molex.com was unreachable from this machine; downloads and fetches timed out.
- The mirrors that worked (Farnell, RS, onlinecomponents) had only product specification sheets, without the dimensioned drawing.
- The footprint comes from KiCad's standard library, which is normally generated from the Molex drawing, but I did not confirm that here.

**Action for T:**
1. Before crimping the harness, open Molex SD-43045-xxx for 43045-0812 and check two things: circuit 1's position relative to the peg holes and latch, and the molded cavity numbers on the 43025-0800 receptacle.
2. Remember the receptacle is a mirror image when viewed from the wire side.

### U1: STM32G0B1CBT6, LQFP-48 (quick check)
- The pin functions were already verified pin by pin against ST's data in step 2 (`make pins`, 28/28).
- Pad geometry: pad 1 at (−4.16, −2.75), which is the top of the left side.
  - Pads 1–12 run down the left side.
  - Pads 13–24 run left to right along the bottom.
  - Pads 25–36 run up the right side.
  - Pads 37–48 run right to left along the top.
- That is counter-clockwise from the pin-1 corner, as in ST's LQFP48 drawing (DS13560 Fig. 9). ✅
- The supply pins are wired correctly: 4 VBAT, 5 VREF+ and 6 VDD/VDDA are on +3V3, and 7 VSS/VSSA is on GND. ✅
- Note: the **"N" variants** (e.g. STM32G0B1CBT6**N**, C5270160) have a different pinout. DS13560 has separate "LQFP48 – GP" and "– N" pinout columns; for example pin 30 is PC6 on GP parts and VSS on N parts. **An N part is not a drop-in substitute.**

### U3, U5: SN65HVD230DR, SOIC-8 (C12084, TI)
Datasheet: TI SLOS346K (LCSC copy) and SLOS346O (ti.com) — https://datasheet.lcsc.com/datasheet/pdf/5f0a15e636e3498a8a69f46b0b740274.pdf?productCode=C12084 · https://www.ti.com/lit/ds/symlink/sn65hvd230.pdf

| Datasheet pin | Pad | U3 net | U5 net | |
|---|---|---|---|---|
| 1 D (driver in) | 1 | CAN1_TX | CAN2_TX | ✅ |
| 2 GND | 2 | GND | GND | ✅ |
| 3 VCC | 3 | +3V3 | +3V3 | ✅ |
| 4 R (receiver out) | 4 | CAN1_RX | CAN2_RX | ✅ |
| 5 Vref (VCC/2 out) | 5 | not connected | not connected | ✅ (an output; leaving it open is allowed) |
| 6 CANL | 6 | CAN1_L | CAN2_L | ✅ |
| 7 CANH | 7 | CAN1_H | CAN2_H | ✅ |
| 8 Rs | 8 | CAN1_STBY (R5 10k to +3V3; MCU PD2) | CAN2_STBY (R7 10k to +3V3; MCU PB2) | ✅ |

What Rs does:
- V(Rs) above 0.75·VCC selects standby. The 10k pull-up to 3.3 V meets that, so standby is the default. ✅
- V(Rs) below 1 V selects high-speed mode, which is how the MCU enables the driver.
- In standby, TI says "the driver is switched off and the receiver remains active … completely passive to the bus" (SLOS346O §10.4.3, "Standby Mode (**Listen Only** Mode)"). See the step 7 report for what this means.

### SW1, SW2: XKB TS-1187A-B-A-B (C318884)
Datasheet: XKB drawing — https://datasheet.lcsc.com/datasheet/pdf/56c8799ae5193945a16a1ffbe378246a.pdf?productCode=C318884

The drawing's schematic joins **A–B** and **C–D** permanently; pressing the button connects (A,B) to (C,D). A and B are the two legs on one long side; C and D are on the other. The PCB layout is 7.0/5.0 mm in x and 4.5/3.0 mm in y, so the pad centres are at (±3.0, ±1.875).

| Legs | KiCad pads | SW1 net | SW2 net | |
|---|---|---|---|---|
| A, B (top pair, joined) | pad "1" at (−3, −1.875) and (+3, −1.875) | NRST | +3V3 | ✅ |
| C, D (bottom pair, joined) | pad "2" at (−3, +1.875) and (+3, +1.875) | GND | BOOT_SW | ✅ |

A 180° placement error is harmless. A 90° error is not: it would short the switch permanently, holding NRST low. The legs only exist along x, so a 90° error should be obvious in JLC's preview.

### F1 (not polarised): BSMD1206-050-30V, 1206 (C883126)
Pad 1 is VBAT_IN and pad 2 is VBATF. ✅

---

## Summary
| Ref | Result |
|---|---|
| U2, Q1, U4/U6, U7, D1/D2/D7, D3, D4–D6, Y1, J1, U1, U3/U5, SW1/SW2 | ✅ datasheet pin → pad → net all match the design intent |
| J2 | ✅ pad → net; **UNVERIFIED** pad number → physical Molex circuit position (drawing not retrievable) |
| LEDs | ✅, with a caveat: KENTO numbers the anode as pin 1, so JLC's preview must be judged by the cathode mark |

No KiCad files were changed.
