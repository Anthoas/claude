#!/usr/bin/env bash
# Manage which launcher is the home screen, without ever ending up with none.
#
#   65-launcher.sh status              what is registered as HOME, and its state
#   65-launcher.sh store <package>     open that app's Play Store page on the TV
#   65-launcher.sh disable <package>   disable a launcher, only if another remains
source "$(dirname "$0")/lib.sh"
[ $# -ge 1 ] || { sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
require_device

# Every package registering a HOME activity, deduplicated.
home_packages() {
  tvsh cmd package query-activities -a android.intent.action.MAIN \
       -c android.intent.category.HOME 2>/dev/null \
    | tr -d '\r' | grep -oE 'packageName=[A-Za-z0-9_.]+' \
    | cut -d= -f2 | sort -u
}

case "$1" in
  status)
    echo "== Packages registering a HOME activity =="
    HP=$(home_packages)
    [ -z "$HP" ] && { c_red "None found. That is bad - the TV has no home screen."; exit 1; }
    ENABLED=0
    for p in $HP; do
      if pkg_disabled "$p"; then printf '  %-45s %s\n' "$p" "DISABLED"
      else printf '  %-45s %s\n' "$p" "enabled"; ENABLED=$((ENABLED+1)); fi
    done
    echo
    echo "Enabled home screens: $ENABLED"
    [ "$ENABLED" -eq 0 ] && c_red "ZERO enabled. Re-enable one now or the TV boots to nothing."
    [ "$ENABLED" -gt 1 ] && c_ylw "More than one: pressing HOME shows a chooser. Pick yours, tick 'Always'."
    ;;

  store)
    PKG="${2:?usage: 65-launcher.sh store com.spocky.projengmenu}"
    # Opening the listing by intent avoids typing in the Play Store search box,
    # which matters when the on-screen keyboard will not come up.
    tvsh am start -a android.intent.action.VIEW -d "market://details?id=$PKG" \
      >/dev/null 2>&1
    c_grn "Play Store page for $PKG opened on the TV."
    echo "Press OK on 'Install' with the remote, or:"
    echo "    bash scripts/70-remote.sh key OK"
    echo "Then confirm it landed:"
    echo "    bash scripts/65-launcher.sh status"
    ;;

  disable)
    PKG="${2:?usage: 65-launcher.sh disable <package>}"
    pkg_installed "$PKG" || { c_red "$PKG is not installed."; exit 1; }
    # The whole point of this script: never leave the TV with no home screen.
    SURVIVORS=0
    for p in $(home_packages); do
      [ "$p" = "$PKG" ] && continue
      pkg_disabled "$p" || SURVIVORS=$((SURVIVORS+1))
    done
    if [ "$SURVIVORS" -eq 0 ]; then
      c_red "REFUSING: disabling $PKG would leave no enabled home screen."
      c_red "The TV would boot to a black screen. Install and open another"
      c_red "launcher first, then re-run this."
      exit 1
    fi
    echo "$SURVIVORS other enabled home screen(s) would remain."
    read -r -p "Disable $PKG? [y/N] " a; case "$a" in y|Y) ;; *) echo "Cancelled."; exit 0;; esac
    OUT=$(tvsh pm disable-user --user 0 "$PKG" 2>&1 | tr -d '\r'); echo "$OUT"
    if printf '%s' "$OUT" | grep -q 'new state: disabled'; then
      grep -qx "$PKG" "$DISABLED_FILE" 2>/dev/null || echo "$PKG" >> "$DISABLED_FILE"
      printf '\n### Launcher change — %s\n\n| package | result | undo |\n|---|---|---|\n| `%s` | disabled as home screen | `adb -s %s shell pm enable %s` |\n' \
        "$(date -u '+%Y-%m-%d %H:%M:%SZ')" "$PKG" "$TV_ADDR" "$PKG" >> "$LOG_FILE"
      c_grn "Done. Press HOME on the remote to check before rebooting."
    fi
    ;;
  *) sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
