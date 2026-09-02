#!/usr/bin/env bash
# Replace the Google TV home screen with FLauncher. Read HOME-SCREEN.md first.
source "$(dirname "$0")/lib.sh"
require_device

FL="me.efesser.flauncher"
LX="com.google.android.apps.tv.launcherx"

echo "== Checking FLauncher is installed =="
if ! pkg_installed "$FL"; then
  c_red "$FL is NOT installed. Install it on the TV first, then re-run."
  echo "See HOME-SCREEN.md for where to get it."
  exit 1
fi
c_grn "FLauncher found."

echo
echo "== HOME activities currently registered =="
tvsh cmd package query-activities -a android.intent.action.MAIN -c android.intent.category.HOME 2>/dev/null | tr -d '\r' | grep -E 'packageName|name=' | sed 's/^/  /'

echo
c_ylw "This is the only irreversible-feeling step. Keep this terminal open."
c_ylw "If the screen goes black after disabling launcherx, run:"
echo   "    adb -s $TV_ADDR shell pm enable $LX"
echo
read -r -p "Have you opened FLauncher once on the TV already? [y/N] " a
case "$a" in y|Y) ;; *) echo "Do that first."; exit 0;; esac
read -r -p "Disable $LX now? [y/N] " a
case "$a" in y|Y) ;; *) echo "Cancelled."; exit 0;; esac

# launcherx is on the protected list on purpose; this script is the only
# sanctioned way past it, and only after the checks above.
OUT=$(tvsh pm disable-user --user 0 "$LX" 2>&1 | tr -d '\r')
echo "$OUT"
if printf '%s' "$OUT" | grep -q 'new state: disabled'; then
  grep -qx "$LX" "$DISABLED_FILE" 2>/dev/null || echo "$LX" >> "$DISABLED_FILE"
  printf '\n### Home screen swap — %s\n\n| package | result | undo |\n|---|---|---|\n| `%s` | disabled, FLauncher is now HOME | `adb -s %s shell pm enable %s` |\n' \
    "$(date -u '+%Y-%m-%d %H:%M:%SZ')" "$LX" "$TV_ADDR" "$LX" >> "$LOG_FILE"
  c_grn "Done. Rebooting to confirm FLauncher survives a restart..."
  read -r -p "Reboot the TV now? [y/N] " a
  case "$a" in y|Y) adbx reboot ;; esac
fi
