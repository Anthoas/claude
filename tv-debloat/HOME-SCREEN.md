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
