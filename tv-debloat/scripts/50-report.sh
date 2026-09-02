#!/usr/bin/env bash
# Deliverable 1 + 3: before/after RAM table and the single undo command.
source "$(dirname "$0")/lib.sh"

B="$OUTDIR/before"; A="$OUTDIR/after"
[ -f "$B/summary.txt" ] || { c_red "Missing measurements/before — run 10-measure.sh before"; exit 1; }
[ -f "$A/summary.txt" ] || { c_red "Missing measurements/after  — run 10-measure.sh after";  exit 1; }

val() { grep -E "^${2}:" "$1/summary.txt" | head -1 | sed -E 's/^[^:]+:[[:space:]]*//'; }

echo "## 1. RAM, before vs after"
echo
printf '| metric | before | after |\n|---|---|---|\n'
for m in "Total RAM" "Free RAM" "Used RAM" "Lost RAM" "packages_total" "packages_disabled"; do
  printf '| %s | %s | %s |\n' "$m" "$(val "$B" "$m")" "$(val "$A" "$m")"
done

echo
echo "## 2. Packages disabled ($(grep -c . "$DISABLED_FILE" 2>/dev/null || echo 0))"
echo
if [ -s "$DISABLED_FILE" ]; then sed 's/^/- `/; s/$/`/' "$DISABLED_FILE"; else echo "_none_"; fi

echo
echo "## 3. Single command that undoes everything"
echo
cat <<C
    bash tv-debloat/scripts/undo.sh --all && adb -s $TV_ADDR reboot

or without the scripts, one line:

    while read p; do adb -s $TV_ADDR shell pm enable \$p; done < tv-debloat/kapatilanlar.txt; \\
    for k in window_animation_scale transition_animation_scale animator_duration_scale; do \\
      adb -s $TV_ADDR shell settings put global \$k 1.0; done; adb -s $TV_ADDR reboot
C
