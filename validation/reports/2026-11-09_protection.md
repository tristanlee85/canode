# Input protection update (2026-11-09)

**Why.** Step 6 (`2026-11-09_sim.md`) found that D3 (SMBJ24A, breakdown 26.7–29.5 V) conducts in the
35 V *suppressed* load dump that modern alternators produce, and would absorb 16–49 J. T approved the
redesign on 2026-11-09. Design target: **ISO 16750-2 test B (35 V suppressed load dump) and ISO 7637-2
pulse 2a**. The board is still **not rated for an unsuppressed (test A, 87 V) load dump**.

## What changed

| Ref | Before | After | LCSC | Why |
|---|---|---|---|---|
| D3 | SMBJ24A, 600 W, SMB | **SMCJ33A, 1500 W, SMC** (Diodes Inc SMCJ33A-13-F) | C135162 (Extended, 3,999 in stock, $0.37) | Breakdown 36.7 V min, so it doesn't conduct at 35 V. The SMC part's lower dynamic resistance (0.52 Ω vs 1.30 Ω for SMBJ33A) holds pulse-2a spikes to ~51 V instead of ~61 V. Standoff 33 V covers a 24 V jump start. |
| R17 (new) | — | **10 Ω 0805**, D1 cathode → VIN | C17415 (Basic) | With C1, forms an RC filter in front of the LDO so fast spikes don't reach it. |
| C1 | 1 µF 50 V 0805 | **10 µF 50 V X5R 1206** (Samsung CL31A106KBHNNNE) | C13585 (Basic) | Filter capacitor. About 3 µF effective at 25–30 V bias, which is what the sims assume. |
| R18 (new) | — | **2.2 Ω 0805** in series with D7 (AUX_OUT flyback) | C17521 (Basic) | Removes the second reverse-battery path through Q1's body diode and D7 (was 14.6 A for ~12 ms; now 0.74 A). |
| R1 | 1 kΩ | **4.7 kΩ** (same 0603) | C23162 (Basic) | Power-LED draw 0.2–0.8 mA → ~0.1–0.17 mA. It's always on, so it matters once the firmware sleeps. |

- New nets: `/VIN_PRE` (D1 cathode to R17) and `/AUX_FLY` (R18 to D7 anode). Both are added to the Power netclass in `canode.kicad_pro`, in both the `VIN_PRE` and `/VIN_PRE` forms.
- Unchanged:
  - Q1 stays AO3422 (55 V). With the SMC clamp, its worst simulated V<sub>DS</sub> is 49.4 V (pulse 2a, D3 at VBR max), which leaves 10 % margin.
  - D1, D2 and D7 stay SS36 (60 V).
  - F1 stays at 30 V. With D3 no longer conducting at 35 V, F1 never trips in a test-B dump.
- Extended-part count is unchanged (8): D3 was already Extended, and the new parts are Basic.

## Simulation results (`make sim`, cases tagged `*_new`)

The `NEW` parameter set in `validation/sim/run_all.py` covers SMCJ33A, R17 10 Ω, C1 3 µF effective, R18 2.2 Ω and Q1 at 55 V.

| Event | Before (SMBJ24A, as built) | After |
|---|---|---|
| **Suppressed load dump, 35 V / 0.5 Ω / 400 ms**, relay on AUX_OUT | D3 1.4–5.3 A, **16–49 J (FAIL)**; Q1 31.6 V on a 30 V part | **D3 0 A**, F1 doesn't trip, VIN 34.5 V (< 40 V operating), Q1 35.1 V of 55 V. Same at Ri 4 Ω and with D3 at VBR min (36.7 V). **PASS** |
| **ISO 7637-2 pulse 2a, 112 V / 2 Ω**, relay | VIN 44.3 V (above the LDO's 40 V operating limit, 0.7 V under its 45 V abs max) | VBATF 50.8 V (52.3 V at VBR max), **VIN 29.1–29.7 V**, Q1 48.0–49.4 V, D3 0.01 J. **PASS** |
| **Reverse battery, −14 V**, slow PTC | Q1 body diode 14.6 A / 20 W / 114 mJ (unrated); F1 peak 39.3 A | **Q1 body diode 0.74 A / 4 mJ**; F1 peak 37.8 A (Imax 40 A, 5 % margin); VIN −0.05 V. **PASS, F1 margin thin** |
| Relay flyback at 13.5 V | Q1 13.8 V | Q1 15.0 V (+0.7 V from R18 at 0.16 A) |
| 12 V hot-plug | 8.6 A inrush (µs) | **1.1 A** inrush (R17 limits it); +3V3 reaches 3.0 V in 92 µs |
| USB-only power | VIN 4.76 V | Unchanged (D2 feeds VIN directly, after R17) |
| Crank dip to 4.5 V, **50 mA** load | (simulated at 20 mA: VIN min 4.26 V) | VIN min 3.72 V; the TI model holds +3V3 at 3.30 V. With the datasheet's **worst-case** 0.8 V dropout, +3V3 could sag to ~2.9 V for the 30 ms dip. That is fine for the MCU but below the SN65HVD230's 3.0 V minimum. **CONCERN (minor)**: a severe cold crank only, and the transceivers recover. |
| Unsuppressed load dump, 87 V / 1 Ω (not a target) | VIN 48.8 V; D3 10.7 J | VIN 52.2 V for 11 ms; D3 13 J. **Still FAIL, as expected.** |

Model notes:
- The SMCJ33A is the same `SMBJ_UNI` subcircuit as the other TVS models, with the datasheet JEDEC values (VBR 38.65 V nominal, VC 53.3 V at 28.2 A, so rd = 0.52 Ω).
- The forward diode model is still the SMB template. The real SMC part drops less forward, which makes the reverse-battery numbers slightly conservative for Q1 and slightly optimistic for F1.
- **The TI LDO model has an internal ~1 µF input capacitor.** It made the earlier "as built SMBJ33A" pulse-2a row (VBATF 54 V) look better than the real board would. A part with only C1 ahead of the LDO sees ~61 V on VBATF with an SMBJ33A. That's why D3 went to the SMC package rather than SMBJ33A.
- The TVS energy allowance printed by `run_all.py` is scaled from the 600 W SMB rating. The SMC part is rated 1500 W, so the real allowance is about 2.5× what the summary shows.

## Board changes
- D3: footprint `Diode_SMD:D_SMC`, moved 1.2 mm up (to 120.4, 106.3) so it clears R6.
- F1 moved 0.6 mm left and D1 0.6 mm right to clear D3's larger courtyard.
- C1: footprint `Capacitor_SMD:C_1206_3216Metric`, at 132.4, 108.0.
- R17 sits at 128.6, 108.0, between D1 and C2. R18 sits at 104.0, 128.8, above D7.
- Re-route:
  - Ripped up: all VBAT_IN, VBATF, VIN, VIN_PRE, AUX_OUT and AUX_FLY tracks, plus any track under the new or moved parts.
  - Kept, locked: all other copper.
  - Routed by Freerouting 2.1 in two passes. Same method as `2026-11-09_u1-qfn.md`.
- Two GND links were added by hand: C2 GND → C1 GND → U2 pin 2. The new VIN loop around C1/C2 had cut those pads off from the pour, and the input caps now return straight to the LDO's ground pin.
- Silkscreen references for D3, C1, C2, D7, R17 and R18 were placed clear of pads and other silk.

## Verification
- `make check`:
  - pins 29/29;
  - ERC 0 errors (11 library warnings, unchanged);
  - DRC **0 errors, 0 unconnected, schematic parity clean**;
  - firmware and tool tests pass.
- `make fab`: 30 BOM lines, 55 placements. The BOM/CPL diff is exactly the parts above, plus the F1/D1/D3/C1 position changes.
- `hardware/fab/` and `hardware/docs/canode_schematic.pdf` were regenerated.

## Remaining notes
- **F1 Imax:** 37.8 A peak in reverse battery against a 40 A rating. A stiffer source or shorter harness pushes it over. The only fix is a different PTC, and no 1206 part at JLC is better. Accepted for a prototype.
- **D7 (SS36, 60 V)** is reverse-biased by VBATF when Q1 is on: 50.8–52.3 V in pulse 2a, about 13 % margin.
- **C1 (50 V)** sees at most 34.5 V. **D1** only sees reverse voltage during a reverse-battery event (≤ 14 V).
- **AUX_IN** still has no clamp. Test B is fine (PA1 3.2 V), but an unsuppressed dump would exceed PA1's limits, as before.
- Renders in `hardware/docs/renders/` were regenerated with the new parts; the enclosure fit check still reports no interference.
