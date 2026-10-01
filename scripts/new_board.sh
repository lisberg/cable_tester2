#!/usr/bin/env bash
# Create a new KiCad project from hardware/_template.
# Usage: scripts/new_board.sh <name> "<Board title>"
set -euo pipefail
name="$1"; title="${2:-$1}"
src=hardware/_template; dst="hardware/$name"
[[ -e "$dst" ]] && { echo "$dst exists"; exit 1; }
mkdir -p "$dst"
for f in "$src"/_template.*; do cp "$f" "$dst/$name.${f##*.}"; done
cp "$src/sym-lib-table" "$src/fp-lib-table" "$dst/"
python3 - "$dst/$name.kicad_pro" "$title" <<'PY'
import json, sys, uuid, re, pathlib
p = pathlib.Path(sys.argv[1]); d = json.loads(p.read_text())
d["text_variables"]["BOARD_NAME"] = sys.argv[2]
d["meta"]["filename"] = p.name
for sh in d.get("schematic", {}).get("top_level_sheets", []):
    sh["filename"] = p.with_suffix(".kicad_sch").name
    sh["name"] = p.stem
p.write_text(json.dumps(d, indent=2) + "\n")
# give the new schematic its own root UUID
sch = p.with_suffix(".kicad_sch"); s = sch.read_text()
s = re.sub(r'\(uuid "[0-9a-f-]+"\)', f'(uuid "{uuid.uuid4()}")', s, count=1)
sch.write_text(s)
PY
echo "Created $dst"
