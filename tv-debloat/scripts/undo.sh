#!/usr/bin/env bash
# Re-enable everything in kapatilanlar.txt and restore animation scales.
source "$(dirname "$0")/lib.sh"
require_device

if [ ! -s "$DISABLED_FILE" ]; then echo "Nothing recorded in $DISABLED_FILE"; exit 0; fi
echo "Re-enabling $(grep -c . "$DISABLED_FILE") package(s)..."
while IFS= read -r p; do
  [ -z "$p" ] && continue
  printf '  %-55s %s\n' "$p" "$(tvsh pm enable "$p" 2>&1 | tr -d '\r')"
done < "$DISABLED_FILE"

if [ "${1:-}" = "--all" ]; then
  for k in window_animation_scale transition_animation_scale animator_duration_scale; do
    tvsh settings put global "$k" 1.0
  done
  echo "Animation scales reset to 1.0"
fi
c_grn "Undo complete. Reboot with: adb -s $TV_ADDR reboot"
