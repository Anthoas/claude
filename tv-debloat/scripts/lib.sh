#!/usr/bin/env bash
# Shared helpers. Sourced by every script.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TV_ADDR="${TV_ADDR:-192.168.1.43:5555}"
OUTDIR="$ROOT/measurements"
DISABLED_FILE="$ROOT/kapatilanlar.txt"
LOG_FILE="$ROOT/DEBLOAT-LOG.md"
PROTECTED="$ROOT/data/protected.txt"

c_red()  { printf '\033[31m%s\033[0m\n' "$*"; }
c_grn()  { printf '\033[32m%s\033[0m\n' "$*"; }
c_ylw()  { printf '\033[33m%s\033[0m\n' "$*"; }

adbx()  { adb -s "$TV_ADDR" "$@"; }
tvsh()  { adb -s "$TV_ADDR" shell "$@"; }

require_device() {
  if ! command -v adb >/dev/null 2>&1; then
    c_red "adb is not installed. Run scripts/00-setup.sh first."; exit 1
  fi
  if ! adb devices | grep -qE "^${TV_ADDR}[[:space:]]+device$"; then
    c_red "TV $TV_ADDR is not connected."
    echo "Current adb devices:"; adb devices
    echo "Try: adb connect $TV_ADDR   (and approve the dialog on the TV)"
    exit 1
  fi
}

# is_protected <package> -> 0 if it must never be disabled
is_protected() {
  local pkg="$1" pat
  while IFS= read -r pat; do
    pat="${pat%%[[:space:]]*}"
    [ -z "$pat" ] && continue
    case "$pat" in '#'*) continue;; esac
    # shellcheck disable=SC2254
    case "$pkg" in $pat) return 0;; esac
  done < "$PROTECTED"
  return 1
}

pkg_installed() { tvsh pm list packages 2>/dev/null | tr -d '\r' | grep -qx "package:$1"; }
pkg_disabled()  { tvsh pm list packages -d 2>/dev/null | tr -d '\r' | grep -qx "package:$1"; }
