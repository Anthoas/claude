# tv-debloat — TCL 43V6C

Scripts that carry out the debloat exactly as specified: measure first, disable
in batches of ten, record everything, undo with one command.

**Why you are running these instead of me:** `192.168.1.43` is a private address
on your home network. I run in a cloud container with no route to it, so I
cannot open an adb session to your TV. Verified, not assumed — see the note in
the conversation.

## Ground rules baked into the scripts

| Rule | How it is enforced |
|---|---|
| No uninstalls | `pm uninstall` appears nowhere; only `pm disable-user --user 0` |
| No root / no flashing | Not present, not suggested |
| Measure first | `10-measure.sh` refuses to report without a `before` capture |
| Max 10 per batch | `30-disable-batch.sh` aborts at 11 |
| Never-disable list | `data/protected.txt`, checked before every single disable |
| Written record | `kapatilanlar.txt` + `DEBLOAT-LOG.md`, appended automatically |

## Order of operations

```bash
git clone https://github.com/Anthoas/claude.git
cd claude/tv-debloat

# (a) install adb, pair, connect  — approve the dialog on the TV
bash scripts/00-setup.sh
# if the TV gave a port other than 5555:  export TV_ADDR=192.168.1.43:XXXXX

# (b) baseline
bash scripts/10-measure.sh before

# (c) sort into 3 groups, then send me measurements/before/packages-all.txt
bash scripts/20-triage.sh

# start with group 1, ten at a time, testing between each
split -l 10 triage-group1.txt batch-
bash scripts/30-disable-batch.sh batch-aa "group 1: demos and screensavers"
#   ... test the TV, then batch-ab, and so on

# (d)+(e) animation scales and cache trim
bash scripts/40-tweaks.sh

# (f) reboot and re-measure
adb -s 192.168.1.43:5555 reboot && sleep 60
adb connect 192.168.1.43:5555
bash scripts/10-measure.sh after
bash scripts/50-report.sh
```

Home screen swap: read [HOME-SCREEN.md](HOME-SCREEN.md), then
`bash scripts/60-flauncher.sh`.

## When the on-screen keyboard will not open

FLauncher is a Flutter app and its text fields do not always bring up the
system IME on Android TV. Type into it from the computer instead:

```bash
bash scripts/70-remote.sh shot          # see what the TV is showing
bash scripts/70-remote.sh type "Films"  # type into the focused field
bash scripts/70-remote.sh key ENTER     # confirm
bash scripts/70-remote.sh keys          # list the key names
```

`adb input text` sends a US keymap, so accented characters are dropped or
mangled - the script warns before sending them. Use `Series`, rename later
if it matters. Spaces are escaped automatically.

## The test after every batch

Inputs/Source button -> HDMI switch -> Netflix opens -> YouTube opens -> sound
-> on-screen keyboard in a search box -> Settings opens.

Anything broken: re-enable that whole batch first, then bisect it.

```bash
while read p; do adb -s 192.168.1.43:5555 shell pm enable $p; done < batch-aa
```

## Changing launcher

`65-launcher.sh` refuses to disable a launcher unless another enabled home
screen would remain, so it cannot leave the TV booting to a black screen.

```bash
bash scripts/65-launcher.sh status                          # what is HOME now
bash scripts/65-launcher.sh store com.spocky.projengmenu    # open its Play Store page on the TV
bash scripts/65-launcher.sh disable me.efesser.flauncher    # only once the new one works
```

`store` opens the listing by intent, so you do not have to type in the Play
Store search box - useful while the on-screen keyboard is broken.

## Wallpaper

```bash
bash scripts/80-wallpaper.sh ~/Pictures/fond.jpg
```

Reports the resolution the TV's UI actually renders at (the panel may be 4K
while Android draws at 1080p), warns if the image is smaller or not 16:9,
pushes it to `/sdcard/Pictures/` and nudges the media scanner so wallpaper
pickers list it.

## Undo everything

```bash
bash scripts/undo.sh --all && adb -s 192.168.1.43:5555 reboot
```

## Honest expectations

Disabling preinstalled packages frees a modest amount of RAM and removes some
background wakeups. It does not make a low-end SoC faster. In practice the
perceived speed-up comes almost entirely from two things: the 0.5 animation
scales, and replacing the ad-laden launcher. `dumpsys meminfo` before/after will
show a real but small difference — do not expect it to be dramatic, and I would
rather tell you that now than have you measure it and feel cheated.

`pm trim-caches` frees **storage**, not RAM.
