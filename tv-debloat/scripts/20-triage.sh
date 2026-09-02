#!/usr/bin/env bash
# Step (c): sort every package on the TV into 3 groups and print the table.
source "$(dirname "$0")/lib.sh"

SRC="$OUTDIR/before/packages-all.txt"
[ -f "$SRC" ] || { c_red "Run scripts/10-measure.sh before  first."; exit 1; }

G1="$ROOT/data/group1-junk-patterns.txt"
G2="$ROOT/data/group2-ask-patterns.txt"

match_any() { # match_any <pkg> <patternfile>
  local pkg="$1" f="$2" pat
  while IFS= read -r pat; do
    pat="${pat%%[[:space:]]*}"; [ -z "$pat" ] && continue
    case "$pat" in '#'*) continue;; esac
    # shellcheck disable=SC2254
    case "$pkg" in $pat) return 0;; esac
  done < "$f"
  return 1
}

: > "$ROOT/triage-group1.txt"; : > "$ROOT/triage-group2.txt"
: > "$ROOT/triage-group3.txt"; : > "$ROOT/triage-unknown.txt"

while IFS= read -r line; do
  pkg="${line#package:}"; pkg="$(printf '%s' "$pkg" | tr -d '\r')"
  [ -z "$pkg" ] && continue
  if is_protected "$pkg";            then echo "$pkg" >> "$ROOT/triage-group3.txt"
  elif match_any "$pkg" "$G2";       then echo "$pkg" >> "$ROOT/triage-group2.txt"
  elif match_any "$pkg" "$G1";       then echo "$pkg" >> "$ROOT/triage-group1.txt"
  else                                    echo "$pkg" >> "$ROOT/triage-unknown.txt"
  fi
done < "$SRC"

show() { printf '\n== %s (%s) ==\n' "$1" "$(grep -c . "$2")"; sed 's/^/  /' "$2"; }
show "GROUP 1 - junk, safe to disable"            "$ROOT/triage-group1.txt"
show "GROUP 2 - depends on you, I will ask"       "$ROOT/triage-group2.txt"
show "GROUP 3 - UNTOUCHABLE (protected.txt)"      "$ROOT/triage-group3.txt"
show "UNKNOWN - not classified, ASK before touching" "$ROOT/triage-unknown.txt"

cat <<'N'

Next: split triage-group1.txt into files of AT MOST 10 lines and feed them one
at a time to scripts/30-disable-batch.sh, testing between each batch.
  split -l 10 triage-group1.txt batch-   # creates batch-aa, batch-ab, ...
N
