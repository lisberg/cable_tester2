# Schematic generators

The Proto40 schematics are **generated**. Edit `proto40.py`, then regenerate. Do not hand‑edit
`hardware/proto40/*.kicad_sch`: CI regenerates them and fails if the committed files differ.

| File | Purpose |
|---|---|
| `sexpr.py` | Minimal KiCad S‑expression reader/writer |
| `schgen.py` | Generator core: library symbol import (incl. `extends` flattening), placement, labels and power symbols on pin ends, multi‑instance hierarchical sheets with per‑instance references, deterministic UUIDs |
| `make_lib.py` | Builds `hardware/lib/cable_tester.kicad_sym` (VDD5 power symbol, TMUX1308) |
| `proto40.py` | Proto40 design: root → Power, MCU, Control, SideA/SideB (`side.kicad_sch`) → G1…G6 (`group8.kicad_sch`) |
| `check_proto40.py` | Design‑intent audit on the exported netlist (channel cells, chains, rails, straps, loopback). Finds parts by sheet path and follows pins, so it survives layout changes |
| `layoutcheck.py` | Readability check: text/text, text/body, text/wire overlaps and wires through symbol bodies. `proto40.py --strict` fails on any issue (CI uses it) |

## Regenerate and check

```
export KICAD_SYMBOL_DIR=/usr/share/kicad/symbols      # KiCad 10 standard symbols
python3 hardware/gen/make_lib.py
python3 hardware/gen/proto40.py
kicad-cli sch erc --severity-all hardware/proto40/proto40.kicad_sch
kicad-cli sch export netlist -o /tmp/p.net hardware/proto40/proto40.kicad_sch
python3 hardware/gen/check_proto40.py /tmp/p.net
```

## Reference designators

They encode the location: `<prefix><sheet base + n>`.

| Sheet | Base | Example |
|---|---|---|
| Power | 100 | U102 = LM66100 |
| MCU | 200 | U201 = STM32C071 |
| Control | 300 | U305 = STIM driver |
| SideA / SideB | 1000 / 2000 | J1001 = side A fixture connector |
| SideA/G1…G6 | 1100…1600 | R1101 = side A, group 1, channel 0 Rs |
| SideB/G1…G6 | 2100…2600 | |

## Style

The sheets are drawn the way an engineer would draw them:

* Signal flow is left to right. Each functional block is **wired**: channel cells (EXT → TVS / Rs → NODE →
  Rbias / C), decoupling caps on the IC power pin they serve, pull‑ups standing on the line they pull.
* Shared nets are drawn as **rails with junction dots**: BIAS_RAIL in a group, the control ladder (ADDR, EN,
  CLK, PL, BIAS) across the six groups, the shared control nets from Control to both sides on the root sheet.
* The '165 sense chain is drawn as a visible daisy chain. The cross‑side LOOP is a wire on the root sheet.
* Net labels are used only where a net leaves its block (e.g. NODE0…7 from the cells to the mux and the
  '165, MCU GPIOs to their peripherals) and for dense connector pins.
* Reference and value text is placed from the real symbol body graphics, away from pins and wires.
  `layoutcheck.py` enforces it.

* **Every pin leaves through its own short wire** (≥ 2.54 mm): no part stands directly on another wire,
  another pin or a power symbol. Pull-ups, caps, TVS diodes, test points and power flags tap a line with a
  short stub and a junction dot. `layoutcheck.py` enforces this (pin/pin, pin/wire).
* On dense pin columns (MCU, connectors) local labels never sit directly under a hierarchical label.
  They get longer stubs, or the power tie is drawn sideways.

Junctions are added automatically wherever three connections meet or a wire/pin ends on a wire.
