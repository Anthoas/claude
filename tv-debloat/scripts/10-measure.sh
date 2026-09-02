#!/usr/bin/env bash
# Step (b)/(f): capture the measurements. Usage: 10-measure.sh before|after|<label>
source "$(dirname "$0")/lib.sh"
require_device

LABEL="${1:?usage: 10-measure.sh <label>   e.g. before | after}"
D="$OUTDIR/$LABEL"
mkdir -p "$D"

echo "Capturing into $D ..."
tvsh dumpsys meminfo            > "$D/dumpsys-meminfo.txt"     2>&1
tvsh cat /proc/meminfo          > "$D/proc-meminfo.txt"        2>&1
tvsh pm list packages -s        > "$D/packages-system.txt"     2>&1
tvsh pm list packages -d        > "$D/packages-disabled.txt"   2>&1
tvsh pm list packages -3        > "$D/packages-thirdparty.txt" 2>&1
tvsh pm list packages           > "$D/packages-all.txt"        2>&1
tvsh getprop                    > "$D/getprop.txt"             2>&1
{ tvsh settings get global window_animation_scale
  tvsh settings get global transition_animation_scale
  tvsh settings get global animator_duration_scale; } > "$D/animation-scales.txt" 2>&1
sed -i.bak 's/\r$//' "$D"/*.txt 2>/dev/null; rm -f "$D"/*.bak

# one-line summary
{
  echo "label: $LABEL"
  echo "taken: $(date -u '+%Y-%m-%d %H:%M:%SZ')"
  grep -E '^[[:space:]]*(Total RAM|Free RAM|Used RAM|Lost RAM|ZRAM):' "$D/dumpsys-meminfo.txt" | sed 's/^ *//'
  echo "packages_total:    $(grep -c . "$D/packages-all.txt")"
  echo "packages_system:   $(grep -c . "$D/packages-system.txt")"
  echo "packages_disabled: $(grep -c . "$D/packages-disabled.txt")"
} | tee "$D/summary.txt"
c_grn "Saved."
