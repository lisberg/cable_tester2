# Hardware (KiCad 10)

All KiCad projects live **one level below `hardware/`**, so the project library tables can use
`${KIPRJMOD}/../lib/...` and resolve the same way everywhere.

| Path | Content |
|---|---|
| `lib/cable_tester.kicad_sym` | Project symbols (fields: `MPN`, `Manufacturer`, `LCSC`, `Datasheet`) |
| `lib/cable_tester.pretty/` | Project footprints |
| `lib/3dmodels/` | STEP models, referenced as `${KIPRJMOD}/../lib/3dmodels/<file>.step` |
| `_template/` | Base project: JLCPCB 4‑layer stack‑up, design rules, net classes, custom rules, title block |
| `proto40/` | Prototype 1 (controller + 40 + 40 nodes). **Schematic generated** by `gen/proto40.py`. No layout yet (`CI_STAGE` = schematic) |
| `gen/` | Schematic generators + design‑intent audit (see `gen/README.md`) |
| `sim/` | ngspice channel‑cell simulation and report |

## New board

```
scripts/new_board.sh <name> "<Board title>"
```

## Rules built into the template

* JLCPCB, JLC04161H‑7628, 1.6 mm, 4 layers, HASL lead‑free.
* Min track/space 0.1 mm. Min drill 0.3 mm, min via 0.5 mm. Copper‑to‑edge 0.3 mm. Silk ≥ 1.0 mm / 0.15 mm.
* Net classes by name pattern:

| Class | Pattern | Track / clearance |
|---|---|---|
| FIXTURE | `*EXT*`, `*SHELL*` | 0.2 / 0.2 mm, ≥ 0.3 mm to non‑fixture nets (`.kicad_dru`) |
| STIM | `*STIM*` | 0.25 / 0.2 mm |
| POWER | `*VBUS*`, `*VDD5*`, `*+3V3*`, `*GND*` | 0.4 / 0.15 mm, via 0.8/0.4 |
| SPI | `*SCK*`, `*MOSI*`, `*MISO*` | 0.2 / 0.15 mm, ≥ 0.5 mm to FIXTURE (`.kicad_dru`) |

* Text variables: `BOARD_NAME`, `REVISION`, `RELEASE_DATE`, `COMPANY`, `PROJECT`.

## Checks

`scripts/kicad_check.sh` runs ERC + DRC (with schematic parity) on every project. A project with a `CI_STAGE` file containing `schematic` skips DRC until layout starts. CI runs it on every pull
request (`.github/workflows/kicad.yml`), together with a regeneration check for generated schematics and the Proto40
netlist audit, and uploads schematic PDFs and BOMs. Tags `hw/<board>/vX.Y` also
produce Gerbers, drill, pick‑and‑place and STEP.
