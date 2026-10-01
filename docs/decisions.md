# Decision log

| # | Date | Decision | Notes |
|---|---|---|---|
| D1 | 2026‑10‑01 | Symmetric channel cells: every node can be driven and sensed | Review F1 |
| D3 | 2026‑10‑01 | 5 V analog/logic domain (VDD5 from USB VBUS, ratiometric). MCU at 3.3 V with HCT/AHCT and LVC level interfaces | Review F8. Changed from the proposed 3.3 V |
| D5 | 2026‑10‑01 | Survive ±24 V DC on any fixture node (design margin to 30 V). Rs = 4.7 kΩ 1206, external low‑leakage clamps, VDD5 shunt clamp, TVS standoff ≥ 28 V | Review F9. Changed from the proposed ±12 V. Consequence: Rbias 470 kΩ, guaranteed max net size 32 nodes (F3) |
| D8 | 2026‑10‑01 | Fabrication at JLCPCB. 4‑layer JLC04161H‑7628 stack‑up. Conservative no‑surcharge rules (0.1 mm min track/space, 0.3 mm min drill) | Encoded in `hardware/_template` |
| D9 | 2026‑10‑01 | KiCad 10. CI pinned to `kicad/kicad:10.0.6` | |
| D9b | 2026‑10‑01 | ERC/DRC run on pull requests (plus fab outputs on `hw/*` tags) | `.github/workflows/kicad.yml`. kicad‑cli only, no KiBot dependency |
| D10 | 2026‑10‑01 | Adapter EEPROM carries identity + embedded test profiles | `docs/adapter-eeprom-format.md` |
| D12 | 2026‑10‑01 | First adapter: ADP‑0001 Tap/M12/Fluidic (cables C1, C2 and chain C3) | `fixtures/ADP0001_tap_fluidic` |

Open: D2 (50 vs 64 nodes/side), D4 (confirm values by simulation), D6 (backplane), D7 (fixture connector),
D11 (Proto40 size, proposed so ADP‑0001 fits).
