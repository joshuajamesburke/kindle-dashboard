#!/bin/sh
# Shared setup. Sourced by start.sh, refresh.sh and stop.sh.
# Locates binaries, sets the environment, and sends everything to a log.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$ROOT/dashboard.log"

# POSIX rule string, not "America/Los_Angeles": the Kindle has no zoneinfo
# database and silently falls back to UTC for named zones.
export TZ="PST8PDT,M3.2.0,M11.1.0"

# Everything from here on lands in the log, so failures are diagnosable.
exec >> "$LOG" 2>&1
echo "--- $(date) : $(basename "$0") ---"


# --- stage bundled binaries somewhere executable ----------------------
# /mnt/us is noexec, /var/tmp is not.
if [ ! -x /var/tmp/rsvg-convert ] && [ ! -x /var/tmp/rsvg-convert-lib/rsvg-convert ]; then
    echo "staging binaries from $ROOT/external"
    cp -rf "$ROOT"/external/* /var/tmp/ 2>/dev/null
    chmod +x /var/tmp/rsvg-convert /var/tmp/fbink 2>/dev/null
    chmod +x /var/tmp/rsvg-convert-lib/rsvg-convert 2>/dev/null
fi

# --- locate rsvg-convert ----------------------------------------------
# Some bundles put the binary inside rsvg-convert-lib/, others alongside.
RSVG=""
for candidate in /var/tmp/rsvg-convert /var/tmp/rsvg-convert-lib/rsvg-convert; do
    if [ -x "$candidate" ]; then RSVG="$candidate"; break; fi
done
if [ -z "$RSVG" ]; then
    echo "ERROR: rsvg-convert not found."
    echo "  Looked in /var/tmp/rsvg-convert and /var/tmp/rsvg-convert-lib/"
    echo "  Contents of $ROOT/external:"
    ls -la "$ROOT/external"
    exit 1
fi
echo "rsvg: $RSVG"
export RSVG

# --- locate fbink -------------------------------------------------------
# Bundled with NiLuJe's Python package and with the KindleModding hotfix.
FBINK=""
for candidate in /var/tmp/fbink \
                 /usr/bin/fbink \
                 /usr/local/bin/fbink \
                 /mnt/us/python3/bin/fbink \
                 /mnt/us/extensions/hotfix/bin/fbink; do
    if [ -x "$candidate" ]; then FBINK="$candidate"; break; fi
done
[ -z "$FBINK" ] && command -v fbink >/dev/null 2>&1 && FBINK="$(command -v fbink)"

if [ -z "$FBINK" ]; then
    echo "ERROR: fbink not found. It ships inside NiLuJe's Python package;"
    echo "  reinstall that, or drop the binary into $ROOT/external"
    exit 1
fi
echo "fbink: $FBINK"
export FBINK

# --- check python -------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not on PATH. Install NiLuJe's Python 3 package via MRPI."
    exit 1
fi
echo "python: $(command -v python3)"

export LD_LIBRARY_PATH=/var/tmp/rsvg-convert-lib:/usr/lib:/lib
export FONTCONFIG_FILE="$ROOT/fonts/fonts.conf"

# --- housekeeping -------------------------------------------------------
# Runs on every wake. With the reading software stopped, nothing trims the
# Kindle's own logs, and each suspend/resume adds to them. The scratch area
# they share with us is only a few MB, so it fills within about a day.
housekeep() {
    # Kindle system logs: empty anything over 200 KB, drop rotated copies
    for f in /var/log/*; do
        [ -f "$f" ] || continue
        case "$f" in
            *.gz|*.[0-9]|*.old) rm -f "$f" ;;
            *) [ "$(wc -c < "$f")" -gt 204800 ] && : > "$f" ;;
        esac
    done 2>/dev/null

    # leftovers from older versions of this dashboard
    rm -f /var/tmp/dash.svg /var/tmp/dash.png /var/tmp/dash_next 2>/dev/null

    # our own log: keep the last ~2000 lines once it passes 1 MB
    if [ "$(wc -c < "$LOG")" -gt 1048576 ]; then
        tail -n 2000 "$LOG" > "$LOG.tmp" && cat "$LOG.tmp" > "$LOG"
        rm -f "$LOG.tmp"
        echo "(log trimmed)"
    fi

    # one line of free space per wake, so a slow fill shows up early
    echo "free: $(df -k /var/tmp /var/log /mnt/us 2>/dev/null \
        | awk 'NR>1 {printf "%s=%dK ", $6, $4}')"
}

