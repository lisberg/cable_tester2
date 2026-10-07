# Cable tester – working notes for Claude

- Hardware is KiCad 10 (CI pinned to `kicad/kicad:10.0.6`), fabricated at JLCPCB. Decisions: `docs/decisions.md`.
- **Any ECAD work** (schematics, PCB layout, symbols/footprints, netlists, BOMs, ERC/DRC, fab outputs, any EDA
  tool): load the `ecad-house-style` skill (`.claude/skills/ecad-house-style/SKILL.md`) **before starting**,
  and follow its rules and checks.
- **Schematics are generated** by `hardware/gen/*.py`. Never hand-edit a generated `.kicad_sch`.
- Shared drawing helpers live in `hardware/gen/style.py`. Readability rules are enforced by
  `hardware/gen/layoutcheck.py` (`--strict` in CI).
- Visible schematic text is ASCII-only (the KiCad font lacks arrows, Ω, ≤ …).
