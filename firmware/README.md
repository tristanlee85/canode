# Firmware

Bare-metal C for the STM32G0B1, built with `arm-none-eabi-gcc` and CMake. It uses ST's HAL for clocks, GPIO and FDCAN, and TinyUSB for the USB virtual serial port. One build produces two images:

- **`canode`**: the rev A board.
- **`nucleo_g0b1re`**: an ST NUCLEO-G0B1RE, for trying the firmware before the PCB arrives.

**Status:** milestones 1–4 are written, plus a gateway skeleton for milestone 5. It builds with no warnings, and the portable logic is unit-tested on the host. **Nothing has run on hardware yet.** See *Untested until hardware* below.

## Safety model (read this first)

The board sits inline on a vehicle bus, so the firmware is built to be silent unless you explicitly ask otherwise. The rules are also written at the top of `src/can_drv.c`.

1. **Transceivers start in standby.** After reset, the 10k pull-ups hold Rs (PD2, PB2) high. That is the SN65HVD230's standby mode: the driver is off and the receiver stays on, so the transceiver cannot drive the bus. Firmware drives Rs low only after that channel's FDCAN is configured and started; for normal (TX) mode, also only after the explicit opt-in command. Every reconfiguration puts the transceiver back in standby first. A HardFault drives both Rs pins high, then resets.
2. **The default is listen-only.** At boot both channels start in FDCAN **bus-monitoring** mode at 500 kbit/s. In that mode the controller receives frames but sends no ACKs, no error frames, and nothing else. A wrong bitrate does no harm.
   - **Rs while monitoring is a per-channel setting** (`rslisten`):
     - `low` (**the compiled default, current policy**): the transceiver is fully active, and FDCAN bus monitoring alone keeps us off the bus.
     - `high`: the transceiver stays in standby, so its driver is off in hardware. That gives two independent no-transmit layers. But TI specifies a slower receiver path in standby, so reception at 500k/1M is **not verified yet**.
   - **Bring-up step 7 (CAN) in `validation/README.md` decides the default.** To change it, edit the one line `BOARD_CAN_RS_LISTEN_DEFAULT` in `src/board.h`, or run `rslisten <can1|can2|all> high` at run time.
   - TX-capable modes always drive Rs low, whatever `rslisten` says.
3. **Transmitting always takes an explicit command that names the channel.** Only these do it, and each prints a warning:
   - `mode can1 normal` / `mode can2 normal`: one channel at a time; `all` is refused.
   - `selftest ext can1 can2`: a bench test that transmits on both channels.
   - `gw on`: forwards frames, so it requires both channels to be in normal mode already.
   - `send`: only works on a channel that is already in normal mode.
4. **Nothing returns to a transmitting mode by itself.** After a bus-off, a bitrate change or a self-test, the channel comes back in **monitor** mode. The gateway turns off when either channel leaves normal mode. A reboot restores the defaults: both channels in monitor mode, gateway off.
5. While any channel can transmit, LED1 blinks fast (5 Hz instead of 1 Hz).
6. **Sleep never changes this.** The board only auto-sleeps if nothing has been transmit-enabled since boot. On waking it restores each channel to listen-only monitor mode through the same path as boot: Rs stays high until the controller is running. See [Sleep](#sleep-stop-1).

The ROM bootloader (blank chip, or the `dfu` command) probes FDCAN1 on PD0/PD1. That is harmless: the transceiver stays in standby, so the bootloader cannot reach the bus.

## Pin map (validated by `make pins` against ST's pin data)
| Function | Pin | AF / mode |
|---|---|---|
| FDCAN1 RX / TX | PD0 / PD1 | AF3 |
| CAN1 transceiver Rs | PD2 | GPIO out; LOW = active, HIGH/float = standby (10k pull-up) |
| FDCAN2 RX / TX | PB0 / PB1 | AF3 |
| CAN2 transceiver Rs | PB2 | GPIO out, same as above |
| USB DM / DP | PA11 / PA12 | USB (HSI48 + CRS, no crystal needed) |
| HSE | PF0 / PF1 | 12 MHz crystal |
| VBAT sense | PA0 | ADC1_IN0, V = raw × 3.3 / 4095 × 11 |
| AUX_IN sense | PA1 | ADC1_IN1, same scaling |
| AUX_OUT gate | PA8 | GPIO or TIM1_CH1 (AF2) |
| LED1 / LED2 | PA5 / PA6 | GPIO, active high |
| Debug UART | PA2 TX / PA3 RX | USART2 (AF1) |
| Spare | PB6 / PB7 / PB8 / PB9 | PB6/PB7 = I2C1 (AF6) or USART1 |
| SWD | PA13 / PA14 | default after reset; PA14 is also BOOT0 |

Board differences live in `src/board.h`. The firmware does not use VBAT, AUX_IN or AUX_OUT yet.

## Clock plan
```
HSE 12 MHz / M=3 = 4 MHz -> x N=80 -> VCO 320 MHz
    PLLR /5 = 64 MHz  SYSCLK (AHB = APB = 64 MHz, 2 flash wait states)
    PLLQ /8 = 40 MHz  FDCAN kernel clock
HSI48 + CRS (synced to USB start-of-frame) -> USB 48 MHz
TIM2 = 1 MHz free-running counter -> microsecond timestamps
```
If the crystal doesn't start within 100 ms, the firmware falls back to HSI16 / M=4 and keeps the same output frequencies. `status` then reports `HSI16 (HSE FAILED to start)`. HSI16 is only ±1 %, which is too loose for a real bus, but USB still works, so you can diagnose the problem.

### CAN bit timing (40 MHz kernel clock, 87.5 % sample point)
| Bitrate | Prescaler | tq/bit | TSEG1 | TSEG2 | SJW | Sample point |
|---|---|---|---|---|---|---|
| 125k | 2 | 160 | 139 | 20 | 20 | 87.5 % |
| 250k | 1 | 160 | 139 | 20 | 20 | 87.5 % |
| 500k | 1 | 80 | 69 | 10 | 10 | 87.5 % |
| 1M | 1 | 40 | 34 | 5 | 5 | 87.5 % |

How these are computed:
- Bit time = (1 + TSEG1 + TSEG2) × prescaler / 40 MHz.
- Sample point = (1 + TSEG1) / tq-per-bit.
- `lib/bittiming.c` picks the smallest prescaler that gives an exact bitrate within the FDCAN limits (TSEG1 ≤ 256, TSEG2 ≤ 128).
- At 125k a prescaler of 1 would need TSEG1 = 279, which is over the limit, so it uses 2.
- Any other rate up to 1M works if it is within 0.1 %, e.g. `83.333k`.
- The unit tests check this table.

## Build

Run `scripts/setup_mac.sh` once. Building also needs `arm-none-eabi-gcc` and `cmake` (`brew install cmake`).
```
cmake -S firmware -B firmware/build        # first run downloads deps (~14 MB) into firmware/.deps/
cmake --build firmware/build -j            # -> firmware/build/canode.{elf,bin,hex}, nucleo_g0b1re.{elf,bin,hex}
firmware/test/run_tests.sh                 # host unit tests (or: cmake --build firmware/build --target host-tests)
```
Current size (MinSizeRel, the default build type):
- `canode`: 40,944 B flash (31 % of 128 KB), 21,272 B RAM.
- `nucleo_g0b1re`: 39,968 B flash, 21,264 B RAM.

Most of the RAM is buffers: the 256-frame RX ring, the 4 KB USB and UART TX buffers, and a 4 KB stack.

### Dependencies (pinned by SHA-256 in `cmake/deps.cmake`)
| Package | Version | Used for |
|---|---|---|
| [ST cmsis-device-g0](https://github.com/STMicroelectronics/cmsis-device-g0) | v1.4.5 | register headers, startup file, `SystemInit` |
| [ST stm32g0xx-hal-driver](https://github.com/STMicroelectronics/stm32g0xx-hal-driver) | v1.4.7 | RCC, GPIO, PWR, FDCAN |
| [Arm CMSIS 6](https://github.com/ARM-software/CMSIS_6) | v6.4.0 | Cortex-M0+ core headers |
| [TinyUSB](https://github.com/hathach/tinyusb) | 0.21.0 | USB device stack + CDC (STM32 "FSDEV" driver) |

Why TinyUSB rather than ST's USB middleware:
- It drives the G0's USB peripheral directly, including the G0B1's 32-bit packet memory.
- It is maintained on GitHub with tagged releases.
- It needs no CubeMX-generated glue, and its CDC API is a few calls.

USART2 and TIM2 are driven by register, because the HAL adds nothing there.

USB IDs: `1209:0001` is the [pid.codes](https://pid.codes/1209/0001/) test PID. It is fine for private use; get a real PID before distributing boards. The USB serial number is the chip's unique ID.

## Flash

**canode over USB (no debugger).** A blank STM32G0 boots into ST's ROM DFU bootloader. On a programmed board, type `dfu` in the shell to get back into it.
```
dfu-util -l                                                    # expect 0483:df11 "STM32 BOOTLOADER"
dfu-util -d 0483:df11 -a 0 -s 0x08000000:leave -D firmware/build/canode.bin
```

**SWD (canode J3, or the Nucleo's on-board ST-LINK).** Any one of these works:
```
st-flash --reset write firmware/build/canode.bin 0x08000000          # stlink (brew install stlink)
STM32_Programmer_CLI -c port=SWD -w firmware/build/canode.hex -v -rst  # STM32CubeProgrammer
pyocd flash -t stm32g0b1ceux firmware/build/canode.hex                 # pyOCD (pip install pyocd; pyocd pack install stm32g0b1)
```

**Nucleo.**
- Easiest: copy `nucleo_g0b1re.bin` onto the `NOD_G0B1RE` USB drive that the ST-LINK provides.
- Or use any of the SWD commands above, with `nucleo_g0b1re.bin` / `.hex`. For pyOCD, use target `stm32g0b1retx`.

## Talk to it

**USB:** the board shows up as `/dev/cu.usbmodem*` on a Mac. The baud setting is ignored.

**UART:** USART2 at 115200 8N1. On canode it is on header J4; on the Nucleo it is the ST-LINK virtual COM port.

Each port has its own shell. A command's reply goes to the port that sent it.
```
screen /dev/cu.usbmodem* 115200        # quit: Ctrl-A then K
```

| Command | What it does |
|---|---|
| `help` | List commands |
| `status` | Firmware version, clock source, each channel's mode, bitrate and error state (TEC/REC, bus-off), counters, gateway and log state |
| `mode <can1\|can2\|all> <off\|monitor>` | Stop a channel, or put it in listen-only bus monitoring (the default) |
| `mode <can1\|can2> normal` | **Transmit-capable**: ACKs, error frames, `send`, gateway. Prints a warning. One named channel only. |
| `bitrate [<can1\|can2\|all> <rate>]` | Show or set the bitrate (`125k`, `250k`, `500k`, `1M`, `83.333k`, ...). A channel in normal mode drops back to monitor. |
| `rslisten <can1\|can2\|all> <high\|low>` | Rs state while monitoring: `low` = transceiver active (default), `high` = transceiver standby, driver off in hardware. Applies immediately to a monitoring channel. Shown in `status`. |
| `log on [can1\|can2\|all]` / `log off` | Stream received frames to this port in candump format. No prompt is shown while streaming. |
| `time [unix_seconds[.frac]]` | Show or set the wall clock used for timestamps (default: seconds since boot) |
| `send <can1\|can2> <id>#<data>` | Transmit one frame, e.g. `123#DEADBEEF`, `18DAF110#0211`, `7DF#R`. The channel must be in normal mode. |
| `selftest [int]` | Internal loopback on both channels at 125k/250k/500k/1M. Never touches the bus. |
| `selftest ext can1 can2` | **Transmits.** Bench test, CAN1→CAN2 and back, at all four rates. Needs JP1+JP2 bridged and CAN1 wired to CAN2. canode only. |
| `gw [status\|list]`, `gw add ...`, `gw del <n>`, `gw clear` | Manage gateway rules (see below) |
| `gw on` / `gw off` | Turn forwarding on or off. `gw on` requires both channels in normal mode. |
| `sleep` | Sleep status: on/off, timeout, bus and console idle time, why it is awake, sleep/wake counts, last wake source |
| `sleep on\|off` / `sleep timeout <s>` | Turn auto-sleep on or off (default on); set the idle time (5–86400 s, default 60). Not saved across reset. |
| `sleep now` | Sleep immediately, even with USB connected. Refused while a channel can transmit. |
| `echo <on\|off>` | Turn local echo and the prompt on or off (off for scripts) |
| `reset` / `dfu` | Reboot / reboot into the ROM USB DFU bootloader |

### Capture (milestone 4)
The stream uses the can-utils `candump -l` format: `(1699999999.123456) can1 123#DEADBEEF`.
- Standard IDs are always 3 hex digits and extended IDs always 8. That is how `tools/canlog`, SavvyCAN and can-utils tell them apart.
- `can1` is the car side and `can2` is the module side, matching the board.

To save a capture with real Unix timestamps:
```
python3 firmware/scripts/capture.py /dev/cu.usbmodem* -o logs/drive.log   # Ctrl-C to stop
python3 tools/canlog/canlog.py --replay logs/drive.log
```
`canlog` currently ignores the interface name, so a two-channel capture shows both buses merged. Use `--chan can1` to capture one side.

Throughput limits:
- USB CDC can carry a fully loaded 1 Mbit/s bus (about 8000 frames/s, ~360 KB/s).
- The UART at 115200 manages only about 250 frames/s.
- Frames are counted when lost: `status` shows `hw-lost` (overrun in the 3-deep FDCAN FIFOs) and `rx ring dropped` (the main loop fell behind).

### Gateway rules (milestone 5 skeleton)
When the gateway is on, each frame received on one channel is checked against the rules in order, and the first match decides what happens. A frame that matches no rule is forwarded unchanged.
```
gw add <from> <match> <action> [id=<hex>] [data=<pattern>]
  from    can1 | can2 | any        side the frame arrived on (it is sent out the other side)
  match   *  |  123  |  18DAF110  |  123/7F0  (ID/mask; 3 hex digits = standard, 8 = extended)
  action  pass | drop | rewrite
  data=   2 chars per byte, per nibble: hex digit = replace, '.' = keep.  data=..01 sets byte 1 to 0x01
```
Example: `gw add can1 3B3 rewrite data=....0.` clears the high nibble of byte 2 of ID 0x3B3 on its way from the car to the module.

Rules live in RAM and are lost on reset (saving them to flash is a later step). Forwarding runs from the main loop, so it adds some latency; measure it once hardware exists.

## Sleep (Stop 1)

The board is meant to be wired to an always-hot feed (J2 pin 1 straight from the gateway harness). Running at 64 MHz it draws about 9 mA. When the car's buses go quiet, the firmware puts the MCU into **Stop 1** and wakes it on CAN activity.

### When it sleeps
The policy is in `lib/power.c`, which is host-tested in `test/test_power.c`. Auto-sleep needs **all** of the following:
- Sleep is on (`sleep on`, the default; `BOARD_SLEEP_DEFAULT_ENABLED` in `board.h`).
- No frame has been received on either channel for the timeout (default 60 s, `sleep timeout <s>`).
- No console input on USB or UART for the timeout. Plugging or unplugging USB also counts as console input.
- USB is not mounted by a host (`tud_mounted()`). With a laptop connected, the board never auto-sleeps.
- No channel is transmit-capable right now (normal mode, gateway on).
- **Transmit has not been enabled at any point since boot.** That includes `mode canN normal` and `selftest ext`. Once T has explicitly enabled transmit, auto-sleep stays off until a reboot. The reason: a wake-up only ever restores listen-only mode, so a gateway or transmit setup would silently stop working after a sleep. As a result, an installed gateway keeps drawing ~9 mA.
- At least one channel is in monitor mode. With both channels off, nothing but the UART could wake it.

`sleep now` overrides everything except a channel that can currently transmit; in that case it refuses and says why. `sleep` and `status` show what is keeping the board awake.

### What happens (src/sleep.c)
1. A message goes to both consoles, and the UART drains.
2. Both FDCANs are stopped, and both Rs pins are driven **high**. That is transceiver standby: the driver is off and the receiver stays on, so RXD still goes low on a dominant bit. The SN65HVD230 has no lower-power mode than standby. The TX pins are parked as recessive GPIO outputs.
3. USB is detached and powered down (the host sees an unplug), and LED1/LED2 are turned off.
4. The wake-up sources are armed. A last check runs with interrupts masked: if a frame reached the RX ring, or an RX line is dominant right now, the board aborts and stays awake for another timeout. After that, WFI with LPMS = Stop 1. Flash is powered down in Stop.
5. On wake the chip is running on HSI16. The firmware reruns `system_clock_init()`: HSE crystal, PLL to 64 MHz, the 40 MHz FDCAN kernel clock, and HSI48 + CRS for USB. It then restarts every channel that was listening, in **bus-monitoring mode, at its previous bitrate and `rslisten` setting**, through the same `chan_configure()` path as boot: Rs goes low only after the controller is running. USB is restarted and the wake source is recorded. The board then stays awake for at least one timeout.

### Wake sources and the EXTI0 problem
CAN1 RX is PD0 and CAN2 RX is PB0. Both are **EXTI line 0**, and EXTICR routes each EXTI line to one port only, so GPIO interrupts can't watch both. The fix used here:

| Source | How | Notes |
|---|---|---|
| CAN1 (car side) | PD0 as GPIO input, EXTI0 (port D), falling edge | dominant = RXD low |
| CAN2 (module side) | PB0 is also **COMP3_INP** (IO1, per ST's pin data and `stm32g0xx_ll_comp.h`). COMP3 compares it against VREFINT (~1.2 V), and its output is **EXTI line 20**, falling edge. | The comparators keep running in Stop, so no GPIO line is needed. Medium-speed power mode. |
| UART key | PA3 (USART2 RX) as GPIO input, EXTI3, falling edge (start bit) | J4 on canode; the ST-LINK virtual COM port on the Nucleo. The key itself is lost. |
| RESET (SW1) | always | |

Only channels that were in monitor mode are armed. FDCAN itself is not a Stop-mode wake-up source on the G0, because its kernel clock stops.

**USB plug-in can't wake the board.** There is no VBUS-sense pin. Detecting the host's 15k pull-downs on D+/D− with an internal pull-up is marginal: about 0.7–1.2 V against a ~1 V input threshold. It would also make the host see a device attach. **If it's asleep and you need the USB console, press RESET (or send any character on the UART).**

### What you lose
- **The first frame(s) after a wake.** The FDCAN can't receive until the crystal and PLL are running again. Start-up is roughly 2–3 ms: HSE start-up (typ ~2 ms) plus PLL lock plus channel configuration. All three figures are **UNVERIFIED**, so measure them. On a waking car bus that is a handful of frames. This is acceptable for listen-only logging; it would not be for a gateway, which is one more reason the board never auto-sleeps once transmit was enabled.
- **Time while asleep.** TIM2 and SysTick stop in Stop mode, so `uptime` and candump timestamps don't advance while asleep. A log shows the sleep as a zero-length gap. If wall-clock time matters, run `time` again after a wake.
- **A misconfigured channel causes a wake loop.** If a monitored bus is active at the wrong bitrate, no frames are received, so the board sleeps, wakes on the first edge, stays up for a timeout, and repeats. That is harmless, but the board is effectively awake. `sleep` shows the wake count.

### Current budget while asleep (from the battery, at ~12.6 V)
| Item | Current | Source |
|---|---|---|
| STM32G0B1 in Stop 1, flash powered down, + COMP3 and the VREFINT scaler | a few µA to a few tens of µA | DS13560 §5.3.5 (Stop 1 supply current) and the COMP characteristics table. **UNVERIFIED:** ST's site blocked the datasheet download, so the exact figures and table numbers were not checked. Negligible either way. |
| 2 × SN65HVD230 in standby (Rs high) | 2 × 370 µA = **0.74 mA** | TI SN65HVD230 datasheet, standby supply current |
| VBAT divider R11 100k + R12 10k | 12.6 V / 110 kΩ = **0.11 mA** | schematic |
| TPS7B6933-Q1 LDO quiescent | ~15 µA | TI datasheet; also used in `validation/sim/board.inc` |
| Power LED D4 (green, LCSC C2297) + **R1 4.7 kΩ** on +3V3 | ~0.1–0.17 mA | R1 raised from 1 kΩ on 2026-11-09 (`validation/reports/2026-11-09_protection.md`). UNVERIFIED, measure it. Firmware can't turn it off. |
| LED1/LED2 | 0 (firmware turns them off) | |
| Rs 10k pull-ups (Rs driven high), PA3 internal pull-up | 0 | |
| **Total** | **~1.0–1.1 mA** | |

Compare ~9 mA awake. Leaving D4 unfitted saves another ~0.1–0.17 mA.

### Debugging
- A **Debug** build (`cmake -S firmware -B firmware/build-debug -DCMAKE_BUILD_TYPE=Debug`) sets `DBGMCU_CR.DBG_STOP`, so SWD stays attached in Stop. That keeps clocks running, so current measured with a Debug build means nothing.
- Release builds (the default MinSizeRel) drop the SWD connection while asleep. Connect under reset: hold RESET (SW1) while the debugger connects. Alternatively, wake the board first with `sleep off` from the UART.

### Untested until hardware (sleep)
- Everything above. In particular:
  - That COMP3 in medium-speed mode wakes the board on a real 500k/1M frame. If it doesn't, switch to high-speed `PWRMODE` in `src/sleep.c`.
  - That EXTI on PD0/PA3 wakes it.
  - That Rs stays high from sleep entry until after the controller restarts. Check on a scope.
  - USB re-enumeration after a wake.
  - Clock restore, including the HSE-failed fallback.
- Bench steps:
  1. Run `sleep timeout 5` with nothing on the buses, measure current at J2 (12 V), and compare it with the table.
  2. Feed frames on CAN1, then on CAN2, at 125k, 500k and 1M, and check `sleep` (last wake, wake count).
  3. Scope RXD1 against Rs1 to measure wake latency.

## Nucleo-G0B1RE notes
- **Clock.** It runs from HSI16, not a crystal. The HSE input only gets the ST-LINK's 8 MHz MCO if solder bridge SB17 is closed, and X3 is not fitted. ST's own Zephyr and TinyUSB board files also use HSI16.
- **No transceivers.** Use `selftest int`. `selftest ext` is refused on this board. The FDCAN and Rs pins are the same as on canode (PD0/PD1/PD2, PB0/PB1/PB2), on the morpho headers, if you want to wire up transceiver modules.
- **One LED.** LD4 on PA5 is LED1; there is no LED2.
- **UART.** The shell is on the ST-LINK virtual COM port (USART2).
- **USB.** The Nucleo has no USB device connector. To try the USB shell, wire a USB breakout to PA11 (D−, CN10-14), PA12 (D+, CN10-12) and GND.
- **Sleep.** Same policy as canode. It wakes on a key on the ST-LINK virtual COM port, or on CAN1 (PD0, internal pull-up) if you've wired a transceiver. CAN2 wake-up is disabled (`BOARD_WAKE_CAN2_COMP 0`), because PB0 would float in the analog mode the comparator needs. The ST-LINK keeps powering the board, so measure Stop current at the Nucleo's IDD jumper (see UM2324), not at USB.

## Layout
```
firmware/
  CMakeLists.txt        builds both boards; target host-tests runs the unit tests
  cmake/                toolchain file, pinned dependency list
  ld/stm32g0b1xb.ld     linker script (128 KB flash, 128 KB RAM; deliberately the smallest G0B1, so the same image runs on the 512 KB CEU6 and the Nucleo)
  lib/                  portable C, no HAL, unit-tested on the host:
                        bittiming, candump, frame_ring, gateway, parse, power (sleep policy), shell
  src/                  target code: board.h (board differences), system (clocks, time, DFU),
                        can_drv (FDCAN + safety rules), commands (shell), selftest, sleep (Stop 1), usb, uart, main
  test/                 host unit tests: run_tests.sh
  scripts/capture.py    save the candump stream to a file
```

## Untested until hardware
Everything in `src/`, in particular:
- HSE start-up and the HSI16 fallback.
- USB enumeration (TinyUSB on this chip) and CRS lock.
- FDCAN internal and external loopback at each rate.
- Rs sequencing, confirmed on a scope: Rs must stay high until the controller is running.
- Bus-off handling.
- The jump into DFU.
- Real throughput at 1 Mbit/s.
- Sleep / wake-up: see [Sleep](#sleep-stop-1).

Suggested order for bring-up:
1. Check `status` for the clock source.
2. Run `selftest`.
3. Run `selftest ext can1 can2` on the bench.
4. Listen to a known bus with `log on`.

**Rs-high reception test (decides the `rslisten` default).**
- Why not canode alone: a channel in monitor mode doesn't ACK. If canode's other channel is the only sender, it sees an ACK error and sends an error frame, which invalidates every frame. `selftest ext` can't test this.
- Instead, wire CAN1 and CAN2 in parallel onto the same live bus. That can be a bench bus with at least one other ACKing node (CANable, OBDLink, a module), or the car's bus. Terminate the bench bus once; leave JP1/JP2 open on the car.
- Set both channels to the same bitrate and leave both in monitor mode. Run `rslisten can1 low` and `rslisten can2 high`.
- Compare `rx`, `hw-lost` and `REC` in `status` (or `log on` and diff the two channels) at 125k, 250k, 500k and 1M.
- If `can2` matches `can1` frame for frame at every rate, `high` is safe to make the default.

## Milestones
1. Done, untested on hardware: clocks, LEDs, UART.
2. Done, untested on hardware: USB CDC and a command shell.
3. Done, untested on hardware: FDCAN internal loopback, then external CAN1↔CAN2 loopback.
4. Done, untested on hardware: bus-monitoring capture over USB in candump format.
5. Skeleton only: gateway: forwarding with filter and rewrite rules. Still to do: persistence, timing measurements, and per-direction counters.
6. Done, untested on hardware: Stop 1 sleep with wake-up on CAN1, CAN2 (via COMP3) and the UART.
