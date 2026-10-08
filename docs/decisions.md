# Decision log

| # | Date | Decision | Notes |
|---|---|---|---|
| D1 | 2026‑10‑01 | Symmetric channel cells: every node can be driven and sensed | Review F1 |
| D3 | 2026‑10‑01 | 5 V analog/logic domain (VDD5 from USB VBUS, ratiometric). MCU at 3.3 V with HCT/AHCT and LVC level interfaces | Review F8. Changed from the proposed 3.3 V |
| D5 | 2026‑10‑01 | Survive ±24 V DC on any fixture node (design margin to 30 V). Rs = 4.7 kΩ 1206, VDD5 shunt clamp, TVS standoff ≥ 28 V. External low‑leakage clamps dropped on Proto40: the IC input diodes take the current anyway, Rs is the limit (plan F9, `hardware/sim/report.md` §4) | Review F9. Changed from the proposed ±12 V. Consequence: see D4 |
| D2 | 2026‑10‑06 | 50 nodes + shell per bank side | Set by the 64‑pin fixture connector |
| D4 | 2026‑10‑06 | Rs 4.7 kΩ (1206), Rbias 680 kΩ, leakage budget ≤ 1 µA/node at ≤ 40 °C. Guaranteed net size 32 nodes (64 typical) | ngspice: `hardware/sim/report.md` |
| D7 | 2026‑10‑06 | Fixture connector DIN 41612 type C 2×32: female vertical on base, male right‑angle on adapter | `docs/fixture-interface.md` |
| D8 | 2026‑10‑01 | Fabrication at JLCPCB. 4‑layer JLC04161H‑7628 stack‑up. Conservative no‑surcharge rules (0.1 mm min track/space, 0.3 mm min drill) | Encoded in `hardware/_template` |
| D9 | 2026‑10‑01 | KiCad 10. CI pinned to `kicad/kicad:10.0.6` | |
| D9b | 2026‑10‑01 | ERC/DRC run on pull requests (plus fab outputs on `hw/*` tags) | `.github/workflows/kicad.yml`. kicad‑cli only, no KiBot dependency |
| D10 | 2026‑10‑01 | Adapter EEPROM carries identity + embedded test profiles | `docs/adapter-eeprom-format.md` |
| D11 | 2026‑10‑06 | Prototype = Proto40 (40 + 40 nodes) | |
| D12 | 2026‑10‑01 | First adapter: ADP‑0001 Tap/M12/Fluidic (cables C1, C2 and chain C3) | `fixtures/ADP0001_tap_fluidic` |
| D13 | 2026‑10‑06 | ADP‑0001 harness only: GND wires are commoned (one GND net in C2) | Harness‑specific, **not** a general tester rule. Each cable profile states its own GND topology. C1 still to confirm |
| D14 | 2026‑10‑08 | Fixture ID lines get ESD (PESD5V0S1BA) at the connector + series R (220 Ω I²C, 1 kΩ WP/A0/PRESENT). ID_VCC limited by 100 Ω 1206, no polyfuse. These lines are protected against ESD and miswiring at logic levels, **not** against the 24 V node fault | Schematic review 2026‑10‑08 (S1, S2). `docs/fixture-interface.md` |
| D15 | 2026‑10‑08 | VDD5 shunt clamp sized for 300 mA: collector ballast 6.8 Ω 2512 (0.6 W), BCP53 ≈ 1 W, needs ≥ 1 cm² collector copper | Schematic review 2026‑10‑08 (P4). Plan F9 "rail pumping" |

Open: D6 (backplane, Phase 4).
