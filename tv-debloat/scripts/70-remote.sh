#!/usr/bin/env bash
# Drive the TV from the computer when the on-screen keyboard will not appear.
#
#   70-remote.sh type "Films"        type text into the focused field
#   70-remote.sh key ENTER           send one remote/keyboard key
#   70-remote.sh shot [file.png]     screenshot what the TV is showing
#   70-remote.sh keys                list the useful key names
source "$(dirname "$0")/lib.sh"

usage() { sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
[ $# -ge 1 ] || usage

case "$1" in
  keys)
    cat <<'K'
  ENTER  DEL(backspace)  BACK  HOME  SEARCH
  UP  DOWN  LEFT  RIGHT  OK(select)
  Send them with:  70-remote.sh key ENTER
K
    exit 0 ;;
esac

require_device

case "$1" in
  type)
    TEXT="${2:?usage: 70-remote.sh type \"your text\"}"
    # `input text` uses a US keymap: non-ASCII is silently dropped or mangled.
    if printf '%s' "$TEXT" | LC_ALL=C grep -q '[^ -~]'; then
      c_ylw "Warning: '$TEXT' contains non-ASCII characters (accents, etc)."
      c_ylw "adb input text cannot send those - they will be dropped or wrong."
      c_ylw "Use an unaccented name (Series, Enfants) and rename later if needed."
      read -r -p "Send anyway? [y/N] " a; case "$a" in y|Y) ;; *) exit 1;; esac
    fi
    # A literal space ends the argument; %s is the documented escape.
    ESCAPED=$(printf '%s' "$TEXT" | sed 's/ /%s/g')
    echo "Typing into whatever field currently has focus on the TV:"
    echo "  \"$TEXT\""
    tvsh input text "$ESCAPED"
    c_grn "Sent. Look at the TV - the text should be in the field."
    ;;
  key)
    K="${2:?usage: 70-remote.sh key ENTER}"
    case "$(printf '%s' "$K" | tr '[:lower:]' '[:upper:]')" in
      ENTER)  C=66 ;;  DEL|BACKSPACE) C=67 ;;
      BACK)   C=4  ;;  HOME)          C=3  ;;
      SEARCH) C=84 ;;
      UP)     C=19 ;;  DOWN)  C=20 ;;
      LEFT)   C=21 ;;  RIGHT) C=22 ;;
      OK|SELECT|CENTER) C=23 ;;
      *) c_red "Unknown key '$K'. Run: 70-remote.sh keys"; exit 1 ;;
    esac
    tvsh input keyevent "$C" && c_grn "Sent $K (keyevent $C)"
    ;;
  shot)
    OUT="${2:-tv-screen.png}"
    # exec-out keeps the PNG binary intact; `shell screencap` mangles newlines.
    adbx exec-out screencap -p > "$OUT" 2>/dev/null
    if [ -s "$OUT" ]; then c_grn "Saved $OUT ($(wc -c < "$OUT") bytes). Open it to see the TV."
    else c_red "Screenshot failed or came back empty."; rm -f "$OUT"; exit 1; fi
    ;;
  *) usage ;;
esac
