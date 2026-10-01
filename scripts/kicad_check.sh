#!/usr/bin/env bash
# Run ERC + DRC (with schematic parity) on every KiCad project under hardware/.
# Usage: scripts/kicad_check.sh [output_dir]     (requires kicad-cli 10.x on PATH)
set -uo pipefail
OUT="${1:-build/checks}"
mkdir -p "$OUT"
fail=0
shopt -s nullglob
for pro in hardware/*/*.kicad_pro; do
  dir=$(dirname "$pro"); name=$(basename "$pro" .kicad_pro)
  echo "=== $dir/$name"
  if [ -f "$dir/$name.kicad_sch" ]; then
    kicad-cli sch erc --exit-code-violations --severity-error \
      -o "$OUT/$name.erc.rpt" "$dir/$name.kicad_sch" || { echo "ERC FAILED: $name"; fail=1; }
  fi
  if [ -f "$dir/$name.kicad_pcb" ]; then
    kicad-cli pcb drc --exit-code-violations --severity-error --schematic-parity \
      -o "$OUT/$name.drc.rpt" "$dir/$name.kicad_pcb" || { echo "DRC FAILED: $name"; fail=1; }
  fi
done
exit $fail
