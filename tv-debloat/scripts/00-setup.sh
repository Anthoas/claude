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
      brew install android-platform-tools ;;
    linux)
      sudo apt-get update && sudo apt-get install -y adb ;;
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

echo
echo "== Connecting to the TV =="
IP="${TV_ADDR%%:*}"
adb start-server >/dev/null 2>&1

echo "Trying plain connect on 5555 (works on Android 10 and earlier, and on"
echo "Android 11+ once wireless debugging has been paired at least once)..."
if adb connect "$IP:5555" | tee /dev/stderr | grep -q "connected to"; then
  c_grn "Connected."
  c_ylw ">>> LOOK AT THE TV NOW. If it shows 'Allow USB debugging from this"
  c_ylw ">>> computer?', tick 'Always allow' and press OK. Then re-run this script."
else
  c_ylw "Plain connect failed. This TV is almost certainly Android 11+, so it"
  c_ylw "needs pairing first. On the TV go to:"
  cat <<'P'
    Settings -> System -> About -> press "Build" 7 times   (already done for you)
    Settings -> System -> Developer options -> Wireless debugging -> ON
    -> "Pair device with pairing code"
  The TV will show:  IP:PORT  and a 6-digit code.
  NOTE: the PAIRING port is random and is NOT 5555.
P
  read -r -p "Pairing IP:PORT shown on the TV (blank to skip): " PP
  if [ -n "$PP" ]; then
    adb pair "$PP"
    echo "Now, still on the Wireless debugging screen, read the CONNECTION"
    echo "IP:PORT (the one at the top, also usually not 5555)."
    read -r -p "Connection IP:PORT: " CP
    [ -n "$CP" ] && adb connect "$CP"
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
