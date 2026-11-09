"""CAN node Rev A - single source of truth for parts, nets, schematic + PCB placement.

Each part: ref, lib_id, value, footprint, lcsc, mpn, nets{pin:net}, sch(x,y), pcb(x,y,rot), opts
"""
R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
HDR = "Connector_PinHeader_2.54mm:PinHeader_1x{n:02d}_P2.54mm_Vertical"

PARTS = []
def P(ref, lib, value, fp, lcsc, mpn, nets, sch, pcb, dnp=False, jlc=True, desc=""):
    PARTS.append(dict(ref=ref, lib=lib, value=value, fp=fp, lcsc=lcsc, mpn=mpn, nets=nets,
                      sch=sch, pcb=pcb, dnp=dnp, jlc=jlc, desc=desc))

def R(ref, val, lcsc, a, b, sch, pcb, dnp=False):
    P(ref, "Device:R", val, R0603, lcsc, "0603 1% resistor", {"1": a, "2": b}, sch, pcb, dnp)
def C(ref, val, lcsc, a, b, sch, pcb, fp=C0603, mpn="MLCC"):
    P(ref, "Device:C", val, fp, lcsc, mpn, {"1": a, "2": b}, sch, pcb)

# ---------------------------------------------------------------- power input
P("J2", "Connector_Generic:Conn_02x04_Top_Bottom", "Micro-Fit 2x4",
  "Connector_Molex:Molex_Micro-Fit_3.0_43045-0812_2x04_P3.00mm_Vertical", "", "Molex 43045-0812",
  {"1": "VBAT_IN", "2": "CAN1_H", "3": "CAN2_H", "4": "AUX_IN",
   "5": "GND", "6": "CAN1_L", "7": "CAN2_L", "8": "AUX_OUT"},
  (30.48, 50.8), (8.0, 14.0, 90), jlc=False, desc="Vehicle harness connector (hand-solder THT)")
P("F1", "Device:Polyfuse", "500mA PTC", "Fuse:Fuse_1206_3216Metric", "C883126", "BSMD1206-050-30V",
  {"1": "VBAT_IN", "2": "VBATF"}, (63.5, 45.72), (17.5, 4.5, 0))
P("D3", "Device:D_Zener", "SMBJ24A", "Diode_SMD:D_SMB", "C143156", "SMBJ24A (uni-directional TVS)",
  {"1": "VBATF", "2": "GND"}, (83.82, 45.72), (17.5, 9.5, 180))
P("D1", "Diode:SS34", "SS34", "Diode_SMD:D_SMA", "C8678", "SS34",
  {"1": "VIN", "2": "VBATF"}, (63.5, 66.04), (24.0, 4.5, 180))
P("D2", "Diode:SS34", "SS34", "Diode_SMD:D_SMA", "C8678", "SS34",
  {"1": "VIN", "2": "VBUS"}, (63.5, 81.28), (66.0, 31.0, 0))
C("C1", "1uF 50V", "C28323", "VIN", "GND", (91.44, 76.2), (30.0, 9.0, 90), fp=C0805, mpn="CL21B105KBFNNNE")
C("C2", "100nF 50V", "C14663", "VIN", "GND", (101.6, 76.2), (32.0, 9.0, 90), mpn="CL10B104KB8NNNC")
P("U2", "canode:TPS7B6933", "TPS7B6933QDCYRQ1", "Package_TO_SOT_SMD:SOT-223-3_TabPin2", "C108471",
  "TPS7B6933QDCYRQ1", {"1": "VIN", "2": "GND", "3": "+3V3"}, (119.38, 76.2), (31.0, 3.8, 90))
C("C3", "10uF", "C96446", "+3V3", "GND", (139.7, 76.2), (36.0, 4.0, 90), mpn="CL10A106MQ8NNNC")
C("C4", "100nF", "C14663", "+3V3", "GND", (149.86, 76.2), (38.0, 4.0, 90), mpn="CL10B104KB8NNNC")
R("R1", "1k", "C21190", "+3V3", "PWR_LED_A", (91.44, 104.14), (41.5, 2.5, 0))
P("D4", "Device:LED", "Green", "LED_SMD:LED_0805_2012Metric", "C2297", "Green 0805 LED",
  {"1": "GND", "2": "PWR_LED_A"}, (114.3, 104.14), (45.5, 2.5, 180))
P("#FLG01", "power:PWR_FLAG", "PWR_FLAG", "", "", "", {"1": "GND"}, (124.46, 104.14), None, jlc=False)
P("#FLG02", "power:PWR_FLAG", "PWR_FLAG", "", "", "", {"1": "VIN"}, (134.62, 104.14), None, jlc=False)
P("#FLG03", "power:PWR_FLAG", "PWR_FLAG", "", "", "", {"1": "VBATF"}, (144.78, 104.14), None, jlc=False)

# ---------------------------------------------------------------- MCU
P("U1", "MCU_ST_STM32G0:STM32G0B1C_B-C-E_Tx", "STM32G0B1CBT6", "Package_QFP:LQFP-48_7x7mm_P0.5mm",
  "C2847904", "STM32G0B1CBT6",
  {"4": "+3V3", "5": "+3V3", "6": "+3V3", "7": "GND",
   "8": "HSE_IN", "9": "HSE_OUT", "10": "NRST",
   "11": "VBAT_SENSE", "12": "AUX_SENSE", "13": "UART_TX", "14": "UART_RX",
   "16": "LED1_DRV", "17": "LED2_DRV", "28": "AUX_DRV",
   "33": "USB_DM", "34": "USB_DP", "35": "SWDIO", "36": "SWCLK",
   "38": "CAN1_RX", "39": "CAN1_TX", "40": "CAN1_STBY",
   "19": "CAN2_RX", "20": "CAN2_TX", "21": "CAN2_STBY",
   "45": "GPIO_PB6", "46": "GPIO_PB7", "47": "GPIO_PB8", "48": "GPIO_PB9"},
  (228.6, 132.08), (45.0, 18.0, 0))
C("C5", "100nF", "C14663", "+3V3", "GND", (190.5, 40.64), (49.5, 12.6, 0), mpn="CL10B104KB8NNNC")
C("C6", "4.7uF", "C1779", "+3V3", "GND", (200.66, 40.64), (52.5, 12.0, 90), fp=C0805, mpn="CL21A475KAQNNNE")
C("C7", "100nF", "C14663", "+3V3", "GND", (210.82, 40.64), (40.0, 13.4, 0), mpn="CL10B104KB8NNNC")
C("C8", "1uF", "C15849", "+3V3", "GND", (220.98, 40.64), (40.0, 11.8, 0), mpn="CL10A105KB8NNNC")
C("C9", "100nF", "C14663", "+3V3", "GND", (231.14, 40.64), (40.0, 15.0, 0), mpn="CL10B104KB8NNNC")
P("Y1", "Device:Crystal_GND24", "12MHz", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm", "C9002",
  "X322512MSB4SI (20pF CL)", {"1": "HSE_IN", "2": "GND", "3": "HSE_OUT", "4": "GND"},
  (170.18, 160.02), (37.5, 21.5, 90))
C("C10", "30pF", "C1658", "HSE_IN", "GND", (162.56, 175.26), (35.0, 19.0, 0), mpn="0603 C0G 30pF")
C("C11", "30pF", "C1658", "HSE_OUT", "GND", (177.8, 175.26), (35.0, 24.0, 0), mpn="0603 C0G 30pF")
C("C12", "100nF", "C14663", "NRST", "GND", (162.56, 195.58), (40.5, 25.0, 90), mpn="CL10B104KB8NNNC")
P("SW1", "Switch:SW_Push", "RESET", "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A", "C318884",
  "TS-1187A-B-A-B", {"1": "NRST", "2": "GND"}, (180.34, 195.58), (60.0, 5.0, 0))
P("SW2", "Switch:SW_Push", "BOOT", "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A", "C318884",
  "TS-1187A-B-A-B", {"1": "+3V3", "2": "BOOT_SW"}, (180.34, 210.82), (60.0, 33.0, 0))
R("R2", "1k", "C21190", "BOOT_SW", "SWCLK", (200.66, 210.82), (55.0, 30.0, 90))
R("R3", "1k", "C21190", "LED1_DRV", "LED1_A", (271.78, 40.64), (49.0, 2.5, 0))
P("D5", "Device:LED", "Yellow", "LED_SMD:LED_0603_1608Metric", "C72038", "Yellow 0603 LED",
  {"1": "GND", "2": "LED1_A"}, (287.02, 45.72), (52.5, 2.5, 180))
R("R4", "1k", "C21190", "LED2_DRV", "LED2_A", (271.78, 60.96), (49.0, 5.0, 0))
P("D6", "Device:LED", "Red", "LED_SMD:LED_0603_1608Metric", "C2286", "Red 0603 LED",
  {"1": "GND", "2": "LED2_A"}, (287.02, 66.04), (52.5, 5.0, 180))
P("J3", "Connector_Generic:Conn_01x05", "SWD", HDR.format(n=5), "", "1x5 2.54mm header",
  {"1": "+3V3", "2": "SWCLK", "3": "GND", "4": "SWDIO", "5": "NRST"},
  (281.94, 177.8), (60.0, 15.0, 90), jlc=False, desc="SWD: 3V3 SWCLK GND SWDIO NRST")
P("J4", "Connector_Generic:Conn_01x03", "UART", HDR.format(n=3), "", "1x3 2.54mm header",
  {"1": "GND", "2": "UART_TX", "3": "UART_RX"}, (281.94, 200.66), (48.0, 34.5, 0), jlc=False,
  desc="Debug UART (USART2): GND TX RX")
P("J5", "Connector_Generic:Conn_01x06", "GPIO", HDR.format(n=6), "", "1x6 2.54mm header",
  {"1": "+3V3", "2": "GPIO_PB6", "3": "GPIO_PB7", "4": "GPIO_PB8", "5": "GPIO_PB9", "6": "GND"},
  (281.94, 223.52), (60.0, 23.0, 90), jlc=False, desc="Spare GPIO (PB6/PB7 = I2C1 or USART1)")

# ---------------------------------------------------------------- CAN1 / CAN2
def can(n, y0, pcby):
    P(f"U{3 if n == 1 else 5}", "Interface_CAN_LIN:SN65HVD230", "SN65HVD230DR", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
      "C12084", "SN65HVD230DR",
      {"1": f"CAN{n}_TX", "2": "GND", "3": "+3V3", "4": f"CAN{n}_RX", "6": f"CAN{n}_L", "7": f"CAN{n}_H",
       "8": f"CAN{n}_STBY"}, (345.44, y0 + 20.32), (27.0, pcby, 90))
    C(f"C{13 if n == 1 else 14}", "100nF", "C14663", "+3V3", "GND", (322.58, y0), (31.5, pcby - 4.5, 0),
      mpn="CL10B104KB8NNNC")
    R(f"R{5 if n == 1 else 7}", "10k", "C25804", f"CAN{n}_STBY", "+3V3", (332.74, y0), (33.0, pcby + 2.0, 90))
    P(f"U{4 if n == 1 else 6}", "Power_Protection:NUP2105L", "NUP2105L", "Package_TO_SOT_SMD:SOT-23", "C14486",
      "NUP2105LT1G", {"1": f"CAN{n}_H", "2": f"CAN{n}_L", "3": "GND"}, (375.92, y0 + 20.32), (20.0, pcby, 270))
    R(f"R{6 if n == 1 else 8}", "120R", "C22787", f"CAN{n}_H", f"CAN{n}_TERM", (391.16, y0 + 15.24),
      (20.0, pcby + 4.0, 0))
    P(f"JP{n}", "Jumper:SolderJumper_2_Open", "TERM", "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm",
      "", "solder jumper (bridge = 120R termination on)", {"1": f"CAN{n}_TERM", "2": f"CAN{n}_L"},
      (391.16, y0 + 33.02), (20.0, pcby - 4.0, 0), jlc=False)
can(1, 40.64, 23.5)
can(2, 106.68, 33.0)

# ---------------------------------------------------------------- USB
P("J1", "Connector:USB_C_Receptacle_USB2.0_16P", "USB-C", "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
  "C165948", "HRO TYPE-C-31-M-12",
  {"A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
   "A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND", "S1": "GND",
   "A5": "USB_CC1", "B5": "USB_CC2", "A6": "USB_DP", "B6": "USB_DP", "A7": "USB_DM", "B7": "USB_DM"},
  (330.2, 190.5), (71.0, 18.0, 90))
R("R9", "5.1k", "C23186", "USB_CC1", "GND", (370.84, 167.64), (64.5, 12.0, 90))
R("R10", "5.1k", "C23186", "USB_CC2", "GND", (381.0, 167.64), (64.5, 24.0, 90))
P("U7", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6", "C7519", "USBLC6-2SC6",
  {"1": "USB_DM", "6": "USB_DM", "3": "USB_DP", "4": "USB_DP", "2": "GND", "5": "VBUS"},
  (370.84, 213.36), (63.5, 18.0, 90))
C("C15", "4.7uF", "C1779", "VBUS", "GND", (398.78, 208.28), (68.0, 27.0, 0), fp=C0805, mpn="CL21A475KAQNNNE")

# ---------------------------------------------------------------- sense + aux output
R("R11", "100k", "C25803", "VBATF", "VBAT_SENSE", (40.64, 160.02), (22.5, 12.5, 90))
R("R12", "10k", "C25804", "VBAT_SENSE", "GND", (58.42, 160.02), (24.5, 12.5, 90))
C("C16", "100nF", "C14663", "VBAT_SENSE", "GND", (76.2, 160.02), (26.5, 12.5, 90), mpn="CL10B104KB8NNNC")
R("R13", "100k", "C25803", "AUX_IN", "AUX_SENSE", (40.64, 190.5), (13.0, 33.5, 0))
R("R14", "10k", "C25804", "AUX_SENSE", "GND", (58.42, 190.5), (16.5, 36.5, 90))
C("C17", "100nF", "C14663", "AUX_SENSE", "GND", (76.2, 190.5), (18.5, 36.5, 90), mpn="CL10B104KB8NNNC")
P("Q1", "Transistor_FET:AO3400A", "AO3400A", "Package_TO_SOT_SMD:SOT-23", "C20917", "AO3400A",
  {"1": "AUX_GATE", "2": "GND", "3": "AUX_OUT"}, (99.06, 223.52), (10.0, 28.0, 0))
R("R15", "100R", "C22775", "AUX_DRV", "AUX_GATE", (73.66, 220.98), (14.5, 28.0, 0))
R("R16", "100k", "C25803", "AUX_GATE", "GND", (86.36, 233.68), (12.5, 30.5, 0))
P("D7", "Diode:SS34", "SS34", "Diode_SMD:D_SMA", "C8678", "SS34",
  {"1": "VBATF", "2": "AUX_OUT"}, (119.38, 213.36), (4.5, 30.0, 90))

# ---------------------------------------------------------------- mechanical
P("H1", "Mechanical:MountingHole", "M3", "MountingHole:MountingHole_3.2mm_M3", "", "", {},
  (40.64, 254.0), (3.5, 3.5, 0), jlc=False)
P("H2", "Mechanical:MountingHole", "M3", "MountingHole:MountingHole_3.2mm_M3", "", "", {},
  (55.88, 254.0), (71.5, 36.5, 0), jlc=False)

BOARD_W, BOARD_H = 75.0, 40.0

# no-connect pins (everything else unused on MCU gets auto NC)
NOTES = [
    ((20.32, 25.4), "POWER: 12V > PTC > TVS > OR-ing > 3.3V LDO"),
    ((175.26, 25.4), "MCU: STM32G0B1 (2x FDCAN, USB FS crystal-less, 128K flash)"),
    ((302.26, 25.4), "CAN1 (FDCAN1 PD0/PD1) - default transceiver standby via R5 pull-up"),
    ((302.26, 93.98), "CAN2 (FDCAN2 PB0/PB1) - default transceiver standby via R7 pull-up"),
    ((302.26, 160.02), "USB-C (device, 5.1k Rd on CC)"),
    ((20.32, 147.32), "SENSE: VBAT / AUX_IN dividers 100k:10k (ADC full scale ~36V)"),
    ((20.32, 208.28), "AUX_OUT: low-side switch, 30V MOSFET, flyback to VBATF"),
    ((160.02, 147.32), "CLOCK / RESET / BOOT"),
    ((261.62, 30.48), "STATUS LEDs"),
    ((261.62, 165.1), "DEBUG + EXPANSION HEADERS (hand-solder)"),
]
