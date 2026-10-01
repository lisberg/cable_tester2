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
expectation. The bank/adapter partitioning and the staged prototype plan (16 → 50 → 200) are
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

Starting point (3.3 V domain, CMOS VIH = 0.7·VDD = 2.31 V):

| Parameter | Value | Result |
|---|---|---|
| Rs (per node) | 1 kΩ | limits injection, ESD energy after TVS |
| Rlim (stimulus) | 150 Ω | short‑circuit current ≈ 3.3 V / 1.15 kΩ ≈ 2.9 mA |
| Rbias | 220 kΩ | V_net ≥ 2.31 V for **N ≤ ~80** nodes per net |
| Leakage budget | ≤ 1 µA/node (TVS + mux off + input) | V_off ≤ 0.22 V |
| C per node (5 m cable ≈ 500 pF + ~50 pF parasitic) | ~550 pF | τ ≈ 120 µs |

Action items:

* Make the **max net size** a written spec (e.g. 80 nodes). Firmware can flag profiles exceeding it.
* Choose **low‑leakage** TVS arrays — some generic TVS parts are µA‑class at temperature, which
  directly eats the low‑level margin.
* Use **active discharge** instead of waiting 5τ: after each step drive the previous source to the
  opposite polarity for ~10–20 µs before deselecting. That discharges the entire net through the
  low‑impedance path and brings per‑step settle to ≈ 50–100 µs.

Resulting scan time (400 sources × 2 polarities × ~150 µs incl. 50‑byte SPI read) ≈ **0.15 s** – fine.

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

#### F8 – Logic family / voltage domain

* Single **3.3 V** domain for Rev A is recommended: MCU, muxes, shift registers, stimulus all at 3.3 V.
  No level shifting, ADC full scale = logic swing.
* 74HC parts are characterised at 2/4.5/6 V; at 3.3 V their thresholds are interpolated and timing is
  slow. Prefer **74LV165A / 74LV595A** or **74AHC** equivalents, or verify 74HC datasheet numbers at 3.3 V.
* The spec mentions "Schmitt" inputs; the 165 is not Schmitt. This is acceptable because sampling is
  static (after settle). Mitigate noise in firmware: sample each frame 2–3× and require agreement.
  Use the Rs + input capacitance as a natural low‑pass; leave a DNP cap footprint per node only on proto 1.
* A 5 V stimulus domain (better noise margin on long cables) is a possible Rev B option; it would require
  level translation to the MCU and 5 V‑rated muxes.

#### F9 – Protection: define what the tester survives

"Protection at every node" needs a number. Proposed written rating:

* ESD: IEC 61000‑4‑2 ±8 kV contact on every fixture node (TVS array at connector, Rs behind it).
* DC fault: survive ±12 V indefinitely on any single node, power on or off. With Rs = 1 kΩ, the injected
  current into the 3.3 V clamps would be ≈ 8.7 mA — check against the mux injection‑current spec and
  the shift‑register abs‑max (typ. ±20 mA). If insufficient, raise Rs on the sense path only or add
  per‑node clamp diodes to a rail that can absorb current (and verify the 3.3 V rail can't be pumped up —
  add a rail clamp/zener).
* Not rated for mains or live equipment; the ADC pre‑check (F4) refuses to test energised harnesses.

#### F10 – Interconnect between controller and banks

Separate boards with ribbon cables carrying SPI clocks work but are the most common source of
bring‑up pain. Recommend a **backplane** (controller + 4 bank slots) with:

* `SCK`, `MOSI`, `RCLK` (595 latch), `SENSE_PL` (165 load), `/OE`, `STIM`, I²C (fixture ID), 3V3, GND.
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
* Adapter ID: one I²C EEPROM per adapter (e.g. a 24xx02 with factory unique ID). Two adapters on one bus
  need different addresses, so either strap the address pins via the base connector (A side = 0b000,
  B side = 0b001) or give each side its own I²C bus. Add a **presence‑detect** pin (shortest contact if
  the connector allows staggered pins).

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
| D1 | Symmetric channel cells (F1) | **Yes** |
| D2 | Nodes per side: 50 (+6 internal) or 64 | 50 + 6 internal, unless connector favours 64 |
| D3 | Voltage domain | 3.3 V single domain |
| D4 | Max net size / Rbias / Rs | 80 nodes, 220 kΩ, 1 kΩ — confirm by simulation |
| D5 | DC fault rating | ±12 V single node, not live equipment |
| D6 | Controller ↔ bank interconnect | Backplane |
| D7 | Fixture connector family | DIN 41612 64/96‑pin (evaluate pogo alternative) |
| D8 | PCB fab target & stack‑up | 4‑layer, standard 0.127/0.127 mm class (bank card possibly 6‑layer) |
| D9 | KiCad version | Pin one version for all contributors (9.0.x minimum, multichannel tools required) |

---

## Part 2 – KiCad realization plan

### 2.1 Repository layout

```
cable_tester2/
├── docs/                         design notes, ADRs, this plan, calculations
│   └── adr/                      one file per decision D1..D9
├── hardware/
│   ├── lib/
│   │   ├── cable_tester.kicad_sym        project symbols (incl. MPN/manufacturer fields)
│   │   ├── cable_tester.pretty/          project footprints
│   │   ├── 3dmodels/                     STEP models (referenced via ${CT_3DMODELS})
│   │   └── design_blocks/                reusable schematic blocks (channel cell, group‑of‑8)
│   ├── templates/
│   │   └── ct_template/                  board setup, text vars, net classes, title block, .kicad_dru
│   ├── sim/                              ngspice channel‑cell + cable simulation (KiCad schematic)
│   ├── proto16/                          Prototype 1 – single board, MCU + 16 symmetric nodes
│   ├── controller/                       Controller board (Rev A)
│   ├── bank50/                           50‑channel bank card (Rev A)
│   ├── backplane/                        4‑slot backplane
│   └── adapters/
│       ├── _template/                    adapter template (connector footprint, ID EEPROM, outline)
│       └── <cable_family>/               one project per adapter
├── firmware/                             (later)
├── host/                                 (later – GUI, netlist → profile converter)
└── .github/workflows/kicad.yml           ERC/DRC + fab outputs via KiBot
```

Conventions:

* Project‑local `sym-lib-table` / `fp-lib-table` using `${KIPRJMOD}/../lib/...` so every project
  resolves libraries identically on every machine. No dependence on personal global libraries.
* Standard KiCad libraries are allowed for generic parts (R/C, 74xx, DIN 41612, USB‑C,
  STM32C0 symbols if present in the pinned version); anything custom goes into `cable_tester.*`.
* Mandatory symbol fields: `MPN`, `Manufacturer`, `Supplier_PN`, `Value`, `Footprint`, `Datasheet`.
  Alternates in `MPN_Alt`.
* Git: commit `.kicad_pro`, `.kicad_sch`, `.kicad_pcb`, `.kicad_prl` excluded, `fp-info-cache` and
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
* The `proto16` project reuses `group8`/`channel` (2 groups per side). Share them as **KiCad design
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
(GPIO → Rlim → STIM, ADC tap via RC + clamp), I²C for fixture IDs with pull‑ups and buffer/ESD,
backplane connector, LEDs/button/buzzer.

**Backplane** — 2‑layer (4 if SCK integrity demands), 5 slots, slot‑ID straps, power entry.

**Adapters** — template project: board outline + mounting/guide holes matching the bank card front,
DIN 41612 mating footprint(s), ID EEPROM with address straps, presence‑detect, shell strap, and a
blank area for the customer connector. Adapter mapping lives in the schematic *and* is exported as a
netlist that the host tool converts into the test profile — **one source of truth**.

### 2.4 Tooling & CI

* **KiBot** in GitHub Actions (official KiCad Docker image matching the pinned version):
  * on every push/PR: ERC + DRC (fail build on errors), schematic PDF, interactive BOM.
  * on tag `hw/<board>/vX.Y`: Gerbers + drill, pick‑and‑place, BOM (CSV with MPNs), STEP, fab
    drawing, zipped release artifact.
* Text variables in the template (`${REVISION}`, `${BOARD}`, `${DATE}`) populated from git tag by KiBot,
  printed on title block and silkscreen.
* Optional: `kicad-cli` scripted netlist export of each adapter → host‑side expected‑matrix generator,
  checked in CI (adapter netlist and profile must agree).

### 2.5 Phased plan

| Phase | Content | Deliverables | Exit criteria |
|---|---|---|---|
| **0 – Spec freeze** | Resolve D1–D9; write ADRs; fixture connector + mechanical concept sketch; power and timing budget | `docs/adr/*`, updated block diagram, budget spreadsheet | Decisions signed off |
| **1 – Infrastructure** | Repo layout, KiCad template (stack‑up, net classes, `.kicad_dru`, title block), lib tables, CI with KiBot on an empty project | Green CI on template | Any contributor clones and opens every project without missing libs |
| **2 – Library & simulation** | Symbols/footprints for STM32C071, TMUX1308, '165/'595 (LV/AHC), TVS arrays, DIN 41612, USB‑C, EEPROM; 3D models. ngspice sim of channel cell + 5 m cable + worst‑case net | Library with MPNs; `hardware/sim` results in `docs/` | Margins in F3 confirmed incl. tolerances & leakage at temperature |
| **3 – Proto16** | Single 4‑layer board: controller section + 2 groups per side (16+16 symmetric nodes) + 2 small fixture connectors + all internal test nodes. Generous test points, 0603 parts, DNP cap per node, jumper‑selectable Rbias/Rs options | Fabricated proto, bring‑up firmware (chains, mux, STIM, ADC, USB CDC) | No ghost hits; open/short/swap/resistive‑short detection demonstrated; leakage & settle measured vs. sim |
| **4 – Rev A boards** | Bank card (hierarchy as in 2.2, multichannel layout reuse), controller, backplane — schematics → review → layout → review | Fab packages for 3 boards | Design reviews passed (checklist below), CI green |
| **5 – Adapters** | Adapter template + first real cable family adapter pair | Adapter fab package + generated test profile | Profile auto‑generated from adapter netlist |
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

1. Confirm/adjust decisions D1–D9 (especially symmetric cells and 50 vs 64 nodes per side).
2. Set up Phase 1 infrastructure in this repo (template, lib tables, KiBot CI).
3. Build the ngspice channel‑cell model and lock Rs/Rbias/Rlim.
4. Start Proto16 schematic using the `channel` / `group8` blocks that will carry straight into the bank card.
