# Schematic generators

The Proto40 schematics are **generated**. Edit `proto40.py`, then regenerate. Do not hand‑edit
`hardware/proto40/*.kicad_sch`: CI regenerates them and fails if the committed files differ.

| File | Purpose |
|---|---|
| `sexpr.py` | Minimal KiCad S‑expression reader/writer |
| `schgen.py` | Generator core: library symbol import (incl. `extends` flattening), placement, labels and power symbols on pin ends, multi‑instance hierarchical sheets with per‑instance references, deterministic UUIDs |
| `make_lib.py` | Builds `hardware/lib/cable_tester.kicad_sym` (VDD5 power symbol, TMUX1308) |
| `proto40.py` | Proto40 design: root → Power, MCU, Control, SideA/SideB (`side.kicad_sch`) → G1…G6 (`group8.kicad_sch`) |
| `check_proto40.py` | Design‑intent audit on the exported netlist (channel cells, chains, rails, straps, loopback) |

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

Connections are made with labels on short wire stubs at the pin ends rather than drawn wires. That is
electrically exact and ERC‑verified, but less pretty than hand‑drawn sheets. When layout starts, the
schematic can be "frozen" (remove `CI_STAGE`, stop regenerating) and tidied by hand in KiCad if preferred.
