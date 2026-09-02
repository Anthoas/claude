#!/usr/bin/env bash
# Rule 4: disable AT MOST 10 packages, record them, then stop for testing.
# Usage: 30-disable-batch.sh <file-with-package-names> ["reason"]
source "$(dirname "$0")/lib.sh"
require_device

BATCH="${1:?usage: 30-disable-batch.sh <batchfile> [reason]}"
REASON="${2:-batch disable}"
[ -f "$BATCH" ] || { c_red "No such file: $BATCH"; exit 1; }

PKGS=$(grep -v '^[[:space:]]*#' "$BATCH" | tr -d '\r' | grep . || true)
N=$(printf '%s\n' "$PKGS" | grep -c . || true)
[ "$N" -eq 0 ] && { c_red "Batch file is empty."; exit 1; }
if [ "$N" -gt 10 ]; then c_red "Refusing: $N packages, the limit is 10 (rule 4)."; exit 1; fi

echo "About to disable $N package(s):"
BAD=0
for p in $PKGS; do
  if is_protected "$p"; then c_red "  BLOCKED  $p  (on the never-disable list)"; BAD=1
  elif ! pkg_installed "$p"; then c_ylw "  MISSING  $p  (not installed on this TV)"
  elif pkg_disabled "$p"; then c_ylw "  ALREADY  $p  (already disabled)"
  else echo "  ok       $p"; fi
done
[ "$BAD" -eq 1 ] && { c_red "Aborting: the batch contains a protected package."; exit 1; }

read -r -p "Proceed? [y/N] " a; case "$a" in y|Y) ;; *) echo "Cancelled."; exit 0;; esac

mkdir -p "$(dirname "$DISABLED_FILE")"; touch "$DISABLED_FILE" "$LOG_FILE"
STAMP=$(date -u '+%Y-%m-%d %H:%M:%SZ')
printf '\n### Batch %s — %s\n\n| package | result | undo |\n|---|---|---|\n' "$(basename "$BATCH")" "$STAMP" >> "$LOG_FILE"
echo "_Reason: $REASON_" >> "$LOG_FILE"

for p in $PKGS; do
  pkg_installed "$p" || continue
  pkg_disabled "$p"  && continue
  OUT=$(tvsh pm disable-user --user 0 "$p" 2>&1 | tr -d '\r')
  if printf '%s' "$OUT" | grep -q 'new state: disabled'; then
    c_grn "  disabled  $p"
    grep -qx "$p" "$DISABLED_FILE" || echo "$p" >> "$DISABLED_FILE"
    printf '| `%s` | disabled | `adb -s %s shell pm enable %s` |\n' "$p" "$TV_ADDR" "$p" >> "$LOG_FILE"
  else
    c_red  "  FAILED    $p  -> $OUT"
    printf '| `%s` | FAILED: %s | n/a |\n' "$p" "$OUT" >> "$LOG_FILE"
  fi
done

cat <<T

=========================================================================
STOP. Test the TV now, with the remote, before the next batch:
  1. Inputs / Source button  -> can you switch to HDMI?
  2. Netflix opens?
  3. YouTube opens?
  4. Sound works?
  5. On-screen keyboard appears in a search box?
  6. Settings opens?
If ANYTHING is broken, undo this batch immediately:
  while read p; do adb -s $TV_ADDR shell pm enable \$p; done < $BATCH
=========================================================================
T
