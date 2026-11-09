# Step 7: Reference-design comparison (2026-11-09)

**Result: no blocking errors. One problem is worth fixing before ordering:** the HSE load caps (C10/C11 = 30 pF) leave almost no crystal start-up margin. Several smaller items are listed below; each is marked intentional, minor or problem.

## Sources used
| Block | Reference | Link |
|---|---|---|
| STM32G0B1 | DS13560 Rev 1 (LCSC copy): Fig. 15 power-supply scheme, HSE oscillator table, Fig. 27 NRST, Tables 21/22 | https://datasheet.lcsc.com/datasheet/pdf/5429b93ac90cd8c9fdb4f061f26f4cf4.pdf?productCode=C2847904 |
| STM32G0 hardware | AN5096: **not retrieved**. The DS13560 figures above were used instead; they cover decoupling, NRST and HSE. AN2867 (oscillator design) was not re-fetched; its gm_crit criterion is applied below. | — |
| Crystal | YXC YSX321SL (X322512MSB4SI): CL 20 pF, ESR ≤ 80 Ω at 12–15 MHz, C0 ≤ 3 pF | https://datasheet.lcsc.com/datasheet/pdf/a84bd8d530dd46e4b0f6d0ee59d8a89c.pdf?productCode=C9002 |
| SN65HVD230 | TI SLOS346O (Apr 2018) | https://www.ti.com/lit/ds/symlink/sn65hvd230.pdf |
| TPS7B69-Q1 | TI SLVSCJ8B | https://datasheet.lcsc.com/datasheet/pdf/6f175de08d0a41c78395f46e86f06060.pdf?productCode=C108471 |
| USBLC6-2SC6 | ST USBLC6-2 | https://datasheet.lcsc.com/datasheet/pdf/0d3a2ab954b34651a0695e7ccf534db0.pdf?productCode=C7519 |

Board data comes from a snapshot of `canode.kicad_pcb` (md5 `3e046981…`, = HEAD) and from `design.py`.

---

## STM32G0B1 (U1)

| Item | Reference says | Board | Verdict |
|---|---|---|---|
| VDD/VDDA decoupling (pin 6) | 1 × 100 nF + 1 × 4.7 µF (DS13560 Fig. 15) | C5 100 nF, C6 4.7 µF | ✅ |
| VREF+ (pin 5) | 100 nF + 1 µF | C7 100 nF, C8 1 µF; VREF+ tied straight to +3V3 | ✅ Intentional: ADC reference = VDD. Fine for battery sensing. |
| VBAT (pin 4) | Connect to VDD when there's no backup battery | +3V3, plus C9 100 nF | ✅ |
| Cap placement | "As close as possible to, or below" the pins | C5/C7/C9/C8/C6 sit 3–7 mm left of pins 4–7 (pins at x ≈ 144.8; caps at x = 137.6–141) | ⚠ Minor. Acceptable for a 64 MHz M0+. Tightening is a layout-taste item for step 8; the track topology wasn't reviewed here. |
| NRST | 0.1 µF to GND; the internal pull-up is 25–55 kΩ (Fig. 27, Table 59) | C12 100 nF; SW1 to GND; no external pull-up | ✅ |
| BOOT0 = PA14 | PA14 has an internal pull-down at reset, so BOOT0 reads 0 (DS13560 pin-table note 4). The BOOT0 pin is used only when nBOOT_SEL = 0. | SW2 + R2 1k from +3V3 to SWCLK/PA14 | ✅ Intentional, already documented in the README (option byte needed). If the button is pressed while an ST-Link drives SWCLK low, about 3.3 mA flows through R2. Harmless. |
| Blank-device boot to the DFU bootloader | README claim | — | Not re-verified here (needs RM0444 / AN2606). Bring-up step 4 tests it. |

### HSE crystal and load caps: ⚠ Problem (recommended fix, cheap)
DS13560 HSE table:
- C_L1 and C_L2 are typically 5–20 pF.
- The datasheet says to use "**10 pF as a rough estimate** of the combined pin and board capacitance".
- Maximum critical crystal transconductance **Gm_crit_max = 1.5 mA/V** (start-up).

The crystal has CL = 20 pF, ESR max = 80 Ω and C0 max = 3 pF. AN2867's criterion is gm_crit = 4·ESR·(2πf)²·(C0 + CL_eff)², which must be below Gm_crit_max.

| C10 = C11 | Assumed stray | CL seen by the crystal | gm_crit (worst-case ESR) | Margin vs 1.5 mA/V |
|---|---|---|---|---|
| 30 pF (rev A) | 5 pF (README's assumption) | 20 pF | 0.96 mA/V | 1.56× |
| **30 pF (rev A)** | **10 pF (ST's estimate)** | **25 pF** | **1.43 mA/V** | **1.05×: almost none** |
| 22 pF | 10 pF | 21 pF | 1.05 mA/V | 1.43× |
| 20 pF | 10 pF | 20 pF | 0.96 mA/V | 1.56× |

- The 30 pF value assumes only 5 pF of stray. ST's own guidance is about 10 pF. If ST is right, the crystal is over-loaded (about 25 pF), and a worst-case 80 Ω crystal sits right at the start-up limit, so it might fail to start, especially cold.
- Frequency pulling from the 5 pF CL error is only on the order of 10–20 ppm. That is irrelevant for CAN, which tolerates ≥ 0.1 %, so the issue is start-up margin, not accuracy. (The pulling figure is an estimate; the motional capacitance C1 isn't in the datasheet.)
- **Recommendation:** change C10 and C11 to **20 pF (C1648, Samsung CL10C200JB8NNNC, C0G 50 V, JLC Basic, 2.18 M in stock)**, or 22 pF (C1653, Basic). Both are drop-ins on the same 0603 footprint and BOM-only changes.
- If T wants more margin, a crystal with CL = 10–12 pF would roughly halve gm_crit. I didn't search for one; it's optional.
- Drive level (YXC limit 10–200 µW, 100 µW typical) was not assessed and is UNVERIFIED. ST's HSE has no drive-level trim.

---

## SN65HVD230 (U3, U5)

| Item | Reference says | Board | Verdict |
|---|---|---|---|
| VCC decoupling | 100 nF ceramic, close to VCC/GND (SLOS346O §12) | C13 (U3) and C14 (U5), 100 nF each, about 5 mm away | ✅ |
| Rs = pin 8 | > 0.75·VCC = standby; 10–100 kΩ to GND = slope control; < 1 V = high speed | 10k pull-up to 3V3 (standby by default); MCU drives it low for high speed | ✅ Intentional. A GPIO can't do slope control, so EMI-optimised slope control isn't available. Fine at ≤ 500 kbps on short stubs. |
| MCU sinking Rs low | I(Rs) can be up to −450 µA in high-speed mode | GPIO sinks 0.45 mA plus 0.33 mA from the pull-up | ✅ |
| Vref (pin 5) | VCC/2 reference output; optional | Not connected | ✅ |
| Termination | 120 Ω at each end of the bus | R6/R8 120 Ω via JP1/JP2, open by default | ✅ Intentional. See the in-vehicle termination note below. |
| Bus-pin abs max | −4 V to +16 V | Covers a CAN_H short to a 12 V battery, but **not** a 24 V jump-start fault | Minor. The NUP2105L (24 V working) helps. |

### Standby is a hardware listen-only mode
TI SLOS346O §10.4.3, "Standby Mode (Listen Only Mode) of the HVD230", says that with Rs high, "the driver is switched off and the receiver remains active … the transceiver is completely passive to the bus."

So the board's **default state (R5/R7 pull-up) is already a hardware listen-only mode.** `CLAUDE.md` currently says to sniff with "FDCAN bus-monitoring mode with the transceiver enabled (Rs low)".

**Suggestion for T and the firmware:** for vehicle sniffing, keep **Rs high and also use FDCAN bus-monitoring mode.** The driver is then physically disabled, so even a firmware bug can't ACK or transmit. Drive Rs low only for a transmit test that T has explicitly approved.

Caveat: SLOS346O doesn't specify receiver timing separately for standby. That the receiver works at 500 kbps in standby is **UNVERIFIED**; bench-test it during CAN bring-up (step 7, external loopback).

### Vehicle physical layers and in-car termination
These are not board errors, but T should know before testing in a car. Details are in `2026-11-09_lcsc.md` §CAN-FD.
- **GM LS-GMLAN** (OBD pin 1) is single-wire CAN at 33.3 k, and **BMW F-series K-CAN** is fault-tolerant low-speed CAN. The SN65HVD230 can't talk to either. Connect this board only to two-wire high-speed buses (Ford HS/MS-CAN, GM HS-GMLAN, BMW PT-CAN/K-CAN2/D-CAN).
- **Termination when used inline (MITM).** If the board *cuts* a bus and sits between the car side (CAN1) and the module side (CAN2), it creates two separate bus segments. Each segment needs a 120 Ω terminator at both ends.
  - Example: if the isolated module isn't a terminating node, the CAN2 segment may need JP2 bridged.
  - So `CLAUDE.md`'s "never leave JP1/JP2 bridged in a car" holds for a passive **tap**, not automatically for an inline gateway.
  - Check each segment's termination with an ohmmeter (about 60 Ω across H–L with the bus unpowered) before powering up.

---

## TPS7B6933-Q1 (U2)

| Item | Reference says | Board | Verdict |
|---|---|---|---|
| Input cap | > 0.1 µF. Add 10 µF electrolytic plus a ceramic if the supply is "more than a few inches" away (§9.2.2.1, §10). | C1 1 µF/50 V X7R 0805 + C2 100 nF/50 V on VIN | ✅ Meets the minimum. ⚠ Minor: the car harness is long, so TI's 10 µF bulk advice technically applies. Optional: add a 10–22 µF/50 V cap on VBATF/VIN in rev B. |
| Output cap | **2.2–100 µF effective**, ESR 1 mΩ–2 Ω (Rec. Op. Conditions) | C3 10 µF 0603 X5R + C4 100 nF; plus about 6.9 µF nominal of MCU decoupling on +3V3 (C6 4.7 µF, C8 1 µF, 100 nF caps) | ✅ X5R DC-bias derating at 3.3 V wasn't looked up (UNVERIFIED), but even at 50 % the effective total is well above 2.2 µF. Ceramic ESR is within range. |
| BOM-note mismatch (not an electrical issue) | — | C3's LCSC part C96446 is actually **CL10A106MA8NRNC (25 V)**, not the CL10A106MQ8NNNC (6.3 V) written in the BOM "MPN" column | ⚠ Fix the note. The real part is better (25 V). |
| Input range | Recommended 4–40 V; abs max 45 V for 200 ms | VBATF is clamped by the SMBJ24A (VC 38.9 V at Ipp), then drops through D1 | ✅ marginal by design. Step 6 load-dump sim. |
| USB-only operation | VI(min) 4 V | VIN = VBUS − Vf(SS34, about 0.3–0.45 V) ≈ 4.3–4.9 V at 4.75–5.25 V VBUS | ✅. ⚠ Minor: at a 4.4 V worst-case hub port, VIN ≈ 4.0 V, right at the recommended minimum. |
| Thermal | RθJA 64 °C/W (DCY) | About 30 mA at 14 V in: about 0.33 W, about +21 °C | ✅ |

---

## USB-C device (J1, U7, R9/R10, C15)

| Item | Reference | Board | Verdict |
|---|---|---|---|
| Rd on CC | 5.1 kΩ to GND on **each** of CC1 and CC2, separately | R9 on CC1, R10 on CC2 | ✅ |
| D+/D− on both orientations | A6/B6 = D+, A7/B7 = D− | Both tied | ✅ |
| VBUS bulk | USB 2.0 limits a device to ≤ 10 µF on VBUS | C15 4.7 µF; plus C1/C2 (about 1.1 µF) behind D2 | ✅ |
| USBLC6 placement | Close to the connector; VBUS pin to VBUS; flow-through | U7 is about 9 mm from J1, between J1 and U1; pin 5 on VBUS; 1/6 and 3/4 paired | ✅ (closer is better; layout taste) |
| Series resistors on D+/D− | Not needed; STM32 FS PHY is integrated | None | ✅ |
| Shield | Direct to GND (common practice) | S1 to GND | ✅ Intentional |
| **VBUS sensing** | USB 2.0 §7.1.5: a self-powered device must not pull D+ up when VBUS is absent | Not sensed. When the board runs from the car with an unpowered host attached, firmware can't tell, and the internal 1.5 k pull-up back-feeds the host's D+. | ⚠ Minor, spec nit; fine for bench use. Option for rev B: a VBUS divider to a free FT pin (for example PA9, LQFP pin 29, currently unconnected). That's a schematic change, so it's T's call. |

---

## Other blocks noticed in passing

| Item | Observation | Verdict |
|---|---|---|
| D4 power-LED current | KT-0805G Vf is 2.6–3.1 V at 5 mA. Through R1 = 1k from 3.3 V that gives about 0.2–0.8 mA, **lower than the README's 1.3 mA** estimate (UNVERIFIED; measure at bring-up). | Info. See the D4 recommendation in the LCSC report. |
| Always-hot quiescent | The MCU at 64 MHz draws **about 8.6 mA typ** (DS13560 Table 28), plus 2 × 370 µA (HVD230 standby) and about 0.11 mA (VBAT divider). That dwarfs D4. | Info. A low draw on an always-hot feed needs firmware Stop modes or a switched feed, not just D4 removed. |
| AUX_IN overvoltage | PA0/PA1 are FT pins: VIN max = VDD + 4.0 V ≈ 7.3 V (Table 21), and positive injection isn't possible on FT pins. Through the 100k:10k divider, AUX_IN survives up to about 80 V steady state. There's no TVS on AUX_IN. | ✅ for a suppressed load dump (≤ 40 V). An unsuppressed 87 V pulse slightly exceeds the limit at the pin (about 7.9 V), though C17 slows fast edges. Step 6. |
| D7 sneak path | If the AUX_OUT load runs from a supply that stays on while J2 pin 1 is off, current flows load → AUX_OUT → D7 → VBATF → D1 and powers the board through the load. | ⚠ Minor / intentional? Worth a sentence in the README. Only matters when J2 pin 1 is switched separately from the load's supply. |

## Changes made
None. These are report-only findings. Proposed BOM changes (C10/C11 to 20 pF; fix the C3 and C2/C14663 MPN notes) are collected in `2026-11-09_lcsc.md`.
