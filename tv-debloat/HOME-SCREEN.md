# Replacing the Google TV home screen with FLauncher

Read this before running `scripts/60-flauncher.sh`. Three things in the plan
need correcting first.

## 1. FLauncher may not be on the Play Store

FLauncher is free and open source, but its reliable distribution channels are
**GitHub releases** and **F-Droid**, not the Play Store. There have been Play
listings at various points; I cannot verify from here whether one is live for
your region and TV today.

Check the Play Store on the TV first. If it is not there, sideload the APK:

```bash
# download flauncher-<version>.apk from the project's GitHub releases page
adb -s 192.168.1.43:5555 install flauncher.apk
```

Sideloading is an install, not a root or a flash — it does not touch Widevine
and does not factory-reset anything.

Alternatives if you dislike FLauncher: **Projectivy Launcher** and **Wolf
Launcher** are both on the Play Store for Android TV and both give an ad-free
app grid.

## 2. Google TV has no "set default launcher" screen

On a stock Google TV device there is no chooser that lets you pick FLauncher as
HOME. The realistic sequence is the reverse of the plan:

1. Install FLauncher.
2. Open it once from the apps row, so it has run and drawn its grid.
3. Disable `com.google.android.apps.tv.launcherx`.
4. FLauncher then becomes the only remaining HOME activity, so the HOME button
   lands there.

`scripts/60-flauncher.sh` does exactly this, and refuses to run if FLauncher is
not installed.

## 3. The black-screen risk is real

If step 3 runs and FLauncher is broken or missing, the TV boots to nothing.
Mitigations, in order:

- Keep the adb connection alive in a terminal during the swap. The recovery is
  one command: `adb -s 192.168.1.43:5555 shell pm enable com.google.android.apps.tv.launcherx`
- If adb is also gone, a factory reset from the TV's recovery menu restores it.
  That loses your settings but nothing else — it does **not** affect Widevine.

`com.google.android.apps.tv.launcherx` is on `data/protected.txt` deliberately.
`30-disable-batch.sh` will refuse it. `60-flauncher.sh` is the only path that
disables it, and only after the checks above.

## What this actually fixes

Removing launcherx removes the sponsored rows and "recommended for you" —
that is the single biggest visible win in this whole exercise. It does not
make the hardware faster.

## 4. Setting your own wallpaper — what works and what does not

Two separate things get called "the wallpaper", and on this TV they are not
connected:

- **The Android system wallpaper.** Nothing in the stock image can set it.
  `pm query-activities -a android.intent.action.SET_WALLPAPER` resolves only to
  `com.android.wallpaper.livepicker` (live wallpapers, disabled here), and
  `ATTACH_DATA` for `image/jpeg` resolves to nothing at all, because this build
  ships no DocumentsUI and no wallpaper cropper. `cmd wallpaper` reports
  "No shell command implementation", so adb alone cannot do it either.
- **The launcher's own background.** Each launcher draws its own and ignores the
  system one.

**Projectivy never displays the system wallpaper.** Its "Aucun" source is an
opaque black fill — verified by setting the system wallpaper to a solid green
image and seeing black anyway. A canyon photo showing during a cold start is
Android's task snapshot of the previous session, not the wallpaper. So a custom
background in Projectivy means its "Fichier Image/vidéo" source, which is
**Premium only (6,99 €)**; the same paywall also guards its
`SetBackgroundActivity`, so launching that by intent does not get around it.

To set the system wallpaper anyway, sideload **Fossify Gallery** (open source,
holds `SET_WALLPAPER`, registers both `SET_WALLPAPER` and `GET_CONTENT`, and
browses local files without needing a system picker):

```bash
curl -sLO https://github.com/FossifyOrg/Gallery/releases/download/1.13.1/gallery-28-foss-release.apk
adb -s 192.168.1.43:5555 install gallery-28-foss-release.apk
adb -s 192.168.1.43:5555 shell appops set org.fossify.gallery MANAGE_EXTERNAL_STORAGE allow
adb -s 192.168.1.43:5555 push wallpaper.jpg /sdcard/Pictures/Wallpapers/wallpaper.jpg
adb -s 192.168.1.43:5555 shell am start -a android.intent.action.ATTACH_DATA \
  -d file:///sdcard/Pictures/Wallpapers/wallpaper.jpg -t image/jpeg \
  -n org.fossify.gallery/.activities.SetWallpaperActivity
# then confirm on screen, and check that the id went up:
adb -s 192.168.1.43:5555 shell dumpsys wallpaper | grep 'User 0: id='
```

That `id=` is the only honest check. Apps can claim success without touching
`WallpaperManager` — "Photo Wallpaper" (`com.photo.wallpaper.tv.android`) prints
"Wallpaper configured!" and never requests `SET_WALLPAPER` at all; it only
repaints its own window.

Since Projectivy ignores the result, the system wallpaper is worth setting only
under FLauncher, whose "Custom" wallpaper is free — it just needs an image
picker on the device, which is exactly what Fossify Gallery restores.

## Driving the TV when the D-pad guessing gets tedious

`input tap` works on this TV, and `uiautomator` reads the screen, so menus can
be driven by label instead of counting arrow presses:

```bash
adb -s 192.168.1.43:5555 shell uiautomator dump /sdcard/ui.xml
adb -s 192.168.1.43:5555 shell cat /sdcard/ui.xml   # find text= / content-desc= and bounds=
adb -s 192.168.1.43:5555 shell input tap <x> <y>
```

Leanback headers (the left column in Projectivy's and other TV apps' settings)
are `clickable="false"` and only respond to real D-pad focus, so those still
need `input keyevent`.
