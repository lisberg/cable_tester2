# Cable Tester – Design Review & KiCad Realization Plan

Status: **Draft for discussion** · Scope: Rev A hardware (controller, 50‑ch bank card, backplane, fixture adapters)

This document has two parts:

1. **Engineering review** of the proposed architecture (STM32C071 + SPI shift‑register chains + muxed
   single‑point stimulus + parallel bitmap sense, 4 × 50‑channel banks, passive fixture adapters).
2. **A phased plan** to take it from spec to fabricated boards in KiCad, including repo layout,
   library strategy, hierarchy, layout reuse, rules, and CI.

---

## Part 1 – Design review

### 1.1 Verdict

The overall architecture is sound and well suited to production continuity testing: one active
stimulus point, everything else sensed in parallel, bitmaps compared against a netlist‑derived
expectation. The bank/adapter partitioning and the staged prototype plan (small proto → 50 → 200) are
exactly right.

There are, however, a few **architectural inconsistencies and missing numbers** that must be resolved
before schematic capture. The most important is #1 below — it changes the bank card topology.

### 1.2 Findings (ordered by impact)

#### F1 – A side cannot sense, B side cannot drive, yet the test sequence requires B→A *(must fix)*

The bank diagram makes A‑side drive‑only and B‑side sense‑only, but the test philosophy asks for a
B→A pass and the fault model includes shorts between pins on the *same* end. With the asymmetric
topology:

* A‑to‑A shorts (two pins at the same connector bridged) are only seen if both pins happen to be
  wired through to B. A short between an A pin and an unused/unterminated A pin is invisible.
* A B→A pass is physically impossible.
* Y‑harnesses, jumpers inside a single connector, and single‑ended fixtures (both cable ends on
  the same side) are not testable.

**Recommendation:** make every node a **symmetric channel cell**: protection + series R +
switchable bias + sense input + stimulus mux input. Cost per node is one extra mux input and one
extra shift‑register bit — small. The "A" and "B" labels then become purely a fixture/mechanical
concept, and firmware treats all 400 points as one flat node space (`node 0..399`). Any node can
be the source; every node is sensed on every step.

#### F2 – Bias polarity must be switchable, otherwise the "low polarity" pass is meaningless

With fixed pull‑downs, driving a node *low* produces an all‑zero bitmap regardless of wiring.

**Recommendation:** return all bias resistors of a bank side to a common **`BIAS_RAIL`** driven by a
small push‑pull buffer (one per side, controlled from the 595 chain).

* High‑polarity pass: `BIAS_RAIL = 0`, stimulus drives high.
* Low‑polarity pass: `BIAS_RAIL = 1`, stimulus drives low.
* **Free self‑test:** with no stimulus, toggling `BIAS_RAIL` must make every input read 0 then 1 →
  detects stuck‑at faults, missing parts and broken chain links in the sense path on every power‑up.

#### F3 – Missing analog budget: net fan‑out vs. bias vs. thresholds

The spec gives ranges (Rs 330R–1k, Rbias 47k–220k) but no closure. The worst case is a big commoned
net (e.g. a 40‑pin ground net): every other pin on that net loads the stimulus with its bias resistor.

With `Rsrc = Rlim + Ron_stage1 + Ron_stage2 + Rs` and `N` nodes on the net (excluding the source):

```
V_net = VDD · (Rbias/N) / (Rbias/N + Rsrc)          must be ≥ VIH(max) + margin
V_off = I_leak(total, per node) · Rbias              must be ≤ VIL(min) − margin
τ     = Rbias · (C_cable + C_mux + C_in + C_TVS)     sets settle time when a node is released
```

**Values for the chosen 5 V domain and ±24 V fault rating (D3, D5 – decided):**

The ±24 V rating dominates. Rs must limit fault current and dissipation, so it is much larger than the
original 330 R–1 k range. That raises the source impedance, so Rbias must rise with it. Leakage sets
the upper limit on Rbias.

| Parameter | Value | Result |
|---|---|---|
| VDD5 | 4.4–5.25 V (USB VBUS, filtered) | All thresholds ratiometric. ADC measures VDD5. |
| Thresholds (74HC at 5 V) | VIH(max) = 0.7·VDD, VIL(min) = 0.3·VDD | Typical switching point ≈ 0.5·VDD |
| Rs (per node) | **4.7 kΩ, 1206 (≥ 0.25 W)** | At ±24 V fault: ≈ 4 mA, ≈ 0.12 W per node |
| Rlim (stimulus) | 150 Ω | Short‑circuit drive current ≈ 1 mA |
| Rsrc total | ≈ 4.9 kΩ | Rlim + 2 × Ron + Rs |
| Rbias | **680 kΩ** | V ≥ 0.75·VDD (VIH + 5 % margin) for **N ≤ 32** nodes worst case (≈ 64 typical), simulated |
| Leakage budget | ≤ 1 µA/node (TVS + clamp diodes + mux off + 165 input) at ≤ 40 °C ambient | Isolated node ≤ 0.69 V < 0.3·VDD = 1.32 V |
| C per node (5 m cable ≈ 500 pF + ~50 pF) | ~550 pF | τ_release ≈ 370 µs → active discharge mandatory |

Action items:

* Write down **guaranteed max net size = 32 nodes** (worst‑case datasheet limits, all tolerances).
  Firmware warns when a profile has a larger net. Such nets are still testable; they rely on typical
  thresholds plus the ADC load signature (F4). Proto characterises the real limit.
* Choose **low‑leakage** protection parts: 28–33 V bidirectional TVS with ≤ 1 µA leakage at temperature,
  and pA/nA‑class clamp diodes (BAV199 class). Generic TVS parts can leak µA, which directly eats the
  low‑level margin.
* Use **active discharge** instead of waiting 5τ. After each step, drive the previous source to the
  opposite polarity for ~20 µs before deselecting. That discharges the whole net through ~4.9 kΩ and
  brings per‑step settle to ≈ 10–40 µs for typical 2–8 node nets. Big nets need longer (≈ 260 µs at 32 nodes).
  Firmware derives the settle time per step from the expected net size.
* **Simulated** in `hardware/sim/channel_sim.py`; results in `hardware/sim/report.md`, including the
  Rs/Rbias/leakage sensitivity table behind these choices.

Resulting scan time (400 sources × 2 polarities × ~220 µs incl. 50‑byte SPI read) ≈ **0.2 s**, which is fine.

Simulate this in KiCad/ngspice (see Phase 2) before freezing values.

#### F4 – Resistive faults and "is the DUT powered?" need an analog path — get it for free

A pure digital threshold only detects hard opens/shorts. The controller section mentions ADC readback
but the bank has no analog path. Because the mux tree is bidirectional, **the stimulus bus itself can
be the analog path**:

* Make the stimulus a single global `STIM` net driven by an MCU GPIO through `Rlim`, with a second
  MCU pin on the same net configured as ADC input (via a small RC + clamp).
* **Voltage pre‑check (safety):** GPIO in Hi‑Z, bias rails off/Hi‑Z, step the mux tree through every
  node and read the ADC → detects powered DUTs/external voltage *before* any drive. This satisfies the
  spec's "refuse test if not safe" requirement with zero extra parts.
* **Load signature:** while driving a node, `V(STIM)` reveals the total conductance of the net
  (`N × 1/Rbias` plus any parasitic leakage). A 10–50 kΩ resistive short (contamination, pinched
  insulation) shows up as an unexpected conductance even when the digital bitmap passes.

Recommend: put `BIAS_RAIL` drivers in a tri‑state‑capable part (e.g. single‑gate buffer with OE) so
the pre‑check can measure a truly floating node.

#### F5 – Channel arithmetic: 7 × 8:1 = 56 inputs, use the 6 spares deliberately

The diagram treats A49/A50 as a special case with "a small local select/spare mux". Not needed:
7 first‑stage 8:1 muxes give 56 inputs; 7 × 74HC165 give 56 sense bits. The 2nd‑stage 8:1 mux has
one spare input. Use them:

| Per side | Use |
|---|---|
| Inputs 1–50 | Fixture signal nodes |
| Input 51 | Connector shell / chassis node (spec item "shell_A → shell_B") |
| Input 52 | On‑board loopback to the same index on the opposite side (known‑good path) |
| Input 53 | Deliberately open node (known‑open) |
| Input 54 | Node with fixed resistor to GND (ADC calibration / load‑signature reference) |
| Inputs 55–56 | Spare, DNP pads |
| 2nd‑stage input 8 | `STIM` self‑test / ADC calibration point (e.g. divider) |

Alternative worth evaluating in Phase 0: **64 nodes per side** (8 × 8:1 + full 2nd stage, 8 × 165).
It is the "natural" size for this topology and adds 28% capacity for ~same complexity; decide based on
the connector choice.

#### F6 – Cross‑bank operation must be explicit

Cable nets cross bank boundaries (pin 12 to pin 187). Therefore:

* `STIM` is a **global** net routed to every bank (backplane), selected into exactly one bank side by
  that side's 2nd‑stage mux enable.
* All 165 chains in all banks are latched together (`SENSE_PL` global) and read as one 400‑bit frame.
* Hardware/firmware interlock: at most one 2nd‑stage mux enabled. Firmware enforces it; hardware
  defaults must be "all disabled" at power‑up (595 `/OE` pulled high until firmware has loaded a
  safe pattern, mux `EN` lines pulled to their disabled state — check TMUX1308 enable polarity).

#### F7 – Control bit count is much smaller than the spec implies

First‑stage muxes in a side can share their 3 address lines (only the 2nd stage decides which one
reaches `STIM`). Per side: `ADDR1[2:0]`, `ADDR2[2:0]`, `EN2`, `BIAS` = **8 bits = one 74HC595**.
Per bank card: 2 × 595 (+ optionally one more for LEDs/status/BIAS_OE). Total system: ~8–12 bytes out,
50 bytes in. Shift chains are trivially fast.

The inactive first‑stage muxes still connect one pin each to a floating output stub — harmless
(adds a few pF), but note it in the leakage budget.

#### F8 – Logic family / voltage domain *(decided: 5 V analog/logic domain, D3)*

* **5 V domain (VDD5):** muxes (TMUX1308 runs 1.62–5.5 V), '165 and '595 sense/control logic, bias rail
  drivers, `STIM` driver. 74HC at 5 V is inside its characterised range, with better noise margin on long
  cables than 3.3 V.
* **3.3 V domain:** STM32C071 only (plus USB). Level interfaces:
  * MCU → 5 V logic: **74HCT/AHCT** buffers (TTL thresholds accept 3.3 V levels). One single‑gate buffer
    per control net on each bank card. This also gives the clean per‑card clock buffering of F10.
  * 5 V logic → MCU (`MISO` chain end): a 74LVC1G125 powered from 3.3 V (5 V‑tolerant input), or a
    5 V‑tolerant (FT) MCU pin. The LVC buffer is preferred because it does not depend on the pin type.
  * `STIM` driver: 74AHCT1G125 (3‑state, 5 V output, 3.3 V‑compatible inputs) → Rlim → `STIM`.
    `STIM` ADC tap through a 2:1 divider + RC into an MCU ADC pin. A second ADC channel measures VDD5
    for ratiometric scaling.
* VDD5 comes from USB VBUS through a load switch with reverse‑current blocking, an LC filter and the
  rail shunt clamp (F9). The 3.3 V LDO for the MCU is fed from VBUS.
* The 165 is not Schmitt. This is acceptable because sampling is static (after settle). Firmware samples
  each frame 2–3× and requires agreement. Rs (4.7 kΩ) and the input capacitance form a natural low‑pass.
  The prototype gets a DNP cap footprint per node.

#### F9 – Protection *(decided: ±24 V DC on any node, D5)*

Written rating:

* **ESD:** IEC 61000‑4‑2 ±8 kV contact on every fixture node.
* **DC fault:** survive **±24 V** continuously on any fixture node, powered or unpowered, with up to
  8 nodes per bank side faulted at once. Design margin to 30 V, so 24 V systems at full charge voltage (≈ 28.8 V) are covered. Not rated for mains or for load‑dump transients. The ADC pre‑check (F4) refuses to drive an
  energised harness.

Per‑node protection chain (connector → logic):

```
EXT ──┬── TVS (bidirectional, standoff ≥ 28 V, low leakage) ── GND/chassis
      │
      Rs 4.7 kΩ 1206
      │
NODE ─┼── clamp diode to VDD5 ┐  BAV199‑class (low leakage), two nodes per package
      ├── clamp diode to GND  ┘
      ├── Rbias 680 kΩ → BIAS_RAIL
      ├── mux input
      └── 165 input
```

* Simulated (`hardware/sim/report.md` §4): +24 V → 3.8 mA, −24 V → 5.0 mA; at 30 V up to 6.3 mA and
  0.18 W in Rs. Use 1206 (0.25 W, JLCPCB basic part).
* **Correction from simulation:** low‑leakage clamps (BAV199 class) have a *higher* Vf than the CMOS input
  ESD diodes, so ≈ 95 % of the fault current still flows through the mux/'165 input structures. Rs is the
  real limiter. ≤ 6.3 mA per input is inside the 74HC ±20 mA clamp‑current rating; **TMUX1308
  injection/clamp rating must be confirmed in Phase 2**. The external clamps are kept as a footprint
  option (DNP on Proto40) rather than relied upon.
* **Rail pumping:** 8 faulted nodes × 3.9 mA ≈ 31 mA per side, up to ~250 mA for a whole system,
  flowing *into* VDD5. VBUS cannot sink current, so VDD5 needs an **active shunt clamp** (TLV431 + pass
  transistor, set ≈ 5.45 V, rated ≥ 300 mA). The VBUS load switch must block reverse current so the host
  is never back‑fed. The TMUX1308 abs‑max is around 6 V, so the clamp must hold below it — verify
  against the datasheet in Phase 2.
* The TVS standoff must be above the fault voltage. A 5 V TVS would conduct at 24 V and burn out.

#### F10 – Interconnect between controller and banks

Separate boards with ribbon cables carrying SPI clocks work but are the most common source of
bring‑up pain. Recommend a **backplane** (controller + 4 bank slots) with:

* `SCK`, `MOSI`, `RCLK` (595 latch), `SENSE_PL` (165 load), `/OE`, `STIM`, I²C (fixture ID), VDD5, 3V3, GND.
* Sense data as a **daisy chain through all cards** (`MISO_IN` → card → `MISO_OUT`); the 165 output is
  not tri‑state so parallel MISO would need per‑card buffers.
* Per‑card clock buffer (single‑gate Schmitt buffer) + series termination; keep SCK ≤ 4 MHz on Rev A.
* Slot‑ID pins on the backplane (strapped 2 bits) so firmware can verify which banks are populated —
  this makes the 50/100/150/200‑pin variants plug‑and‑play.

#### F11 – Fixture interface & mechanics

* Connector per bank side should carry 56 nodes + ≥ 8 GND + ID + presence detect. A **DIN 41612 64‑pin
  (2 rows) or 96‑pin (3 rows)** connector is cheap, keyed, robust and has well‑defined mating‑cycle
  classes; it also exists in the KiCad standard library. Alternatives: high‑cycle pogo/mezzanine — decide in Phase 0.
* One adapter spanning 4 bank connectors means 4 × 64 contacts → mating force in the 150–250 N range.
  Plan for guide pins and a lever/cam; don't let operators push boards by hand.
* Adapter ID: one I²C EEPROM per adapter. Two adapters on one bus need different addresses, so strap
  the address pins via the base connector (A side = 0b000, B side = 0b001) or give each side its own
  I²C bus. Add a **presence‑detect** pin (shortest contact if the connector allows staggered pins).
  The EEPROM is sized to also carry the **test profile/sequence** (32 kB+, see §1.5).

#### F12 – Smaller items

* USB: USB‑C (UFP, 2 × 5.1 kΩ on CC), ESD array on D+/D‑, polyfuse, 3.3 V LDO. Total load is well below
  100 mA; still budget it.
* Add SWD header (Tag‑Connect or 2×5 1.27 mm), BOOT0 access, status LEDs, one start/stop button, and a
  pass/fail beeper/LED visible to operators.
* Add test points on every global control net and on `STIM`; it pays back during bring‑up.
* Firmware fault classification "swap" needs whole‑matrix analysis, not per‑step comparison — store the
  full measured connectivity matrix and diff it against the expected netlist, then classify.
* "Intermittent" detection: add a continuous‑scan (wiggle) mode that latches any change.

### 1.3 Revised Rev A architecture (summary)

```
              USB
               │
      ┌────────▼─────────┐  I²C (fixture ID A/B)
      │ Controller       │──────────────────────────────┐
      │ STM32C071        │  STIM (GPIO + ADC, Rlim)     │
      │                  │──────────────┐               │
      └──┬──────┬────────┘              │               │
   SPI OUT│     │SPI IN (daisy chain)   │               │
  ════════╪═════╪══════════ BACKPLANE ══╪═══════════════╪══════════
          │     │                       │               │
   ┌──────▼─────▼───────────────────────▼───────────────▼──────┐  × 4
   │ Bank card (50+6 nodes side A, 50+6 nodes side B)          │
   │                                                           │
   │  per side:  56 × channel cell [TVS · Rs · Rbias→BIAS_RAIL]│
   │             7 × 8:1 mux (shared ADDR1) → 1 × 8:1 (ADDR2,EN)│──► STIM
   │             7 × '165 (56 sense bits)                      │
   │             1 × '595  (ADDR1, ADDR2, EN, BIAS)            │
   │             BIAS_RAIL buffer (tri‑state)                  │
   │  connectors: Fixture‑A (DIN 41612) · Fixture‑B (DIN 41612)│
   └───────────────────────────────────────────────────────────┘
```

Rough per‑bank‑card active BOM: 16 × TMUX1308, 14 × '165, 2 × '595, 2 × bias buffer, ~28 × 4‑ch TVS array
(or 14 × 8‑ch), 112 × Rs, 112 × Rbias, 2 × fixture connector, 1 × backplane connector.

### 1.4 Decisions needed before schematic capture (Phase 0)

| # | Decision | Recommendation |
|---|---|---|
Status as of 2026‑10‑01 (see `docs/decisions.md` for the log):

| # | Decision | Status |
|---|---|---|
| D1 | Symmetric channel cells (F1) | ✅ **Decided: yes** |
| D2 | Nodes per side | ✅ **50 + shell** (set by the 64‑pin DIN connector, `docs/fixture-interface.md`) |
| D3 | Voltage domain | ✅ **Decided: 5 V analog/logic, 3.3 V MCU** (F8) |
| D4 | Max net size / Rbias / Rs | ✅ **Simulated: 32 nodes guaranteed, Rbias 680 kΩ, Rs 4.7 kΩ, leakage ≤ 1 µA/node** |
| D5 | DC fault rating | ✅ **Decided: ±24 V on any node** (F9) |
| D6 | Controller ↔ bank interconnect | Proposed: backplane |
| D7 | Fixture connector family | ✅ **DIN 41612 type C 2×32** (female base, male right‑angle adapter) |
| D8 | PCB fab target & stack‑up | ✅ **Decided: JLCPCB** (JLC04161H‑7628 4‑layer, JLCPCB capabilities in DRC) |
| D9 | KiCad version | ✅ **Decided: KiCad 10.0 (CI pinned to 10.0.6)**; checks run on pull requests |

| D10 | Adapter EEPROM scope | ✅ **Decided: identity + embedded test profile** (§1.5) |
| D11 | Prototype size | ✅ **Proto40** (5 groups per side) |

### 1.5 Adapter EEPROM carrying the test sequence (standalone operation)

The adapter EEPROM can hold more than an ID. It can carry the complete test definition, so a matching
adapter pair plus the *Start* button is enough to test a cable **without a PC**. The full format is in
[`adapter-eeprom-format.md`](adapter-eeprom-format.md). Key points:

* **Store the intent, not the scan.** The EEPROM holds the expected netlist (in adapter‑pin terms) plus
  a short list of sequence opcodes (`PRECHECK`, `SELFTEST`, `CONTINUITY`, `LOAD_SIG`, `PROMPT`,
  `WIGGLE`, …). The controller derives expected bitmaps at run time. A 200‑wire cable profile is
  ≈ 4 kB including pin labels; raw bitmaps would be ≥ 20 kB per polarity.
* **Separation of concerns.** Each adapter stores its own *pin → tester channel* map (generated from
  its KiCad netlist). The *primary* adapter stores the cable profile and the required partner adapter
  type. The same profile works on side A or B and in any bank position.
* **Safety stays in firmware.** The voltage `PRECHECK` always runs, whatever the profile says.
* **PC overrides.** When the host is connected and has loaded a profile, the EEPROM is used for identity
  only. The host tool is the only writer: it programs through the tester, with `WP` controlled by the
  controller and protected by default.
* **Integrity.** Versioned format (major/minor), CRC‑32 per section, forward‑compatible TLV opcodes. An
  optional HMAC signature is reserved for regulated production.

Hardware consequences (carried into Part 2):

| Board | Change |
|---|---|
| Adapter | 24xx256/512‑class EEPROM (SOIC‑8/TSSOP‑8), A0–A2 and `WP` routed to the base connector, `WP` pull‑up + "lock" solder jumper, presence pin |
| Bank card / backplane | Per side: `ID_SDA`, `ID_SCL`, `ID_WP`, `PRESENT`, address straps. Primary bank connector only, but wired on all for flexibility |
| Controller | `WP` control GPIOs, I²C ESD/series R. **Standalone UI:** Start button, PASS/FAIL LEDs, buzzer, optional small display (I²C OLED / character LCD) for prompts and fault text; optional SPI flash for result logs and a profile cache |

---

## Part 2 – KiCad realization plan

### 2.1 Repository layout

```
cable_tester2/
├── docs/                         design notes, decision log (decisions.md), this plan, formats
├── hardware/                     every KiCad project sits one level below hardware/ (lib path rule)
│   ├── lib/
│   │   ├── cable_tester.kicad_sym        project symbols (incl. MPN/manufacturer/LCSC fields)
│   │   ├── cable_tester.pretty/          project footprints
│   │   ├── 3dmodels/                     STEP models (${KIPRJMOD}/../lib/3dmodels/...)
│   │   └── design_blocks/                reusable schematic blocks (channel cell, group‑of‑8)
│   ├── _template/                ✅ JLCPCB 4‑layer stack‑up, rules, net classes, .kicad_dru, title block
│   ├── sim/                              ngspice channel‑cell + cable simulation
│   ├── proto40/                  ✅ (empty) Prototype 1 – MCU + 40 + 40 symmetric nodes
│   ├── controller/                       Controller board (Rev A)
│   ├── bank50/                           50‑channel bank card (Rev A)
│   ├── backplane/                        4‑slot backplane
│   ├── adp_template/                     adapter template (fixture connector, EEPROM, outline)
│   └── adp0001_a/, adp0001_b/            first adapter pair (after D7)
├── fixtures/
│   └── ADP0001_tap_fluidic/      ✅ cable netlists (C1, C2, chain C3), adapter pin map, open questions
├── scripts/                      ✅ kicad_check.sh, kicad_outputs.sh, new_board.sh
├── firmware/                             (later)
├── host/                                 (later – GUI, netlist → profile/EEPROM image)
└── .github/workflows/kicad.yml   ✅ ERC/DRC on pull requests, fab outputs on hw/* tags
```

Conventions:

* Project‑local `sym-lib-table` / `fp-lib-table` using `${KIPRJMOD}/../lib/...` so every project
  resolves libraries identically on every machine. No dependence on personal global libraries.
* Standard KiCad libraries are allowed for generic parts (R/C, 74xx, DIN 41612, USB‑C,
  STM32C0 symbols if present in the pinned version); anything custom goes into `cable_tester.*`.
* Mandatory symbol fields: `MPN`, `Manufacturer`, `LCSC` (JLCPCB assembly), `Value`, `Footprint`, `Datasheet`.
  Alternates in `MPN_Alt`.
* Git: commit `.kicad_pro`, `.kicad_sch`, `.kicad_pcb`, `.kicad_dru`, lib tables; `.kicad_prl` excluded, `fp-info-cache` and
  `*-backups/` ignored. Add `.gitattributes` to treat KiCad files as text with LF.

### 2.2 Schematic hierarchy (bank card)

Use KiCad multi‑instance hierarchical sheets so a channel is drawn **once**:

```
bank50.kicad_sch (root)
├── power.kicad_sch                  3V3 filtering, bulk caps, backplane connector
├── control.kicad_sch                SPI buffering, MISO daisy chain, 2 × '595, slot ID
├── side.kicad_sch   ×2  (A, B)      fixture connector, 2nd‑stage mux, BIAS_RAIL buffer,
│   │                                internal nodes 51–56, '165 chain wiring
│   └── group8.kicad_sch  ×7         1 × TMUX1308, 1 × '165, local decoupling
│       └── channel.kicad_sch ×8     TVS (or shared array pin), Rs, Rbias, test pad
```

Notes:

* `channel.kicad_sch` exposes hierarchical pins: `EXT` (fixture side), `NODE` (to mux + '165),
  `BIAS_RAIL`. If multi‑channel TVS arrays are used, place the array at `group8` level instead
  (one 4‑ch or 8‑ch array per group), and keep `channel` to Rs/Rbias/test‑pad.
* Bus conventions: `EXT[0..7]`, `NODE[0..7]` inside a group; `SIDE_A_EXT[1..56]` at side level.
  Use **bus aliases** `{SPI_CTRL}` = `SCK MOSI RCLK SENSE_PL OE_N` and `{SIDE_CTRL}` =
  `ADDR1[0..2] ADDR2[0..2] EN2_N BIAS BIAS_OE` to keep sheet symbols compact.
* Global labels only for true globals: `STIM`, `+3V3`, `GND`, `I2C_SDA/SCL`. Everything else via
  hierarchical pins (forces explicit, reviewable connectivity).
* Annotation: "sheet number × 1000" scheme so references encode location
  (e.g. `R2317` = sheet 2, group 3, channel‑ish), which makes rework on a 100‑node board tractable.
* The `proto40` project reuses `group8`/`channel` (5 groups per side). Share them as **KiCad design
  blocks** stored in `hardware/lib/design_blocks/` rather than referencing the same `.kicad_sch` file
  from two projects (instance data and annotation make cross‑project sheet sharing fragile).

### 2.3 PCB strategy

**Bank card**

* Floorplan: two fixture connectors on the front edge (A, B), backplane connector on the rear edge,
  the two "side" regions mirrored left/right, control/power strip in the middle.
* Protection zone: TVS arrays within a few mm of the fixture connector pins, Rs immediately after,
  then the long route to the logic. Return TVS directly to a solid GND plane with multiple vias.
  Separate the connector shell/chassis copper from logic GND (bridge with RC/0 Ω option).
* Layout reuse: route **one** `group8` (mux + '165 + 8 channel cells) cleanly, then use KiCad's
  multichannel tools (rule areas generated from sheets → *Repeat layout*) to clone it to the other
  13 groups. Fallback for older versions: the *Replicate Layout* action plugin.
* Stack‑up (4‑layer starting point): L1 signals/parts, L2 solid GND, L3 3V3 + slow control,
  L4 signals. Move to 6‑layer only if the 112 fixture nets + buses can't break out from the
  connectors cleanly — decide after a placement study.
* Net classes: `FIXTURE` (wider clearance, e.g. 0.2 mm, no vias in the TVS region if avoidable),
  `STIM`, `SPI` (length‑matched not needed at 4 MHz, but keep SCK away from fixture nets),
  `POWER`. Encode in the template's `.kicad_dru` custom rules, e.g. clearance FIXTURE↔SPI.
* Test points on `STIM`, `BIAS_RAIL_A/B`, all '595 outputs, chain in/out, 3V3, GND.

**Controller** — 2‑ or 4‑layer, USB‑C + ESD + polyfuse + LDO, STM32C071, SWD, `STIM` driver
(GPIO → Rlim → STIM, ADC tap via RC + clamp), I²C for fixture EEPROMs with pull‑ups and ESD/series R,
two `ID_WP` drive lines (default protected), presence inputs, backplane connector. Standalone UI per
§1.5: Start button, PASS/FAIL LEDs, buzzer, header/footprint for an I²C display, optional SPI flash
footprint (DNP) for logs.

**Backplane** — 2‑layer (4 if SCK integrity demands), 5 slots, slot‑ID straps, power entry.

**Adapters** — template project: board outline + mounting/guide holes matching the bank card front,
DIN 41612 mating footprint(s), profile EEPROM (24xx256/512 footprint) with A0–A2 and `WP` taken to the
base connector, `WP` pull‑up + lock jumper, presence‑detect, shell strap, and a blank area for the
customer connector. Adapter mapping lives in the schematic *and* is exported (`kicad-cli`) as a netlist.
The host tool converts it into the EEPROM `PINMAP` and, together with the cable definition, into the
`PROFILE` image — **one source of truth**.

### 2.4 Tooling & CI

* **kicad‑cli in GitHub Actions** (`kicad/kicad:10.0.6` container). There is no KiBot dependency; the
  same scripts run locally:
  * on every pull request: `scripts/kicad_check.sh` (ERC + DRC with schematic parity; fails on errors)
    and `scripts/kicad_outputs.sh` (schematic PDF, BOM CSV with MPN/LCSC), uploaded as artifacts.
  * on tag `hw/<board>/vX.Y`: plus Gerbers, drill, pick‑and‑place, STEP, zipped.
* Text variables in the template (`BOARD_NAME`, `REVISION`, `RELEASE_DATE`, `COMPANY`, `PROJECT`) feed the
  title block. A release can override them with `kicad-cli … -D REVISION=…`.
* Optional: `kicad-cli` scripted netlist export of each adapter → host‑side expected‑matrix generator,
  checked in CI (adapter netlist and profile must agree).

### 2.5 Phased plan

| Phase | Content | Deliverables | Exit criteria |
|---|---|---|---|
| **0 – Spec freeze** | Resolve D1–D10; freeze EEPROM format v1 header/PINMAP; write ADRs; fixture connector + mechanical concept sketch; power and timing budget | `docs/adr/*`, updated block diagram, budget spreadsheet | Decisions signed off |
| **1 – Infrastructure** ✅ | Repo layout, KiCad template (stack‑up, net classes, `.kicad_dru`, title block), lib tables, CI (kicad‑cli) on an empty project | Green CI on template | Any contributor clones and opens every project without missing libs |
| **2 – Library & simulation** | Symbols/footprints for STM32C071, TMUX1308, '165/'595 (LV/AHC), TVS arrays, DIN 41612, USB‑C, EEPROM; 3D models. ngspice sim of channel cell + 5 m cable + worst‑case net | Library with MPNs; `hardware/sim` results in `docs/` | Margins in F3 confirmed incl. tolerances & leakage at temperature |
| **3 – Proto40** | Single 4‑layer board: controller section + 5 groups per side (40+40 symmetric nodes) + 2 small fixture connectors (with ID_SDA/SCL/WP/PRESENT pins) + all internal test nodes + a mini test adapter carrying the profile EEPROM. Generous test points, 0603 parts, DNP cap per node, jumper‑selectable Rbias/Rs options | Fabricated proto, bring‑up firmware (chains, mux, STIM, ADC, USB CDC, EEPROM profile read) | No ghost hits; open/short/swap/resistive‑short detection demonstrated; leakage & settle measured vs. sim |
| **4 – Rev A boards** | Bank card (hierarchy as in 2.2, multichannel layout reuse), controller, backplane — schematics → review → layout → review | Fab packages for 3 boards | Design reviews passed (checklist below), CI green |
| **5 – Adapters** | Adapter template + first real cable family adapter pair; host tool `ctfx build/verify/program` | Adapter fab package + EEPROM image generated from netlists | Image auto‑generated and CI‑verified against adapter netlist; standalone test (no PC) passes/fails seeded faults |
| **6 – Integration** | 1 bank → 4 banks; self‑test, adapter ID, logging, enclosure & fixture mechanics | System test report | Full 200‑pin cable tested < 1 s, self‑test catches seeded faults |

### 2.6 Review checklists (gate for Phase 4/5)

Schematic review:

- [ ] Power‑on default state: 595 `/OE` high, mux enables disabled, `BIAS_OE` safe — verified per part datasheet polarity
- [ ] Every fixture net: TVS → Rs → logic, nothing else between connector and TVS
- [ ] Bias rail driver can source/sink worst case (all nodes opposite polarity)
- [ ] Injection current at ±12 V within mux and register abs‑max
- [ ] Shift‑chain order documented and matches firmware bit map table (generate the table from the schematic netlist if possible)
- [ ] Internal test nodes 51–56 wired as specified
- [ ] ERC clean, no unexplained `no_connect`, every IC decoupled

Layout review:

- [ ] TVS placement within protection zone, short GND return
- [ ] Repeated groups truly identical (multichannel/replicate tool used, not hand‑copied)
- [ ] Chassis/logic GND separation as intended
- [ ] Connector pin‑1, keying and mating orientation checked against adapter template (print 1:1 / 3D check)
- [ ] Test points accessible with probes when cards are in the backplane
- [ ] DRC clean against fab capabilities; silkscreen readable (references + node numbers at connectors)

### 2.7 Immediate next steps

1. Remaining open decision: D6 (backplane), needed for Phase 4 only.
2. ~~Set up Phase 1 infrastructure~~ (done: template, lib tables, CI on pull requests).
3. ~~Build the ngspice channel‑cell model and lock Rs/Rbias/Rlim~~ (done, `hardware/sim`).
4. Start Proto40 schematic using the `channel` / `group8` blocks that will carry straight into the bank card.
