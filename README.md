# kindle-dashboard

An e-ink dashboard for a jailbroken Kindle that shows the time, the weather,
and the next Caltrain departures in both directions. It runs entirely on the
Kindle: no server, no subscription, no second computer. Each wake it fetches
data, draws an SVG, puts it on the screen, and goes back into deep sleep.

<img src="docs/preview.png" width="360" alt="Dashboard showing time, weather, Caltrain departures and a three-day forecast">

Built for a **Kindle Basic (8th/10th gen, 600×800)** on firmware 5.14.3,
jailbroken with WinterBreak. Other models should work with a different
template size.

## How it works

```
wake (RTC alarm)
  → Wi-Fi up → fetch Open-Meteo weather + 511.org Caltrain predictions
  → fill svg/template.svg → rsvg-convert to PNG → FBInk to the screen
  → pick the next wake time → deep sleep
```

The refresh schedule adapts to save battery: every 10 minutes during weekday
commute hours, every 20 minutes otherwise, nothing overnight when no trains
run, and always a wake just after the soonest train on screen departs.

## What you need

On the Kindle (via MRPI, from
[NiLuJe's snapshots thread](https://www.mobileread.com/forums/showthread.php?t=320564)):

- **Python 3**: `Update_python3_*_install_pw2_and_up.bin`. This also brings FBInk.
- **USBNetwork** (optional, for SSH debugging): `Update_usbnet_*_install_pw2_and_up.bin`

Downloaded yourself (not included in this repo):

| File | Where it goes | Source |
|---|---|---|
| `rsvg-convert`, `rsvg-convert-lib/` | `external/` | [4dcu-be/kual-dashboard](https://github.com/4dcu-be/kual-dashboard), `dashboard/external/` |
| `cacert.pem` | `certs/` | https://curl.se/ca/cacert.pem |
| `DejaVuSans.ttf`, `DejaVuSans-Bold.ttf` | `/mnt/us/fonts/` on the Kindle | https://dejavu-fonts.github.io/ |
| A 511.org API key (free) | `api_key.txt` | https://511.org/open-data/token |

## Install

1. Download this repo and add the files from the table above.
2. Copy `api_key.example.txt` to `api_key.txt` and paste your 511 key into it.
3. Copy the folder to the Kindle as **`extensions/dashboard/`**. The name
   matters: `menu.json` refers to that path.
4. Open KUAL → **Weather Dashboard** → **Refresh once (test)**. This draws a
   single frame without stopping the Kindle UI, so it's safe to retry.
5. When that works, choose **Start**.

To get the normal Kindle back, hold the power button until it reboots. The
dashboard never starts on its own.

## Configuration

In `bin/run.py`:

| Setting | Purpose |
|---|---|
| `LAT`, `LON` | Weather location |
| `UNITS` | `fahrenheit` or `celsius` |
| `TZ_API`, `TZ_LOCAL` | Timezone, as an IANA name and a POSIX rule string (also set `TZ` in `bin/common.sh`) |
| `STOP_NB`, `STOP_SB` | Caltrain stop codes (Menlo Park is 70161 / 70162) |
| `PEAK_INTERVAL`, `OFFPEAK_INTERVAL`, `MIN_INTERVAL` | Refresh schedule |
| `NIGHT_START`, `NIGHT_END` | Overnight window with no refreshes |

In `bin/start.sh`, `REFRESH_SECONDS=""` uses the adaptive schedule. Set a
number of seconds to force a fixed interval for testing, never below 180:
each wake makes two 511 requests, and 511 allows 60 per hour per key.

The layout is `svg/template.svg`, a fixed 600×800 SVG with `{{TOKENS}}` that
`run.py` fills in. Open it in a browser to preview edits.

## Troubleshooting

Everything is logged to `dashboard.log` in the extension folder, including how
long each stage took and how much free space is left. Read it over USB, but
give the script time to finish first: plugging in unmounts the user storage
and kills a run in progress.

Things that bit during development:

- **No menu entry in KUAL.** KUAL finds extensions by `config.xml`, not
  `menu.json`. Both must sit directly in `extensions/dashboard/`.
- **Start leaves a white screen.** Stopping the Kindle framework kills KUAL's
  child processes, so `start.sh` relaunches itself detached first. Allow a
  minute or two for the first draw.
- **Times off by hours.** The Kindle has no timezone database. Named zones
  like `America/Los_Angeles` silently fall back to UTC, so a POSIX rule string
  is used instead. Its Python also lacks `time.tzset()`.
- **`CERTIFICATE_VERIFY_FAILED`.** `certs/cacert.pem` is missing or stale.
- **`No space left on device`.** If you block OTA updates by filling the
  storage, leave ~150 MB free for the dashboard; updates need far more.
- **Never wakes.** The wake-capable RTC is `rtc1` on most models but `rtc0` on
  some. Check `ls /sys/class/rtc/` and edit `RTC=` in `bin/start.sh`.
- **Slow first render.** The font index is built once and cached in
  `fonts/cache/`; later runs are much faster.

## Credits

- [FBInk](https://github.com/NiLuJe/FBInk), the Python package, and KUAL/MRPI
  builds by NiLuJe
- [KindleModding](https://kindlemodding.org) for WinterBreak and the guides
- [4dcu-be/kual-dashboard](https://github.com/4dcu-be/kual-dashboard) and
  [x-magic/kindle-weather-stand-alone](https://github.com/x-magic/kindle-weather-stand-alone)
  for the on-device SVG approach and the `rsvg-convert` build
- Weather from [Open-Meteo](https://open-meteo.com); transit data from
  [511.org](https://511.org/open-data)

## License

MIT, see [LICENSE](LICENSE). Third-party binaries you download keep their own
licenses.
