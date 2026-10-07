---
name: ecad-house-style
description: Mandatory house style, workflow and checks for ALL ECAD / electronics CAD work. Use automatically, before doing anything else, whenever the task involves schematics, schematic capture, PCB layout, footprints, symbols, netlists, BOMs, ERC/DRC, fabrication outputs or hardware design files in any EDA tool (KiCad, Altium, OrCAD, Eagle, EasyEDA, generated or hand-made), including creating, editing, re-laying-out, reviewing or exporting them, and starting a new board.
---

# ECAD house style and workflow

**Scope:** every ECAD task – schematics, PCB layout, libraries (symbols/footprints), netlists, BOMs and
fabrication outputs, in any EDA tool. The drawing rules in §1 apply to every schematic, whatever tool
draws it (KiCad, Altium, …). For PCB / library / output work, follow §4 together with the checks in §3.

Schematics in this repo are **generated** from Python (`hardware/gen/`) and committed as KiCad 10 files.
Never hand-edit a generated `.kicad_sch`; change the generator and regenerate. These rules came from the
reviewer's feedback on Proto40 and apply to **every** schematic going forward.

## 1. Drawing rules (mandatory)

**Connectivity must be visible**
1. Signal flow left → right. Inputs on the left, outputs on the right, supplies on top, GND at the bottom.
2. A functional block is drawn **with wires**, not as isolated parts joined by labels: e.g. channel cell
   EXT → TVS / Rs → NODE → Rbias / C, an LDO with its input/output caps, a transistor clamp with its bias
   network.
3. Shared nets are **rails**: one continuous wire with junction dots (bias rail, control ladder across
   repeated sub-sheets, signals fanned out to several sheets on the root sheet).
4. Net labels only where a net genuinely leaves its block or sheet, for 1-to-many fan-outs to ICs
   (e.g. NODE0…7 to a mux and a shift register), and on dense connector pin columns.
5. Hierarchy: wire sheet pins to each other on the parent sheet where they line up; order sheet pins so
   wires run straight.

**Every pin gets its own wire**
6. Every connected pin leaves through **its own short wire (≥ 2.54 mm)**. A part never sits directly on
   another wire, on another pin, or on a power symbol.
7. A part that connects to a line (pull-up, pull-down, decoupling cap, TVS, test point, PWR_FLAG, power
   symbol on a rail) **taps** it: short stub from the part's pin to the line, junction dot at the line.
8. Power symbols always sit at the end of a stub: GND hangs down, rails point up. On dense pin columns
   (MCU, connectors, sheet pins), turn the power symbol **sideways** instead of pointing it into the
   neighbouring row.
9. Decoupling: the rail symbol sits above the IC power pin, and the caps hang off a horizontal wire beside
   the body (one cap per 12.7 mm, text beside each cap). Use the free side of the IC.

**Text never touches anything**
10. Reference/value text sits beside the body: vertical two-pin parts → right (or left), horizontal → above /
    below, ICs → outside a corner. The side is chosen from the **pin axis**, not the body shape.
11. No text on wires, pin lines, bodies, the DNP cross, power symbols or other text.
12. A local label sits above its wire, so it must never be directly below a hierarchical/global label on
    a 2.54 mm pitch. Give it a longer stub so it starts beyond the neighbour's text.
13. Field text on rotated parts must read horizontally (the generator handles 90/180/270 – don't override).
14. Visible text is ASCII only: the KiCad font lacks arrows, box-drawing, ≤ ≥ × Ω. Write `->`, `<=`, `x`,
    `Ohm` in sheet notes. Unicode is fine in hidden fields (MPN, Note).

**Hygiene**
15. Unused pins get a no-connect flag (`sheet.unused_nc()` at the end of each sheet builder).
16. Reference designators encode location: `<prefix><sheet base + n>` (see `hardware/gen/README.md`).
17. Every part carries `Footprint`, and `MPN` (+ `Manufacturer`) where known. Mark open selections as `TBD: …`.

## 2. How to build a sheet

Use the generator core and the shared house-style helpers. Don't re-implement placement.

```python
from schgen import Project, Sheet               # core: symbols, wires, labels, hierarchy, auto-junctions
from style import (U, R, C, hier, decap, pull, tap_tp, tap_power, tap_flag, r_down, cap_down,
                   FP_R0603, FP_C0603, ...)       # house-style blocks (rule-compliant by construction)
import layoutcheck
```

| Need | Use |
|---|---|
| Part | `s.add(lib_id, prefix, (x, y), rot=…, value=…, footprint=…, fields={…}, text="auto")` |
| Wire / polyline | `s.wire(...)`, `s.path(p0, p1, …)` (points may be `sym.pos(pin)`) |
| Pin → label / power / NC | `s.connect(sym, pin, net, kind=None|"hier"|"global", stub=…, rotate=…)` (`net=None` → NC) |
| Pull-up / pull-down on a line | `pull(s, x, y, rail, value, up=True)` |
| Cap or resistor hanging off a line | `cap_down(...)`, `r_down(...)` |
| Decoupling at an IC power pin | `decap(s, ic, "VCC", rail="VDD5", values=("100n",), side=±1)` |
| Test point / power symbol / PWR_FLAG on a line | `tap_tp`, `tap_power`, `tap_flag` |
| Sub-sheet | `s.sheet(name, child_sheet, (x, y), (w, h), [(pin, type, "L"/"R"), (None, None, "L") for a gap])` |
| Write project | `Project(name, root, base_of).write(out_dir)` |

Coordinates are on the 1.27 mm grid (prefer 2.54). Leave ≥ 2.54 mm between any part, text and wire. New
library parts go into `hardware/gen/make_lib.py` (project library), never into a schematic by hand.

## 3. Checks (all must pass before committing)

Run in the KiCad 10 environment (CI image `kicad/kicad:10.0.6`; locally `KICAD_SYMBOL_DIR` → the KiCad 10
symbol directory):

```bash
python3 hardware/gen/make_lib.py
python3 hardware/gen/<design>.py --strict        # layoutcheck: must report "layout issues: 0"
kicad-cli sch erc --severity-all hardware/<board>/<board>.kicad_sch            # must be 0 violations
kicad-cli sch export netlist -o /tmp/<board>.net hardware/<board>/<board>.kicad_sch
python3 hardware/gen/check_<board>.py /tmp/<board>.net                         # design-intent audit
scripts/kicad_check.sh                                                          # ERC (+ DRC once laid out)
```

Each design also needs:
- a **design-intent audit** (`check_<board>.py`) that finds parts by sheet path and follows pins. ERC
  cannot check intent.
- a CI step that regenerates with `--strict` and fails on `git diff` (see `.github/workflows/kicad.yml`).

`layoutcheck.py` estimates text extents and ignores pin numbers, so passing it is necessary but not
sufficient. **Always render and look** at every sheet, zooming into dense areas, before handing it over:

```bash
kicad-cli sch export pdf -o /tmp/<board>.pdf hardware/<board>/<board>.kicad_sch
pdftoppm -r 110 -png /tmp/<board>.pdf /tmp/page        # whole pages
pdftoppm -r 200 -png -f N -l N -x X -y Y -W 900 -H 600 /tmp/<board>.pdf /tmp/zoom   # dense areas
```

If you find a problem by eye that the checker missed, **extend `layoutcheck.py`** so it is caught
automatically next time, then fix the layout.

## 4. PCB layout, libraries and outputs

- Boards start from `hardware/_template` (`scripts/new_board.sh`): JLCPCB 4-layer stack-up, design rules,
  net classes (FIXTURE / STIM / POWER / SPI) and custom clearance rules. Don't loosen them per board without
  recording why in `docs/decisions.md`.
- Repeated channels: lay out one group, then replicate it with KiCad multichannel tools – never hand-copy.
- Fixture-side protection (TVS, then series R) sits next to the connector. Keep FIXTURE nets ≥ 0.3 mm from
  logic and ≥ 0.5 mm from SPI clocks (enforced by the `.kicad_dru` rules).
- New symbols/footprints go into the project library (`hardware/gen/make_lib.py` for symbols,
  `hardware/lib/cable_tester.pretty` for footprints), with MPN/Manufacturer/LCSC fields. Never embed
  one-off parts in a design.
- DRC (with schematic parity) must be clean before fabrication outputs. Outputs come from
  `scripts/kicad_outputs.sh` / CI tags `hw/<board>/vX.Y`, never hand-exported.
- In other EDA tools (e.g. Altium), apply the same rules. Where the automated checks can't run, do the
  equivalent review manually and say so.

## 5. Review checklist (before handing ECAD work to the user)

- [ ] `--strict` layout check 0, ERC 0 (all severities), design-intent audit PASS, regeneration deterministic
- [ ] Every block wired; labels only where a net leaves its block
- [ ] No part directly on a wire/pin/power symbol; every tap has a junction dot
- [ ] No text touching wires, pins, bodies or other text (checked on rendered pages)
- [ ] Notes ASCII-only; footprints and MPNs filled (or `TBD: …`)
- [ ] Rendered PDF sent to the user, plus a summary of what changed
