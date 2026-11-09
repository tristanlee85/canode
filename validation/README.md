# Validation plan: CAN node rev A

The goal is to catch as much as possible **before** ordering boards, then bring the boards up in a fixed order once they arrive. Each step lists how to run it and what "pass" means. Put dated results in `validation/reports/` (for example `reports/2026-11-10_erc.md`).

## Before ordering (no hardware)

| # | Check | How | Pass criteria | Status |
|---|---|---|---|---|
| 1 | Netlist matches the design table | `hardware/generator/check_net.py <netlist>` | 0 mismatches | ✅ done (61 parts, 45 nets) |
| 2 | MCU pinout vs ST's official pin data | `make pins` | 0 failures; AF numbers recorded for firmware | ✅ passes (28/28) |
| 3 | Schematic ERC | `make erc` | No errors. Each warning reviewed and either fixed or explained in the report | ✅ done (0 errors; 11 lib-mismatch warnings explained, `reports/2026-11-09_erc.md`) |
| 4 | Board DRC + schematic parity | `make drc` | No errors; parity clean | ✅ done (0 errors, parity clean; 51 footprint-library-version warnings explained, `reports/2026-11-09_drc.md`) |
| 5 | Footprint ↔ datasheet pin mapping | Compare each risky part's datasheet pinout with the KiCad footprint pad numbers (list below) | Every row matches | ✅ all match; J2 Molex physical pin order **unverified** (check drawing before crimping) (`reports/2026-11-09_footprints.md`) |
| 6 | Analog simulation (ngspice) | `make sim` (`validation/sim/`) | See the simulation list below | ✅ after the protection update: SMCJ33A + 10 Ω/10 µF filter + 2.2 Ω in the D7 path; the 35 V suppressed dump, pulse 2a, reverse battery and crank all pass (`reports/2026-11-09_sim.md`, `reports/2026-11-09_protection.md`). Not rated for an unsuppressed 87 V dump. |
| 7 | Reference-design comparison | Each block vs its datasheet's typical application (list below) | Differences are intentional and noted | ✅ done; crystal caps changed 30→20 pF; other findings noted (`reports/2026-11-09_refdesign.md`) |
| 8 | Visual review in KiCad (2D + 3D view) | Open the project; `Alt+3` for the 3D view | USB-C flush with the edge, no parts colliding, silkscreen legible | ☐ |
| 9 | LCSC stock / price | Search each LCSC number on jlcpcb.com/parts | All in stock; extended-part count known | ✅ done; out-of-stock U1/D3/D5 replaced (U1 → STM32G0B1CEU6 UFQFPN-48); 8 extended parts (`reports/2026-11-09_lcsc.md`) |
| 10 | Optional: STM32CubeMX project | Build the `.ioc` from the pin table | No conflicts; generated init code builds | ☐ |

### Step 5: parts whose pinout must be checked by hand

| Ref | Part | Expected mapping (symbol pin → function) | Why risky |
|---|---|---|---|
| U2 | TPS7B6933QDCYRQ1 (SOT-223) | 1 IN, 2 GND, 3 OUT, tab = GND | SOT-223 regulators have several different pinouts |
| Q1 | AO3400A (SOT-23) | 1 G, 2 S, 3 D | MOSFET SOT-23 pinouts vary |
| U4, U6 | NUP2105L (SOT-23) | 1, 2 = CAN lines, 3 = common/GND | |
| U7 | USBLC6-2SC6 (SOT-23-6) | 1/6 = I/O1, 3/4 = I/O2, 2 = GND, 5 = VBUS | |
| D1, D2, D7 | SS34 (SMA) | pad 1 = cathode | Polarity |
| D3 | SMCJ33A (SMC) | pad 1 = cathode, to VBATF | Polarity: backwards makes it a short to ground |
| D4–D6 | LEDs | pad 1 = cathode | Polarity |
| Y1 | X322512MSB4SI (3225) | 1/3 = crystal, 2/4 = GND | |
| J1 | HRO TYPE-C-31-M-12 | A/B pin letters per the footprint | |
| J2 | Molex 43045-0812 | pins 1–4 in row 1, 5–8 in row 2 | The harness depends on it |

### Step 6: simulations worth running

1. **Reverse battery:** −14 V at J2. Expect D1 to block, D3 to conduct and the PTC to see current. Check nothing downstream goes below −0.5 V.
2. **Load dump (simplified):** 87 V source through 1 Ω for about 300 ms (roughly an unsuppressed ISO 16750 pulse). Check the peak voltage at VBATF and the LDO input stays at or below 40 V. Also check the AUX_OUT FET's drain voltage. This is the known weak spot: a 30 V part.
3. **VBAT divider:** ADC voltage at 9–16 V and at the clamp voltage; check settling with the 100 nF filter.
4. **LDO start-up** with the actual input and output capacitors (needs the TI PSPICE model).

### Step 7: reference designs

- STM32G0: ST AN5096, *Getting started with STM32G0 hardware* (decoupling, NRST, BOOT0, HSE).
- SN65HVD230: TI datasheet typical application, plus the Rs pin modes.
- TPS7B69-Q1: datasheet capacitor requirements.
- USB-C device: 5.1k Rd resistors on CC1 and CC2.

## After boards arrive (bring-up)

Do these strictly in order, and stop at the first failure.

1. **Unpowered:** inspect under magnification. Resistance from VBAT_IN, VIN and +3V3 to GND should all be well above 1 kΩ.
2. **12 V from a current-limited supply (100 mA limit):** +3V3 should read 3.25–3.35 V and input current about 10–30 mA.
3. **USB only:** same rail check.
4. **DFU:** `dfu-util -l` should list "STM32 BOOTLOADER" (VID:PID 0483:df11).
5. **SWD:** `st-info --probe` or `pyocd list`. pyOCD may first need `pyocd pack install stm32g0b1`.
6. **Firmware smoke tests:**
   - LEDs.
   - Switch to the 12 MHz crystal and check it locks. To measure it, output MCO on PA8 with nothing on AUX_OUT; the FET just toggles.
   - ADC readings against a meter.
   - AUX_OUT switching.
7. **CAN:**
   - Internal loopback.
   - External loopback: bridge JP1 and JP2, wire CAN1↔CAN2, test 125k/250k/500k/1M.
   - Bus-off recovery.
8. **Vehicle:** listen-only (FDCAN bus monitoring, Rs low) on the Bronco Sport's HS-CAN. Compare against `tools/canlog` captures from the OBDLink.
