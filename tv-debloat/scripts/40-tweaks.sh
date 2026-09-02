#!/usr/bin/env bash
# Steps (d) + (e): animation scales and cache trim.
source "$(dirname "$0")/lib.sh"
require_device

echo "== (d) Halving animation speeds =="
for k in window_animation_scale transition_animation_scale animator_duration_scale; do
  tvsh settings put global "$k" 0.5
  printf '  %-28s -> %s\n' "$k" "$(tvsh settings get global "$k" | tr -d '\r')"
done
echo "Undo: adb -s $TV_ADDR shell settings put global <key> 1.0"

echo
echo "== (e) Trimming caches =="
# pm trim-caches needs a target free-space figure; a huge one evicts everything.
tvsh pm trim-caches 999G 2>&1 | tr -d '\r'
c_grn "Done. This frees storage, not RAM."
