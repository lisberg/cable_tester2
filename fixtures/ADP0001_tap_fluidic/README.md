# ADP-0001 – Tap ↔ M12 ↔ Fluidic harness adapter

The first test adapter. It is an adapter **pair** that tests two cables separately and as a mated chain:

| Profile | Cable | End on side A (ADP0001‑A) | End on side B (ADP0001‑B) |
|---|---|---|---|
| 1 | **C1** Tap ribbon → M12 female | FFSD (16) on J1 | M12 female (17) on J3 |
| 2 | **C2** M12 male → Fluidic Pico‑SPOX | Pico‑SPOX 12 on J2 | M12 male (17) on J4 |
| 3 | **C3** C1 + C2 mated (chain) | FFSD on J1 **and** Pico‑SPOX on J2 | — (single‑ended) |

Source data: the pin table received 2026‑10‑01, transcribed into:

* `C1_tap_ribbon_to_m12f.nets.csv`, `C2_m12m_to_fluidic.nets.csv`: expected nets (cable definitions)
* `C3_chain_c1_c2.nets.csv`: the chain profile, derived from C1 + C2 by joining the M12 pins.
  The derivation has been verified by script.
* `adapter_pinmap.csv`: adapter connector pin → tester channel

Channel usage: side A uses 28 channels, side B uses 36 (34 M12 pins + 2 shells). Both fit **Proto40** and
the Rev A bank card. The adapter connects to the base through the standard fixture connector (D7, still
open). The profile EEPROM sits on **ADP0001‑A** (primary) and holds profiles 1–3.

## What the test covers

* Opens, shorts, and swapped or crossed wires on every conductor, in both drive polarities.
* The **RS‑422 crossover** in C2/C3 (Tap A/B ↔ Fluidic Y/Z) is checked explicitly: a "straight" wired
  pair fails.
* **Ground wires are commoned in C2** (confirmed 2026‑10‑06). C2 has one GND net with 11 endpoints
  (M12M 1, 2, 5, 6, 11, 12, 16 + PS 2, 5, 8, 11). Every one of them must be present, so a broken ground
  wire fails. That's well within the guaranteed 32‑node net size. C1 is still modelled 1:1 with separate
  GND conductors (see Q3b).
* `C3` is generated with `scripts/chain_nets.py` and must be regenerated whenever C1 or C2 changes.
* Unused M12 pin 17 is checked for isolation against everything.
* Bridged pins (M12M.1+2, 3+4, 5+6, 12+16) must be connected to each other.

**Not electrically verifiable:** twisting of PS.3/PS.4 and PS.6/PS.7, wire gauge, and shield coverage.
These need visual or manual inspection, or a separate test. The profile can show a `PROMPT` reminding
the operator to check them.

Default sequence for each profile:

```
PRECHECK            (always; refuses energised harness)
SELFTEST
PROMPT  "Connect cable <Cn>, press Start"   wait=button
CONTINUITY polarity=both
WIGGLE  5 s         (optional, enabled per production decision)
RESULT
```

## Open questions to the cable owner

1. **M12 parts:** exact 17‑pin M12 part numbers and coding (A‑coded?) for both cable ends. The adapter
   needs the mating panel connectors (J3 male, J4 female), and the footprints are not in the KiCad
   standard library.
2. **Shells and shield:** are the M12 coupling nuts or shells metal, and are the cables shielded?
   If so, where does the shield/drain land? This decides whether channels B35/B36 are tested or left
   as don't‑care.
3. ~~Ground wires isolated?~~ **Answered 2026‑10‑06: not isolated (commoned).** Applied to C2.
   3b. **Does the same apply to C1** (ribbon → M12 female)? Are FFSD 1, 2, 5, 6, 11, 12, 16 joined inside
   the cable, or only on the Tap PCB? Currently modelled as separate conductors.
4. **FTSH variant on the Tap board** (e.g. FTSH‑108‑01‑L‑DV‑K, keyed/shrouded?) and FFSD polarisation.
   The adapter must use the same header so the cable is keyed the same way.
5. **Pico‑SPOX 0874371273:** confirm vertical vs right‑angle on the Fluidic board. The adapter copies it.
6. **Expected volume / insertions per day.** Pico‑SPOX and FTSH headers have low mating‑cycle ratings
   (tens to ~100 cycles; check datasheets). Plan J1/J2 on a small replaceable **wear board** and track
   insertions with the EEPROM usage counter.

## KiCad work (next)

* Library: FTSH‑108 header and Pico‑SPOX 87437‑1273 footprints (12 ckt; only the 14 ckt variant is in the
  standard library), M12 17‑pin panel connectors, from vendor drawings once Q1/Q4/Q5 are answered.
* Projects `hardware/adp0001_a` and `hardware/adp0001_b`. Each carries one DIN 41612 C 2×32 male
  right‑angle connector to the base (`docs/fixture-interface.md`). EEPROM on ‑A only. ‑B ties `PRESENT_N`
  to GND and leaves the ID pins open.
