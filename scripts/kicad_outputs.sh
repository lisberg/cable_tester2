#!/usr/bin/env bash
# Export review/fab outputs for every KiCad project under hardware/.
# Usage: scripts/kicad_outputs.sh [output_dir] [--fab]
#   default: schematic PDF + BOM CSV        --fab: also Gerbers, drill, positions, STEP
set -euo pipefail
OUT="${1:-build/outputs}"; FAB="${2:-}"
shopt -s nullglob
for pro in hardware/*/*.kicad_pro; do
  dir=$(dirname "$pro"); name=$(basename "$pro" .kicad_pro)
  [[ "$name" == _template ]] && continue
  o="$OUT/$name"; mkdir -p "$o"
  sch="$dir/$name.kicad_sch"; pcb="$dir/$name.kicad_pcb"
  kicad-cli sch export pdf -o "$o/$name-schematic.pdf" "$sch"
  kicad-cli sch export bom -o "$o/$name-bom.csv" \
    --fields 'Reference,Value,Footprint,MPN,Manufacturer,LCSC,${QUANTITY},${DNP}' \
    --labels 'Designator,Value,Footprint,MPN,Manufacturer,LCSC,Qty,DNP' \
    --group-by 'Value,Footprint,MPN' --ref-range-delimiter '' "$sch"
  if [[ "$FAB" == --fab && -f "$pcb" ]]; then
    mkdir -p "$o/gerbers"
    kicad-cli pcb export gerbers -o "$o/gerbers/" --board-plot-params "$pcb"
    kicad-cli pcb export drill -o "$o/gerbers/" --format excellon --excellon-separate-th "$pcb"
    kicad-cli pcb export pos -o "$o/$name-pos.csv" --format csv --units mm --side both "$pcb"
    kicad-cli pcb export step -o "$o/$name.step" --subst-models "$pcb" || echo "STEP export skipped"
    (cd "$o" && zip -qr "$name-gerbers.zip" gerbers)
  fi
done
