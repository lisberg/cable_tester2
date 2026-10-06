# Fixture interface – base ↔ adapter connector

Status: **v1 (frozen for Proto40 and Rev A)** · Decision D7

## Connector

| | Base (Proto40 / bank card) | Adapter |
|---|---|---|
| Type | DIN 41612 **type C, 2 × 32 (rows a + c)**, female, vertical, THT | DIN 41612 type C 2 × 32, male, right‑angle, THT |
| KiCad footprint | `Connector_DIN:DIN41612_C_2x32_Female_Vertical_THT` | `Connector_DIN:DIN41612_C_2x32_Male_Horizontal_THT` |
| Performance level | Level 1 (≥ 500 mating cycles) or level 2 (≥ 400) | same |

* The base carries the female (protected contacts, no exposed pins on the expensive board).
  The adapter is a card standing perpendicular to the base, with the customer connectors on its top edge.
* Rows a and c sit 5.08 mm apart, so routing is easy and clearance for the 30 V rating is comfortable.
* If adapters are swapped many times a day, fit a "connector saver" (male‑female DIN extender) on the base.

## Pinout (one connector per bank side)

| Pin | Signal | Pin | Signal |
|---|---|---|---|
| a1 | GND | c1 | GND |
| a2 … a26 | **EXT01 … EXT25** | c2 … c26 | **EXT26 … EXT50** |
| a27 | GND | c27 | GND |
| a28 | **SHELL** (channel 51) | c28 | **PRESENT_N** (adapter ties to GND, base pulls up) |
| a29 | ID_SDA | c29 | ID_WP (base drives; adapter pull‑up = protected) |
| a30 | ID_SCL | c30 | ID_A0 (base strap: side A = 0, side B = 1) |
| a31 | ID_VCC (+3.3 V, current‑limited on base) | c31 | GND |
| a32 | GND | c32 | GND |

Totals: 50 nodes + 1 shell + 6 ID/control + 7 GND = 64.

* `EXTnn` = tester channel nn of that bank side. On Proto40 only EXT01–EXT40 (and SHELL) are populated.
  EXT41–EXT50 are left unconnected on the base, so the pinout stays identical to Rev A.
* EEPROM address: adapter ties A1 = A2 = GND and takes A0 from `ID_A0`. The same adapter design therefore
  works on either side.
* `ID_VCC` is fed through ≥ 47 Ω + polyfuse (or a load switch) on the base, so a damaged adapter cannot
  pull down the controller's 3.3 V rail.
* Fixture nodes are rated ±24 V (design 30 V, see review F9). ID and control pins are **not**. Adapter layout
  must keep DUT‑side copper ≥ 0.3 mm from ID nets (FIXTURE net‑class rule in the template).
