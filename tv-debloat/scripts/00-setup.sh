#!/usr/bin/env bash
# Step (a): install adb for this OS, then connect to the TV.
source "$(dirname "$0")/lib.sh"

echo "== Detecting operating system =="
OS="unknown"
case "$(uname -s)" in
  Darwin) OS="macos" ;;
  Linux)  OS="linux" ;;
  MINGW*|MSYS*|CYGWIN*) OS="windows" ;;
esac
echo "OS: $OS"

if command -v adb >/dev/null 2>&1; then
  c_grn "adb already installed: $(adb version | head -1)"
else
  echo "adb not found. Installing..."
  case "$OS" in
    macos)
      command -v brew >/dev/null 2>&1 || { c_red "Homebrew missing. Install from https://brew.sh then re-run."; exit 1; }
      # android-platform-tools is a Homebrew CASK, not a formula. `brew install`
      # usually falls back to casks, but not on every configuration, so be explicit.
      brew install --cask android-platform-tools \
        || brew install android-platform-tools \
        || true ;;
    linux)
      sudo apt-get update || c_ylw "apt-get update reported errors; continuing anyway"
      sudo apt-get install -y adb || sudo apt-get install -y android-tools-adb || true ;;
    windows)
      c_ylw "On Windows do this by hand:"
      cat <<'W'
  1. Download https://dl.google.com/android/repository/platform-tools-latest-windows.zip
  2. Unzip to C:\platform-tools
  3. Add C:\platform-tools to PATH:
       setx PATH "%PATH%;C:\platform-tools"
  4. Open a NEW terminal and re-run this script.
W
      exit 1 ;;
    *) c_red "Unknown OS. Install platform-tools manually."; exit 1 ;;
  esac
fi


# Do not continue without a working adb: every failure past this point would
# be reported as a TV problem when the real cause is a missing binary.
if ! command -v adb >/dev/null 2>&1; then
  c_red "adb is STILL not installed - the install step above failed."
  c_red "Stopping here. Nothing below would tell you anything useful about the TV."
  echo
  echo "Fix the install first, then re-run this script. Options:"
  echo "  Debian/Ubuntu : sudo apt-get install -y adb"
  echo "                  (if apt fails on a broken third-party PPA, disable it:"
  echo "                   ls /etc/apt/sources.list.d/  then move the offender aside)"
  echo "  macOS         : brew install --cask android-platform-tools"
  echo "                  (no Homebrew? install it from https://brew.sh first)"
  echo "  Fedora        : sudo dnf install android-tools"
  echo "  Arch          : sudo pacman -S android-tools"
  echo "  Any Linux/mac : download platform-tools from"
  echo "                  https://developer.android.com/tools/releases/platform-tools"
  echo "                  unzip it, and add the folder to PATH"
  exit 1
fi
c_grn "adb is available: $(adb version | head -1)"

# adb connect against an unreachable host does not fail fast, it hangs on the
# TCP handshake. Bound it so the script reports something instead of freezing.
# macOS has no timeout(1) unless coreutils is installed; fall back to plain run.
TMO=""
if command -v timeout  >/dev/null 2>&1; then TMO="timeout 20"
elif command -v gtimeout >/dev/null 2>&1; then TMO="gtimeout 20"
else c_ylw "note: no timeout(1) found; a connect to an unreachable TV may hang."
fi

echo
echo "== Connecting to the TV =="
IP="${TV_ADDR%%:*}"
adb start-server >/dev/null 2>&1

echo "Trying plain connect on 5555 (works on Android 10 and earlier, and on"
echo "Android 11+ once wireless debugging has been paired at least once)..."
CONN_OUT="$($TMO adb connect "$IP:5555" 2>&1)"; CONN_RC=$?
printf '%s\n' "$CONN_OUT"
if [ "$CONN_RC" -eq 124 ]; then
  c_red "Timed out after 20s with no answer from $IP:5555."
  c_red "Nothing is listening there, or nothing routes there. This is a network"
  c_red "problem, not an adb problem - pairing will not fix it. Check that your"
  c_red "computer and the TV are on the same subnet before going further."
fi
if printf '%s' "$CONN_OUT" | grep -q "connected to"; then
  c_grn "Connected."
  c_ylw ">>> LOOK AT THE TV NOW. If it shows 'Allow USB debugging from this"
  c_ylw ">>> computer?', tick 'Always allow' and press OK. Then re-run this script."
else
  c_ylw "Could not connect to $IP:5555. Possible causes, in order of likelihood:"
  cat <<'C'
    1. The TV is Android 11+ and has never been paired -> pair below.
    2. Wireless debugging is off, or the TV toggled it off after a reboot.
    3. The TV is asleep. Wake it with the remote and try again.
    4. Wrong IP. Check Settings -> Network -> the TV's actual address.
    5. Your computer and the TV are on different subnets or VLANs
       (guest wifi is a common culprit).
C
  c_ylw "If it is cause 1, pair now. On the TV go to:"
  cat <<'P'
    Settings -> System -> About -> press "Build" 7 times   (already done for you)
    Settings -> System -> Developer options -> Wireless debugging -> ON
    -> "Pair device with pairing code"
  The TV will show:  IP:PORT  and a 6-digit code.
  NOTE: the PAIRING port is random and is NOT 5555.
P
  # An agent or a CI job runs this with stdin on /dev/null, which makes every
  # read below return empty instantly and silently skip pairing. Say so loudly
  # instead of pretending the step ran.
  if [ ! -t 0 ]; then
    c_red "stdin is not a terminal, so the pairing prompts cannot be answered."
    c_red "Pairing was SKIPPED. This step is interactive by nature: the code is"
    c_red "shown on the TV screen and changes every time."
    echo
    echo "Run these two commands yourself, in a real terminal:"
    echo "    adb pair <PAIRING_IP:PORT>      # both shown on the TV, port is random"
    echo "    adb connect <CONNECT_IP:PORT>   # a DIFFERENT port, also on that screen"
    echo
    echo "Then re-run this script, or skip straight to:"
    echo "    bash scripts/10-measure.sh before"
    exit 2
  fi
  read -r -p "Pairing IP:PORT shown on the TV (blank to skip): " PP
  if [ -n "$PP" ]; then
    adb pair "$PP"
    echo "Now, still on the Wireless debugging screen, read the CONNECTION"
    echo "IP:PORT (the one at the top, also usually not 5555)."
    read -r -p "Connection IP:PORT: " CP
    [ -n "$CP" ] && $TMO adb connect "$CP"
    c_ylw "If that port is not 5555, run every later script with:"
    echo "    export TV_ADDR=$CP"
  fi
fi

echo
adb devices -l
echo
echo "== TV identity =="
tvsh getprop ro.product.model 2>/dev/null
tvsh getprop ro.build.version.release 2>/dev/null
tvsh getprop ro.build.version.sdk 2>/dev/null
