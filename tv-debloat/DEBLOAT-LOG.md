# DEBLOAT-LOG

Every change made to the TCL 43V6C, why, and how to undo it.
`scripts/30-disable-batch.sh` appends a table here automatically after each batch.

- TV: TCL 43V6C
- Address: `192.168.1.43:5555` (override with `export TV_ADDR=...`)
- Rule: `pm disable-user --user 0` only. **`pm uninstall` is never used.**
- Record of disabled packages: [`kapatilanlar.txt`](kapatilanlar.txt)

## Undo everything

```bash
bash scripts/undo.sh --all && adb -s 192.168.1.43:5555 reboot
```

## Change history

_(batches are appended below this line)_

### Batch batch-aa — 2026-09-02 21:04:28Z

| package | result | undo |
|---|---|---|

### Batch batch-aa — 2026-09-02 21:04:47Z

| package | result | undo |
|---|---|---|
_Reason: group 1: demos, screensavers, setup wizards, telemetry_
| `com.google.android.apps.mediashell` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.google.android.apps.mediashell` |
| `com.google.android.onetimeinitializer` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.google.android.onetimeinitializer` |
| `com.google.android.tungsten.setupwraith` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.google.android.tungsten.setupwraith` |
| `com.android.statementservice` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.android.statementservice` |
| `com.tcl.logkit` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.tcl.logkit` |
| `com.android.printspooler` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.android.printspooler` |
| `com.android.dreams.basic` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.android.dreams.basic` |
| `com.google.android.partnersetup` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.google.android.partnersetup` |
| `com.google.android.feedback` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.google.android.feedback` |
| `com.google.android.syncadapters.calendar` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.google.android.syncadapters.calendar` |

### Batch batch-ab — 2026-09-02 21:06:41Z

| package | result | undo |
|---|---|---|
_Reason: group 1: wallpaper live picker + wallpaper backup_
| `com.android.wallpaper.livepicker` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.android.wallpaper.livepicker` |
| `com.android.wallpaperbackup` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.android.wallpaperbackup` |

### Batch batch-g2-a — 2026-09-02 21:07:00Z

| package | result | undo |
|---|---|---|
_Reason: group 2: not used per user (Netflix TokenManager, YT Music, Talkback, TTS, Play Movies, Katniss, dreamx, Miracast, ChannelPlus, Contacts)_
| `com.netflix.tokenmanager` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.netflix.tokenmanager` |
| `com.google.android.youtube.tvmusic` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.google.android.youtube.tvmusic` |
| `com.google.android.marvin.talkback` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.google.android.marvin.talkback` |
| `com.google.android.tts` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.google.android.tts` |
| `com.google.android.videos` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.google.android.videos` |
| `com.google.android.katniss` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.google.android.katniss` |
| `com.google.android.apps.tv.dreamx` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.google.android.apps.tv.dreamx` |
| `com.tcl.miracast` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.tcl.miracast` |
| `com.tcl.channelplus` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.tcl.channelplus` |
| `com.android.providers.contacts` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.android.providers.contacts` |

### Batch batch-g2-b — 2026-09-02 21:07:30Z

| package | result | undo |
|---|---|---|
_Reason: group 2: calendar provider, not used_
| `com.android.providers.calendar` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.android.providers.calendar` |

### Home screen swap — 2026-09-02 21:10:49Z

| package | result | undo |
|---|---|---|
| `com.google.android.apps.tv.launcherx` | disabled, FLauncher is now HOME | `adb -s 192.168.1.43:5555 shell pm enable com.google.android.apps.tv.launcherx` |

### Batch batch-u1 — 2026-09-02 21:17:56Z

| package | result | undo |
|---|---|---|
_Reason: unknown-triage batch 1: TCL demo/setup/marketing junk + Samba ACR tracking + userdictionary_
| `com.tcl.esticker` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.tcl.esticker` |
| `com.tcl.initsetup` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.tcl.initsetup` |
| `com.tcl.ocean.instructions` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.tcl.ocean.instructions` |
| `com.tcl.useragreement` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.tcl.useragreement` |
| `com.tcl.repairguide` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.tcl.repairguide` |
| `com.tcl.exhibit` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.tcl.exhibit` |
| `tv.samba.ssm.ui` | disabled | `adb -s 192.168.1.43:5555 shell pm enable tv.samba.ssm.ui` |
| `com.android.providers.userdictionary` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.android.providers.userdictionary` |
| `com.tcl.smartalexa` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.tcl.smartalexa` |
| `com.tcl.gamebar` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.tcl.gamebar` |

### Batch batch-u2 — 2026-09-02 21:19:05Z

| package | result | undo |
|---|---|---|
_Reason: unknown-triage batch 2: TCL smart features redundant with FLauncher (not used per user)_
| `com.tcl.usercenter` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.tcl.usercenter` |
| `com.tcl.dashboard` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.tcl.dashboard` |
| `com.tcl.ui_mediaCenter` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.tcl.ui_mediaCenter` |
| `com.tcl.interactive` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.tcl.interactive` |
| `com.tcl.t_solo` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.tcl.t_solo` |
| `com.tcl.hearaid` | disabled | `adb -s 192.168.1.43:5555 shell pm enable com.tcl.hearaid` |

### Home screen swap — 2026-09-03 13:42:24Z

| package | result | undo |
|---|---|---|
| `me.efesser.flauncher` | disabled, Projectivy Launcher (`com.spocky.projengmenu`) is now HOME | `adb -s 192.168.1.43:5555 shell pm enable me.efesser.flauncher` |
