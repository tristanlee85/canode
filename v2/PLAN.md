# canode V2: architecture overview and plan

**Status (2026-11-09):** planning only. V1 (rev A) is designed but not ordered, and nothing here has been built or tested. This document makes no part choices: every block is described by what it must do, and the workstream that owns it picks the parts.

**How to use this.** Sections 1–4 are the shared picture. Section 5 says which decisions wait on V1 bench results. Section 6 splits the work into workstreams, each written so an agent can pick it up without the conversation that produced this plan. Section 7 lists the decisions that are T's to make.

V2 replaces the "rev B follow-ups" in `CLAUDE.md` (the fail-safe bypass and saved feature profiles). Both are part of V2.

## 1. Intent (confirmed with T, 2026-11-09)

| | |
|---|---|
| **Outcome** | A second-generation canode that can be left in a vehicle: fail-safe inline, protected against real automotive faults, able to record locally, and able to restore saved feature settings by itself. |
| **User** | T first, on the 2021 Bronco Sport, 2019 Silverado 3500 and 2016 BMW F80, plus a few more vehicles later. After that, do-it-yourselfers who buy a mostly finished unit and flash and adjust it themselves. |
| **Core job: feature recall** | canode watches a feature's state on the bus, remembers the last setting, and re-applies it at the next power-on as if the driver had pressed the button. Examples: auto start-stop, cruise-control enable, heated seats, heated steering wheel, climate settings. |
| **Discovery mode** | Local recording is for learning an unfamiliar vehicle through a guided series of tests (press a button, see what moved). It is not always-on logging. |
| **Interface** | USB console now. Wireless is wanted, for a phone app that later replaces most console work. |
| **Scope of change** | A significant redesign is acceptable. V2 builds on what V1's design work found, including its known limits. |
| **Not the goal** | Coverage of every vehicle; a certified, warrantied retail product; the phone app itself. |

## 2. V2 at a glance

```
              one T-harness at the vehicle's CAN gateway connector
   ┌────────────────────────────┬──────────────────────┬──────────────┐
 bus A, car side        bus A, gateway side          bus B          bus C
   │                            │                      │              │
   ├──── bypass (closed ────────┤                      │              │
   │     unless gatewaying)     │                      │              │
  CAN1                         CAN2                   CAN3           CAN4
  └──── intercepted pair ───────┘                    (tap)          (tap)
                │                                      │              │
                └───────────────  CAN MCU  ────────────┴──────────────┘
                     │            │           │              │
                state store   bulk storage   USB         radio module ─ ─ phone app
                (profiles,    (discovery    console      (off when        (later)
                last states)  recordings)                 asleep)

 12 V always-hot ─▶ input protection ─▶ low-quiescent rails
 Sense inputs · AUX_OUT · HARNESS_ID carry over from V1
```

- **One intercepted bus.** Two channels sit either side of a cut in one bus, as in V1. Firmware can pass, drop or rewrite frames in each direction.
- **Two tap channels.** Each sits on another bus as an ordinary node. A tap listens all the time and sends only when an armed profile says so. A tap does not cut the bus.
- **Four CAN channels in total.** V1 has two.
- **One tap point.** Everything connects at the vehicle's CAN gateway connector through one T-harness, which is already the project's direction.

**Why taps and not one switched channel.** Feature recall has to notice whenever the driver changes a setting mid-drive, so canode must keep listening to every bus that carries a remembered feature. A channel that switches between buses misses changes on the bus it isn't on. Switching also saves little hardware: each bus needs its own connector pins either way.

## 3. What carries over from V1 and what changes

| Area | V1 (rev A) | V2 |
|---|---|---|
| Tap point and harness scheme | Gateway connector, universal pigtail, per-vehicle T-harness, HARNESS_ID resistor | Same scheme; the connector and pigtail grow for two more buses |
| CAN channels | 2 (one intercepted bus) | 4 (one intercepted bus + two taps) |
| Bus path when canode is off, asleep or faulted | The intercepted bus is split | The bypass joins it, so the car behaves as stock |
| Transceivers | Classic CAN only; bus pins tolerate −4/+16 V | CAN-FD capable; bus pins survive a short to battery; low-power wake |
| MCU | STM32G0B1, two CAN controllers | To be chosen: four channels are needed (workstream 2) |
| Power input | Rated for a 35 V suppressed load dump; reverse battery trips a PTC close to its limit | Rated for an unsuppressed load dump; reverse battery blocked with no fault current |
| Sleep | About 1 mA estimated | Lower target (section 7) |
| Saved state | None: rules in RAM, gateway off at every boot | Profiles and last feature states saved; recall on wake |
| Recording | To a laptop over USB | Also to on-board bulk storage, with wall-clock time |
| Wireless | None | Radio module on board |
| Sense inputs, AUX_OUT | Dividers; bare MOSFET | Same functions, protected against shorts and an unsuppressed dump |
| Layout | 2-layer, autorouted | 4-layer, critical nets hand-routed |
| Firmware safety model | Nothing transmits without a console command after each boot | Nothing transmits unless a saved profile was explicitly armed (section 4.7) |
| Firmware code base | Bare-metal C, host-tested `lib/` | Carries over; the channel model and new modules are added |

## 4. Architecture

### 4.1 Channels and roles

| Channel | Role | Cuts the bus? | May transmit |
|---|---|---|---|
| CAN1 | Intercepted bus, car side | Yes (with CAN2) | Only while an armed gateway profile runs |
| CAN2 | Intercepted bus, gateway side | Yes (with CAN1) | Only while an armed gateway profile runs |
| CAN3 | Tap | No | Only recall messages from an armed profile |
| CAN4 | Tap | No | Only recall messages from an armed profile |

- Every channel powers up unable to drive its bus, held there by hardware until firmware has configured the controller. This is V1's rule, extended to four channels.
- The intercepted pair should stay on the MCU's own CAN controllers, because forwarding latency matters there. Taps are less time-critical.
- Which vehicle bus goes to which channel is set per vehicle by the T-harness and recorded in the vehicle profile.

### 4.2 Fail-safe bypass

**Requirement.** When canode is unpowered, asleep, resetting, crashed, unarmed or faulted, the two halves of the intercepted bus are joined as if canode were not there. They are separated only while firmware is actively gatewaying.

Design rules for the workstream:

1. **Normally closed.** With no power, the bus is joined.
2. **Held open by activity, not by a level.** Opening the bypass needs a continuously refreshed signal from healthy firmware, so a hung MCU or a stuck pin releases it.
3. **No forwarding while joined.** With the bypass closed, CAN1 and CAN2 are on the same bus. Firmware must stop forwarding before closing and must not start until it has opened, or frames loop.
4. **Switch when the bus is idle** where possible, to avoid corrupting a frame in progress.
5. **Readable state.** Firmware can read back whether the bypass is actually open or closed.
6. **Termination.** A joined bus has the car's own termination. A split bus may leave one segment unterminated. The workstream decides whether switched termination replaces the V1 solder jumpers.
7. **Signal integrity.** The bypass path and both transceiver stubs must not degrade the joined bus at 500 kbit/s, 1 Mbit/s or CAN-FD data rates.

**Sleep changes meaning.** In V1 a sleeping gateway leaves the two sides disconnected. In V2 a sleeping canode is bypassed, so the car wakes normally and no wake-up frame is lost. The cost is that the first frames after a wake pass unmodified until firmware is running and opens the bypass. Each profile has to tolerate that gap.

### 4.3 Power and protection

The board lives on an always-hot feed. Targets for the workstream to turn into numbers:

- **Survive without damage:** an unsuppressed load dump, a 24 V jump start, a reversed battery (indefinitely, with no fault current), ISO 7637-2 transients, and cranking dips without resetting.
- **Any connector pin shorted to battery or ground** must not damage the board. That includes the CAN pins, the sense inputs, AUX_OUT and HARNESS_ID.
- **Sleep current** low enough for a car parked for weeks. The target is T's call (section 7).
- **A rail for the transceivers** if the chosen parts need 5 V.
- **Power-fail hold-up:** enough stored energy, and an early warning of falling input, to close a recording and save feature state when power disappears.
- **USB:** sense VBUS, so a plug-in can wake the board and an unpowered host is not back-fed.

The V1 ngspice simulations (`validation/sim/`) and their pass criteria are the starting point for validating the new input stage.

### 4.4 MCU and CAN controllers

V2 needs four CAN channels; the STM32G0B1 has two. The two routes:

| Route | For | Against |
|---|---|---|
| An MCU with more CAN controllers built in | One driver for all channels; simplest firmware model | A port: clocks, pin map, HAL family, sleep and wake code |
| Keep the STM32G0B1, add external CAN controllers for the taps | V1 firmware and pin checks carry over; the intercepted pair is unchanged | Two kinds of CAN driver; extra parts; wake and timestamps differ per channel |

Selection criteria: four channels with CAN-FD; wake from the low-power mode on bus activity on every channel; enough pins for storage, radio link, bypass control and the existing I/O; headroom to forward a busy bus with rewriting while recording; how much of the V1 firmware carries over; availability for JLC assembly.

### 4.5 Storage and time

Two different stores with different needs:

| Store | Holds | Needs |
|---|---|---|
| **State store** | Vehicle profiles, the arming flag, the last state of each remembered feature | Small; written often (a setting can change many times per drive); must never be left corrupt by a power loss; wear must be planned for |
| **Bulk store** | Discovery recordings | Large; written fast in bursts; easy to get onto a computer or phone |

Rough sizing for the bulk store: two busy 500 kbit/s buses produce on the order of 100 KB/s, and four channels more, so a recording session runs to hundreds of megabytes per hour.

Recordings need wall-clock timestamps that keep counting through sleep. V1's timestamps stop while asleep.

### 4.6 Wireless

- A pre-certified radio module, so the radio does not create a certification problem of its own later.
- The radio is a peripheral of the CAN MCU. Only the CAN MCU touches the buses, and it applies the same safety rules to a wireless command as to a console command.
- The radio is powered down while the board sleeps unless T decides otherwise, because it would dominate sleep current.
- The wireless link carries the same command protocol as the USB console (section 4.7), so the phone app and the console are two front ends to one interface.
- Pairing and authorisation need a design. Anyone in radio range must not be able to arm a profile or send frames.

### 4.7 Firmware architecture

**Channel model.** "Car side / module side" becomes a list of channels with roles (section 4.1). Rules, counters, bitrates and safety state are per channel.

**Vehicle profile.** One per vehicle, selected by HARNESS_ID. It holds the bus-to-channel map, the bitrates, and the list of features. An unknown or missing harness ID means listen-only.

**Feature.** Each feature in a profile describes:

| Field | Meaning |
|---|---|
| Bus | Which channel carries it |
| State signal | How to read the feature's current state from bus traffic |
| Action | How to change it: send the frames a button press would produce (works on a tap or the intercepted bus), or rewrite frames in transit (intercepted bus only) |
| Trigger | When to act: after wake, after ignition on, after a delay, once a precondition is seen |
| Verify | How to confirm the state changed; how many retries; what to do on failure |
| Remember policy | Restore the last state, or always force a fixed state |

**Recall loop.** While awake, track each remembered feature's state and save changes to the state store. After a wake, for each feature whose saved state differs from the observed state, run its action when its trigger fires, then verify.

**Safety model.** V1's rule is that nothing transmits without a console command after every boot. V2 keeps the principle and moves the consent:

- A profile transmits only after the user has explicitly armed it. Arming is stored, is per vehicle profile, and can be revoked.
- An unarmed board, an unknown harness, or any fault (bus-off, failed verify beyond its retries, storage error, brown-out) means listen-only with the bypass closed.
- Hardware still holds every channel passive until firmware is running.
- During development, the rule in `CLAUDE.md` still applies: no transmission on a real vehicle bus without T's explicit OK for that test.

**Discovery mode.** A guided capture: record all channels to the bulk store, mark the moments the user performs each test action, then compare. `tools/canlog` already does the byte-diff on a computer; discovery mode supplies it with marked, multi-bus recordings.

**Command protocol.** One machine-readable protocol for USB and wireless, with the human console as a thin layer over it.

**Firmware update.** Do-it-yourself users flash their own builds, so updating must be simple over USB and must not be able to brick the unit. Whether updates are also offered over the wireless link is open.

Much of this does not need V2 hardware: profiles, the feature model, the recall loop, the state store format and the command protocol can be built and host-tested now, and run on V1 or the Nucleo with two channels.

### 4.8 Connector and harness

- J2 gains at least four pins for the two tap buses. The universal inline connector and pigtail grow to match.
- Keep the V1 signal set (power, grounds, the intercepted pair, three sense inputs, AUX_OUT, HARNESS_ID).
- Each T-harness now brings up to three buses from the gateway connector. A vehicle that needs fewer leaves tap pins unconnected.
- The existing harness records (`hardware/harness/<vehicle>.md`) gain a bus-to-channel table.
- **Non-standard buses.** The Silverado's low-speed bus is single-wire CAN, which a normal two-wire transceiver cannot use. Whether a tap should support it is open (section 7).

### 4.9 Board, enclosure and manufacturing

- Four layers, with the crystal, USB, CAN and power-input nets routed by hand.
- Still built by JLC with basic or preferred parts where possible. Whether V2 still fits Economic assembly is for the layout workstream to report.
- Production and do-it-yourself access: test pads for programming and test, a unique serial number per unit, USB flashing without opening the case.
- The enclosure is revised for the new connector and any antenna keep-out. The V1 enclosure pipeline (`hardware/enclosure/`) carries over.
- The V1 validation plan (`validation/README.md`) is re-run in full for V2.

## 5. Two paths: what waits on V1

T has not decided whether to order V1. The plan works either way.

**What only V1 hardware (or a bench stand-in) can tell V2:**

| V1 result | V2 decision it feeds |
|---|---|
| First captures at each vehicle's gateway: which buses exist, their bitrates, whether any is CAN-FD or single-wire, which bus carries each feature | Channel count, tap transceiver types, connector pin count |
| Forwarding latency from the main loop on a busy bus | MCU headroom; whether forwarding moves to interrupt context |
| Sleep current and wake on bus activity | Wake design and the sleep-current target |
| Whether hardware listen-only (`rslisten high`) works and proves useful | Whether V2's transceivers must keep a hardware silent mode |
| +3V3 behaviour during a crank dip | Hold-up sizing |
| How the gateway module tolerates gaps and lost frames around sleep | Bypass timing; profile wake gap |
| Crystal start-up, USB enumeration, QFN assembly | Confidence in blocks carried over unchanged |
| J2 pin order, enclosure fit, harness handling in the car | Connector and enclosure revision |

**Path A: V1 is ordered and works.** V1 becomes the capture and firmware-development unit. Workstreams 0, 1 and 7 start now; the V2 schematic is frozen only after the first vehicle captures.

**Path B: V1 is skipped, or fails.** The NUCLEO-G0B1RE with two transceiver breakouts stands in for captures and firmware work. V2 then carries all the first-hardware risk, so the two riskiest new blocks (the bypass and the power input) are proven on the bench or in simulation before layout, and the first V2 order is a small one.

**Decisions that wait on neither path:** the feature and profile model, the safety model, the state store format, the command protocol, the protection targets, and the two-stores split.

## 6. Workstreams

Each is a self-contained brief. "Gated" means it should not be finalised before the named input exists.

| # | Workstream | Goal | Deliverable | Depends on | Gated on |
|---|---|---|---|---|---|
| 0 | **Vehicle research** | For each target vehicle: the gateway module, its connector pinout, every bus on it (type, bitrate), and which bus each wanted feature probably lives on | `hardware/harness/<vehicle>.md` per vehicle | Service information | Captures, for confirmation |
| 1 | **Requirements** | Turn sections 4.2–4.6 into numbers: fault list and levels, sleep-current target, temperature range, recording duration, latency budget | `v2/requirements.md` | T's decisions (section 7) | — |
| 2 | **Channel and MCU architecture** | Choose between the two routes in 4.4 against its criteria; produce the V2 pin map | `v2/mcu.md` with the comparison, the choice and the pin map | 1 | Latency result; captures |
| 3 | **Bus interface** | Transceiver class for the intercepted pair and the taps; bus-pin protection; termination scheme | `v2/bus-interface.md` | 1, 2 | Captures; listen-only result |
| 4 | **Bypass** | A bypass meeting the seven rules in 4.2, with its control and read-back circuit and its switching sequence | `v2/bypass.md`, plus a bench or simulation result | 1, 3 | Gateway gap tolerance |
| 5 | **Power input and rails** | An input stage and rails meeting 4.3, simulated against the V1 test set plus the new targets | `v2/power.md` and simulation reports | 1, 3 (rail voltages) | Crank-dip and sleep results |
| 6 | **Storage and time** | The state store and the bulk store per 4.5; wall-clock time; power-fail behaviour | `v2/storage.md` | 1, 2, 5 (hold-up) | — |
| 7 | **Firmware: profiles and recall** | The channel model, vehicle profiles, feature model, recall loop, arming and safety model, state store format. Host-tested; runs on V1 or the Nucleo | Code in `firmware/lib/` with tests; `v2/firmware.md` | — (can start now) | — |
| 8 | **Firmware: discovery and protocol** | Discovery mode, the command protocol shared by USB and wireless, firmware update | Code and tests; protocol description in `v2/protocol.md` | 7; 6 for recording | — |
| 9 | **Wireless** | Radio module class, its link to the MCU, power control, pairing and authorisation | `v2/wireless.md` | 1, 2, 8 (protocol) | — |
| 10 | **Connector and harness** | The larger J2, universal connector and pigtail; the pinout; updated harness records | `v2/connector.md`; updated `hardware/harness/` | 0, 2 | Captures; V1 harness handling |
| 11 | **Schematic, layout, enclosure, validation** | The V2 KiCad project, 4-layer layout, revised enclosure, and the full validation plan re-run | KiCad project, fab outputs, validation reports | 2–6, 9, 10 | Everything above |
| 12 | **Phone app** | Later; not planned here | — | 8, 9 | — |

Order of work:

```
now:        0 vehicle research   1 requirements   7 firmware: profiles and recall
then:       2 MCU ─▶ 3 bus interface ─▶ 4 bypass
                 └─▶ 5 power   6 storage   10 connector
            8 firmware: discovery and protocol ─▶ 9 wireless
last:       11 schematic, layout, enclosure, validation        later: 12 app
```

## 7. Decisions for T

| # | Decision | Proposal |
|---|---|---|
| 1 | Order V1, or skip to V2? | Open. Decide once workstream 2 shows how much of V1 carries over. |
| 2 | Sleep-current target | Under 0.5 mA with the radio off, about half of V1's estimate. |
| 3 | Design for an unsuppressed load dump and 24 V jump starts? | Yes. |
| 4 | Must CAN-FD work in V2, or only not be ruled out? | FD-capable transceivers and controllers; FD tested only when a target vehicle needs it. |
| 5 | Should a tap support single-wire CAN (Silverado low-speed bus)? | Decide after Silverado research shows which bus carries the wanted features. |
| 6 | May taps transmit at all? | Yes, recall messages only, from an armed profile. |
| 7 | Does arming over wireless need a physical action on the unit? | Yes, a button press, so radio range alone is never enough. |
| 8 | Is the radio off during sleep? | Yes. |
| 9 | Firmware updates over wireless, or USB only? | USB only for V2. |
| 10 | Where do V2's KiCad files live? | A separate project beside V1's, so V1 stays buildable. |

## 8. Out of scope for V2

- Coverage of every vehicle or bus type. LIN, FlexRay and automotive Ethernet stay out.
- Intercepting more than one bus at a time.
- Certification and compliance testing. The radio module and 4-layer layout are chosen so they are not ruled out later.
- The phone app. V2 provides the radio and the protocol it will use.
- Always-on logging.
- Writing anything to the vehicle's modules. Unplugging the harness still restores stock.
