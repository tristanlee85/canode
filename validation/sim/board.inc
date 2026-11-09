* canode rev A: power input, LDO, VBAT/AUX sense and AUX_OUT (shared by every sim).
* Transcribed from hardware/generator/design.py (refs and net names match the schematic).
* External nodes the top-level netlist drives: VBAT_IN (J2-1), AUX_IN (J2-4),
* AUX_OUT (J2-8), VBUS (USB), AUX_DRV (MCU PA8). Ground is node 0 (J2-5).
* Parameters that the top level must define (with .param):
*   tvs_vbr, tvs_rd      D3 TVS (SMBJ24A: 28.1, 0.70)
*   ptc_r25, ptc_cth     F1 PTC corner (see models/canode.lib)
*   rload3               +3V3 load (MCU + transceivers in standby)
*   aux_drv              PA8 gate drive level (0 = AUX_OUT off)
*   toff                 time PA8 drops to 0 (10 = never)
*   rd7                  series R in the D7 flyback path (what-if; 1m = as built)
*   rvin, c1eff          series R D1->VIN and C1 effective value (what-if; 1m / 0.8u = as built)
*
* Current probes (0 V sources): VIF1 (F1, VBAT_IN -> VBATF), VID3 (D3 TVS, cathode
* current), VID1 (D1), VID7 (D7, AUX_OUT -> VBATF), VIQ1 (Q1 drain).

* ---- F1 PTC, D3 TVS, D1 reverse-polarity diode
VIF1 VBAT_IN F1A 0
XF1  F1A VBATF F1_TJ PTC_BSMD1206 PARAMS: r25={ptc_r25} cth={ptc_cth}
VID3 VBATF D3K 0
XD3  0 D3K SMBJ_UNI PARAMS: vbr={tvs_vbr} rd={tvs_rd}
VID1 VBATF D1A 0
XD1  D1A VINR ss34
* rvin: what-if series resistor D1 -> VIN (default 1 mohm = as built)
RVIN VINR VIN {rvin}
* ---- USB OR-ing diode D2 and VBUS cap C15 (VBUS left floating unless driven)
XD2  VBUS VIN ss34
C15  VBUS 0 4.7u
RVBUSLK VBUS 0 1meg

* ---- LDO input caps. C1 1 uF/50 V X7R 0805 (~0.8 uF effective at 12-14 V), C2 100 nF/50 V.
* c1eff: what-if bigger C1 (as built 0.8u effective)
C1   VIN C1X {c1eff}
RC1  C1X 0 10m
C2   VIN 0 100n
* U2 TPS7B6933-Q1 (TI transient model: VIN VOUT GND_0 GND_1).
XU2  VIN P3V3 0 0 TPS7B6933-Q1_TRANS
* The TI model is purely behavioral: its IN pin draws nothing when off. Add what silicon has:
* ~15 uA quiescent (as 1 Mohm) and the IN-to-GND substrate/ESD diode, so D1's reverse
* leakage cannot drag VIN to an unphysical negative voltage in the reverse-battery sim.
RU2Q VIN 0 1meg
DU2S 0 VIN DSUB
.MODEL DSUB D(IS=1e-14 N=1 RS=1)

* ---- +3V3 output caps (DC-bias-derated effective values):
*  C3 10u/6.3V 0603 X5R ~5.5u, C6 4.7u/25V 0805 ~4.0u, C8 1u/25V 0603 ~0.9u,
*  C4 C5 C7 C9 C13 C14 6 x 100n = 0.6u   -> 11 uF effective (16.4 uF nominal)
COUT P3V3 COX 11u
RCO  COX 0 3m
* MCU + 2x SN65HVD230 standby + misc, as a resistor
RL3  P3V3 0 {rload3}
* power LED: R1 1k + D4 green
R1   P3V3 LEDA 1k
D4   LEDA 0 LEDG
.MODEL LEDG D(IS=1e-20 N=1.8 RS=10)

* ---- VBAT sense: R11 100k / R12 10k / C16 100n -> PA0 (ADC1_IN0)
R11  VBATF VBAT_SENSE 100k
R12  VBAT_SENSE 0 10k
C16  VBAT_SENSE 0 100n
XPA0 VBAT_SENSE 0 STM32_FT_PIN
* ---- AUX_IN sense: R13 100k / R14 10k / C17 100n -> PA1 (ADC1_IN1). No TVS in front.
R13  AUX_IN AUX_SENSE 100k
R14  AUX_SENSE 0 10k
C17  AUX_SENSE 0 100n
XPA1 AUX_SENSE 0 STM32_FT_PIN

* ---- AUX_OUT low-side switch: Q1 AO3400A, R15 100R gate, R16 100k pull-down, D7 SS34 flyback to VBATF
* gate drive: aux_drv until toff, then 0 (toff=10 s = never, within these sims)
VDRV AUX_DRV 0 PWL(0 {aux_drv} {toff} {aux_drv} {toff+20n} 0)
R15  AUX_DRV AUX_GATE 100
R16  AUX_GATE 0 100k
VIQ1 AUX_OUT Q1D 0
MQ1  Q1D AUX_GATE 0 AO3400A_FIT
* rd7: what-if series resistor in the D7 path (default 1 mohm = as built)
VID7 AUX_OUT D7A 0
RD7  D7A D7B {rd7}
XD7  D7B VBATF ss34
