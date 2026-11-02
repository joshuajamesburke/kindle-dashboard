#!/bin/sh
# Kindle weather dashboard - draw, deep sleep, wake, repeat.
# Launched from KUAL. Log lands in ../dashboard.log

# KUAL runs us as its child. Stopping the framework below kills KUAL's
# whole process tree, which would take this script with it. So first,
# relaunch ourselves detached from KUAL and let the original exit.
if [ -z "$DASH_DETACHED" ]; then
    export DASH_DETACHED=1
    if command -v setsid >/dev/null 2>&1; then
        setsid /bin/sh "$0" < /dev/null > /dev/null 2>&1 &
    else
        nohup /bin/sh "$0" < /dev/null > /dev/null 2>&1 &
    fi
    exit 0
fi

. "$(dirname "$0")/common.sh"
echo "running detached, pid $$"

# Leave empty for the smart schedule in run.py (peak/off-peak, wakes after
# each train leaves, sleeps overnight). Set a number of seconds to force a
# fixed interval for testing. Minimum 180: each wake makes two 511 calls
# and 511 allows 60 per hour.
REFRESH_SECONDS=""
WIFI_SETTLE=25           # after waking, Wi-Fi needs time to reassociate
RTC=/sys/class/rtc/rtc1/wakealarm   # some models use rtc0

if [ ! -w "$RTC" ]; then
    echo "WARNING: $RTC not writable. Available RTCs:"
    ls /sys/class/rtc/
fi

# --- take over the screen ---------------------------------------------
echo "stopping framework"
/etc/init.d/framework stop 2>/dev/null || stop lab126_gui 2>/dev/null
lipc-set-prop com.lab126.powerd preventScreenSaver 1 2>/dev/null

# The framework tears down asynchronously and paints the screen white
# as it goes. Draw before it finishes and the white wins.
echo "waiting for framework teardown"
sleep 10

"$FBINK" -q -c
"$FBINK" -q -y 2 -- "dashboard starting, first draw in a few seconds..."

# Wi-Fi is already associated when launched from KUAL, so draw straight
# away rather than making you stare at a blank screen for 25 seconds.
FIRST_RUN=1
ITER=0

while true; do
    ITER=$((ITER + 1))
    echo "--- iteration $ITER at $(date) ---"

    if [ "$FIRST_RUN" = "1" ]; then
        FIRST_RUN=0
    else
        echo "re-enabling wifi, settling ${WIFI_SETTLE}s"
        lipc-set-prop com.lab126.cmd wirelessEnable 1 2>/dev/null
        sleep "$WIFI_SETTLE"
    fi

    housekeep

    echo "drawing"
    DASH_FORCE_INTERVAL="$REFRESH_SECONDS" python3 "$ROOT/bin/run.py"
    echo "draw exit: $?"

    SLEEP_FOR="$(cat "$ROOT/work/next_wake" 2>/dev/null)"
    case "$SLEEP_FOR" in
        ''|*[!0-9]*) SLEEP_FOR=1200 ;;
    esac
    [ "$SLEEP_FOR" -lt 60 ] && SLEEP_FOR=60

    sleep 5   # let the panel finish its refresh before suspending

    echo "arming wake for ${SLEEP_FOR}s, suspending"
    echo "" > "$RTC"
    echo "+$SLEEP_FOR" > "$RTC"
    echo mem > /sys/power/state
    echo "resumed at $(date)"
done
