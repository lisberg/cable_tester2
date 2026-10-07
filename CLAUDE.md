# Cable tester – working notes for Claude

- Hardware is KiCad 10 (CI pinned to `kicad/kicad:10.0.6`), fabricated at JLCPCB. Decisions: `docs/decisions.md`.
- **Schematics are generated** by `hardware/gen/*.py`. Never hand-edit a generated `.kicad_sch`.
  Follow the house style and checks in `.claude/skills/kicad-schematics/SKILL.md` for every schematic change.
- Shared drawing helpers live in `hardware/gen/style.py`. Readability rules are enforced by
  `hardware/gen/layoutcheck.py` (`--strict` in CI).
- Visible schematic text is ASCII-only (the KiCad font lacks arrows, Ω, ≤ …).
