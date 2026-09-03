#!/usr/bin/env bash
# Push a wallpaper to the TV and tell you whether its size actually fits.
# Usage: 80-wallpaper.sh ~/path/to/image.jpg
source "$(dirname "$0")/lib.sh"

# Validate the argument before touching the network: a typo in the path should
# not need a reachable TV to be reported.
IMG="${1:?usage: 80-wallpaper.sh /path/to/image.jpg}"
[ -f "$IMG" ] || { c_red "No such file: $IMG"; exit 1; }
[ -r "$IMG" ] || { c_red "Cannot read: $IMG"; exit 1; }

require_device

echo "== What resolution does the TV's UI actually render at? =="
# The panel may be 4K while the Android UI renders at 1080p. The UI figure is
# the one a wallpaper is scaled against, so that is the one to match.
WM=$(tvsh wm size 2>/dev/null | tr -d '\r')
printf '%s\n' "$WM" | sed 's/^/  /'
TVW=$(printf '%s' "$WM" | grep -oE '[0-9]+x[0-9]+' | tail -1 | cut -dx -f1)
TVH=$(printf '%s' "$WM" | grep -oE '[0-9]+x[0-9]+' | tail -1 | cut -dx -f2)

echo
echo "== The image you are pushing =="
if command -v python3 >/dev/null 2>&1; then
  DIMS=$(python3 - "$IMG" <<'PY'
import struct,sys
p=sys.argv[1]; d=open(p,'rb').read()
try:
    if d[:2]==b'\xff\xd8':
        i=2
        while i<len(d):
            if d[i]!=0xFF: i+=1; continue
            m=d[i+1]
            if m in (0xC0,0xC1,0xC2):
                h,w=struct.unpack('>HH',d[i+5:i+9]); print(f"{w} {h}"); break
            i+=2+struct.unpack('>H',d[i+2:i+4])[0]
    elif d[:8]==b'\x89PNG\r\n\x1a\n':
        w,h=struct.unpack('>II',d[16:24]); print(f"{w} {h}")
except Exception:
    pass
PY
)
  IMGW=$(printf '%s' "$DIMS" | cut -d' ' -f1)
  IMGH=$(printf '%s' "$DIMS" | cut -d' ' -f2)
fi

if [ -n "${IMGW:-}" ] && [ -n "${IMGH:-}" ]; then
  echo "  ${IMGW}x${IMGH}  ($(du -h "$IMG" | cut -f1))"
  if [ -n "${TVW:-}" ] && [ "$IMGW" -lt "$TVW" ] 2>/dev/null; then
    c_ylw "  Narrower than the TV UI (${TVW}px). It will be upscaled and look soft."
  fi
  # 16:9 check, in tenths to stay in integer arithmetic
  R=$(( IMGW * 10 / IMGH ))
  [ "$R" -ne 17 ] && c_ylw "  Not 16:9 (ratio ~${R}/10). It will be cropped or letterboxed."
else
  echo "  (could not read the dimensions - only JPEG and PNG are inspected)"
fi

echo
DEST="/sdcard/Pictures/$(basename "$IMG")"
echo "== Pushing to $DEST =="
# Pictures/ rather than Download/: wallpaper pickers look there first.
tvsh mkdir -p /sdcard/Pictures
adbx push "$IMG" "$DEST" 2>&1 | tail -1
if tvsh ls "$DEST" >/dev/null 2>&1; then
  c_grn "On the TV."
  # Make the gallery/media scanner notice it, or pickers will not list it.
  tvsh am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE \
    -d "file://$DEST" >/dev/null 2>&1 && echo "  media scanner notified"
  cat <<S

Now select it in the launcher:
  FLauncher  Settings -> Wallpaper  (needs a file explorer installed on the TV)
  Projectivy Settings -> Wallpaper  (custom wallpapers are a premium feature)
S
else
  c_red "Push seems to have failed - $DEST is not there."; exit 1
fi
