#!/usr/bin/env python3
"""Time, weather and Caltrain departures for a Kindle Basic (600x800).

Runs on the Kindle itself. Called once per wake by bin/start.sh, which
then sleeps for however many seconds this script writes to NEXT_WAKE_FILE.
"""

import calendar
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.request
from xml.sax.saxutils import escape

# ----------------------------------------------------------------- config

LAT, LON = 37.4530, -122.1817           # Menlo Park
UNITS = "fahrenheit"                    # or "celsius"

# Two timezone spellings on purpose. Open-Meteo wants the IANA name. The
# Kindle has no timezone database, so locally we use a POSIX rule string:
# Pacific, UTC-8, daylight time from the 2nd Sunday of March to the 1st
# Sunday of November.
TZ_API = "America/Los_Angeles"
TZ_LOCAL = "PST8PDT,M3.2.0,M11.1.0"

STOP_NB = "70161"                       # Menlo Park, northbound (to SF)
STOP_SB = "70162"                       # Menlo Park, southbound (to San Jose)

# Refresh schedule in seconds. This is where battery life is decided.
PEAK_INTERVAL = 10 * 60                 # weekdays 6-10am and 4-8pm
OFFPEAK_INTERVAL = 20 * 60              # everything else
MIN_INTERVAL = 8 * 60                   # never wake more often than this
NIGHT_START = (1, 30)                   # no trains run between these,
NIGHT_END = (4, 45)                     # so sleep straight through

# ------------------------------------------------------------------ paths

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "svg", "template.svg")
CA_BUNDLE = os.path.join(ROOT, "certs", "cacert.pem")
API_KEY_FILE = os.path.join(ROOT, "api_key.txt")
# Working files live on main storage. The system scratch area (/var/tmp)
# is only a few MB and shared with Kindle system logs.
WORK = os.path.join(ROOT, "work")
OUT_SVG = os.path.join(WORK, "dash.svg")
OUT_PNG = os.path.join(WORK, "dash.png")
NEXT_WAKE_FILE = os.path.join(WORK, "next_wake")
try:
    os.makedirs(WORK)
except OSError:
    pass
RSVG = os.environ.get("RSVG") or "/var/tmp/rsvg-convert"
FBINK = os.environ.get("FBINK") or "fbink"

# Range bar geometry, mirrored from template.svg.
TRACK_X, TRACK_W, MARKER_W = 32, 536, 8

os.environ["TZ"] = TZ_LOCAL
if hasattr(time, "tzset"):      # missing from the Kindle's Python build;
    time.tzset()                # common.sh exports TZ before we start anyway

# ---------------------------------------------------------- weather codes

WMO = {
    0:  ("icon-sun",    "Clear"),
    1:  ("icon-sun",    "Mostly clear"),
    2:  ("icon-partly", "Partly cloudy"),
    3:  ("icon-cloud",  "Overcast"),
    45: ("icon-fog",    "Fog"),
    48: ("icon-fog",    "Freezing fog"),
    51: ("icon-rain",   "Light drizzle"),
    53: ("icon-rain",   "Drizzle"),
    55: ("icon-rain",   "Heavy drizzle"),
    56: ("icon-rain",   "Icy drizzle"),
    57: ("icon-rain",   "Icy drizzle"),
    61: ("icon-rain",   "Light rain"),
    63: ("icon-rain",   "Rain"),
    65: ("icon-rain",   "Heavy rain"),
    66: ("icon-rain",   "Freezing rain"),
    67: ("icon-rain",   "Freezing rain"),
    71: ("icon-snow",   "Light snow"),
    73: ("icon-snow",   "Snow"),
    75: ("icon-snow",   "Heavy snow"),
    77: ("icon-snow",   "Snow grains"),
    80: ("icon-rain",   "Showers"),
    81: ("icon-rain",   "Showers"),
    82: ("icon-rain",   "Heavy showers"),
    85: ("icon-snow",   "Snow showers"),
    86: ("icon-snow",   "Snow showers"),
    95: ("icon-storm",  "Thunderstorms"),
    96: ("icon-storm",  "Thunderstorms"),
    99: ("icon-storm",  "Thunderstorms"),
}


def decode(code):
    try:
        return WMO.get(int(code), ("icon-cloud", "Unknown"))
    except (TypeError, ValueError):
        return ("icon-cloud", "Unknown")


# ---------------------------------------------------------------- helpers

def log(msg):
    # stderr lands in dashboard.log (common.sh redirects it)
    sys.stderr.write("%s\n" % msg)


def ssl_context():
    """The Kindle's own CA store is a decade stale. Prefer our bundle."""
    if os.path.exists(CA_BUNDLE):
        return ssl.create_default_context(cafile=CA_BUNDLE)
    return ssl.create_default_context()


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "kindle-dash/2"})
    with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as r:
        # utf-8-sig strips the byte-order mark 511 puts on its JSON
        return r.read().decode("utf-8-sig")


ISO = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?"
    r"(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(text):
    """ISO 8601 timestamp to epoch seconds. Written by hand because the
    Kindle's Python may predate fromisoformat() handling a trailing Z."""
    if not text:
        return None
    m = ISO.match(str(text).strip())
    if not m:
        return None
    y, mo, d, h, mi, se = (int(x) for x in m.groups()[:6])
    epoch = calendar.timegm((y, mo, d, h, mi, se, 0, 0, 0))
    zone = m.group(7)
    if zone and zone != "Z":
        sign = 1 if zone[0] == "+" else -1
        digits = zone[1:].replace(":", "")
        epoch -= sign * (int(digits[:2]) * 3600 + int(digits[2:]) * 60)
    return epoch


def clock(epoch):
    t = time.localtime(epoch)
    return "%d:%02d" % (t.tm_hour % 12 or 12, t.tm_min)


def ampm(epoch):
    return "AM" if time.localtime(epoch).tm_hour < 12 else "PM"


def battery():
    try:
        out = subprocess.check_output(
            ["lipc-get-prop", "com.lab126.powerd", "battLevel"],
            stderr=subprocess.DEVNULL)
        return "BATTERY %s%%" % out.decode().strip()
    except Exception:
        return ""


def read_api_key():
    try:
        key = open(API_KEY_FILE, "r").read().strip()
    except OSError:
        return None
    if not key or "PASTE" in key.upper():
        return None
    return key


# ---------------------------------------------------------------- weather

def fetch_weather():
    url = (
        "https://api.open-meteo.com/v1/forecast"
        "?latitude=%s&longitude=%s" % (LAT, LON)
        + "&current=temperature_2m,weather_code"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
        "precipitation_probability_max"
        "&temperature_unit=%s&timezone=%s&forecast_days=4" % (UNITS, TZ_API)
    )
    return json.loads(get(url))


# --------------------------------------------------------------- caltrain

def service_name(raw):
    if isinstance(raw, list):
        raw = raw[0] if raw else ""
    if isinstance(raw, dict):
        raw = raw.get("value", "")
    low = str(raw).lower()
    if "express" in low or "bullet" in low:
        return "Express"
    if "limited" in low:
        return "Limited"
    if "south county" in low:
        return "South County"
    if "local" in low:
        return "Local"
    return str(raw)[:12]


def fetch_departures(key, stop):
    """Returns (departures sorted soonest first, server timestamp)."""
    path = ("api.511.org/transit/StopMonitoring?api_key=%s&agency=CT"
            "&stopcode=%s&format=json" % (key, stop))
    try:
        body = get("https://" + path)
    except Exception as exc:
        log("511 https failed (%s), trying http" % exc)
        body = get("http://" + path)

    data = json.loads(body)
    delivery = data.get("ServiceDelivery", {}) or {}
    server_now = parse_iso(delivery.get("ResponseTimestamp"))

    smd = delivery.get("StopMonitoringDelivery", {}) or {}
    if isinstance(smd, list):
        smd = smd[0] if smd else {}
    visits = smd.get("MonitoredStopVisit") or []
    if isinstance(visits, dict):
        visits = [visits]

    out = []
    for visit in visits:
        journey = visit.get("MonitoredVehicleJourney", {}) or {}
        call = journey.get("MonitoredCall", {}) or {}
        aimed = parse_iso(call.get("AimedDepartureTime")
                          or call.get("AimedArrivalTime"))
        live = parse_iso(call.get("ExpectedDepartureTime")
                         or call.get("ExpectedArrivalTime"))
        when = live or aimed
        if when is None:
            continue
        ref = ((journey.get("FramedVehicleJourneyRef") or {})
               .get("DatedVehicleJourneyRef") or "")
        out.append({
            "aimed": aimed,
            "when": when,
            "live": live is not None,
            "service": service_name(journey.get("PublishedLineName")
                                    or journey.get("LineRef") or ""),
            "number": str(ref),
        })
    out.sort(key=lambda d: d["when"])
    return out, server_now


def describe(dep):
    label = dep["service"]
    if dep["number"].isdigit() and len(dep["number"]) <= 4:
        label = ("%s %s" % (label, dep["number"])).strip()
    if not dep["live"]:
        status = "scheduled"
    elif dep["aimed"] is None:
        status = "live"
    else:
        late = int(round((dep["when"] - dep["aimed"]) / 60.0))
        status = "%d min late" % late if late >= 2 else "on time"
    return "%s \u00b7 %s" % (label, status) if label else status


# --------------------------------------------------------------- schedule

def next_wake(now, shown):
    forced = os.environ.get("DASH_FORCE_INTERVAL", "").strip()
    if forced.isdigit():
        return int(forced)

    t = time.localtime(now)
    minutes = t.tm_hour * 60 + t.tm_min
    night_start = NIGHT_START[0] * 60 + NIGHT_START[1]
    night_end = NIGHT_END[0] * 60 + NIGHT_END[1]
    if night_start <= minutes < night_end:
        return (night_end - minutes) * 60 - t.tm_sec

    weekday = t.tm_wday < 5
    peak = weekday and (6 <= t.tm_hour < 10 or 16 <= t.tm_hour < 20)
    interval = PEAK_INTERVAL if peak else OFFPEAK_INTERVAL

    # Wake just after the soonest train on screen leaves, so the display
    # never advertises a train that is already gone.
    upcoming = [d["when"] for d in shown if d["when"] > now]
    if upcoming:
        interval = min(interval, max(MIN_INTERVAL, min(upcoming) - now + 60))
    return int(interval)


# ----------------------------------------------------------------- fields

def marker_x(current, low, high):
    span = high - low
    frac = 0.5 if span <= 0 else (current - low) / span
    frac = max(0.0, min(1.0, frac))
    return round(TRACK_X + frac * (TRACK_W - MARKER_W), 1)


def fill_trains(fields, prefix, deps, error):
    for i in (1, 2):
        key = "%s%d" % (prefix, i)
        fields[key + "_FILL"] = "#666"
        if error:
            fields[key + "_TIME"] = "\u2014" if i == 1 else ""
            fields[key + "_META"] = error if i == 1 else ""
        elif i <= len(deps):
            fields[key + "_TIME"] = clock(deps[i - 1]["when"])
            fields[key + "_META"] = describe(deps[i - 1])
            if "late" in fields[key + "_META"]:
                fields[key + "_FILL"] = "#000"   # the thing worth noticing
        else:
            fields[key + "_TIME"] = "\u2014"
            fields[key + "_META"] = "none listed" if i == 1 else ""


def build_fields(now, weather, weather_error, nb, sb, train_error, batt, wake):
    fields = {
        "TIME": clock(now),
        "AMPM": ampm(now),
        "DAY": time.strftime("%A", time.localtime(now)).upper(),
        "DATE": time.strftime("%b %d", time.localtime(now)).upper(),
        "BATTERY": batt,
        "NEXT": "NEXT UPDATE %s %s" % (clock(now + wake), ampm(now + wake)),
    }

    if weather and not weather_error:
        cur, daily = weather["current"], weather["daily"]
        temp = int(round(cur["temperature_2m"]))
        icon, label = decode(cur["weather_code"])
        hi = int(round(daily["temperature_2m_max"][0]))
        lo = int(round(daily["temperature_2m_min"][0]))
        rain = (daily.get("precipitation_probability_max") or [None])[0]
        temp_text = "%d\u00b0" % temp
        fields.update({
            "ICON": icon,
            "TEMP": temp_text,
            "TEMP_SIZE": "104" if len(str(temp)) < 3 else "84",
            "CONDITION": label,
            "RAIN": "Rain %d%%" % rain if rain is not None else "",
            "MARKER_X": str(marker_x(temp, lo, hi)),
            "LOW": "%d\u00b0" % lo,
            "HIGH": "%d\u00b0" % hi,
        })
        for n in (1, 2, 3):
            d_icon, _ = decode(daily["weather_code"][n])
            y, m, d = (int(x) for x in daily["time"][n].split("-"))
            wday = time.strftime("%a", (y, m, d, 12, 0, 0,
                                        calendar.weekday(y, m, d), 0, -1))
            fields.update({
                "D%d_DAY" % n: wday.upper(),
                "D%d_ICON" % n: d_icon,
                "D%d_HI" % n: "%d\u00b0" % round(daily["temperature_2m_max"][n]),
                "D%d_LO" % n: "%d\u00b0" % round(daily["temperature_2m_min"][n]),
            })
    else:
        fields.update({
            "ICON": "icon-none", "TEMP": "\u2014", "TEMP_SIZE": "104",
            "CONDITION": "Weather unavailable", "RAIN": "",
            "MARKER_X": "-100", "LOW": "", "HIGH": "",
        })
        for n in (1, 2, 3):
            fields.update({"D%d_DAY" % n: "", "D%d_ICON" % n: "icon-none",
                           "D%d_HI" % n: "", "D%d_LO" % n: ""})

    fill_trains(fields, "N", nb, train_error)
    fill_trains(fields, "S", sb, train_error)
    return fields


def fill_template(fields):
    svg = open(TEMPLATE, "r", encoding="utf-8").read()
    for key, value in fields.items():
        safe = (key in ("ICON", "MARKER_X", "TEMP_SIZE")
                or key.endswith("_ICON") or key.endswith("_FILL"))
        svg = svg.replace("{{%s}}" % key, value if safe else escape(value))
    return svg


# ------------------------------------------------------------------- main

def main():
    device_now = time.time()
    now = device_now
    started = device_now

    def stage(name):
        log("  %-8s done at +%.1fs" % (name, time.time() - started))

    log("local time check: %s %s (TZ=%s)" % (
        clock(now), ampm(now), os.environ.get("TZ")))

    # trains first: the 511 response carries the server's clock, which we
    # trust over the Kindle's
    nb, sb, train_error = [], [], None
    key = read_api_key()
    if key is None:
        train_error = "add 511 key to api_key.txt"
    else:
        try:
            nb, server_now = fetch_departures(key, STOP_NB)
            sb, _ = fetch_departures(key, STOP_SB)
            if server_now:
                drift = int(server_now - device_now)
                if abs(drift) > 120:
                    log("device clock off by %ds, using 511 time" % drift)
                now = server_now
        except Exception as exc:
            log("trains: %s" % exc)
            train_error = "train times unavailable"
    stage("trains")

    # drop anything that has already left
    nb = [d for d in nb if d["when"] >= now - 30]
    sb = [d for d in sb if d["when"] >= now - 30]

    weather, weather_error = None, None
    try:
        weather = fetch_weather()
    except Exception as exc:
        log("weather: %s" % exc)
        weather_error = str(exc)
    stage("weather")

    shown = nb[:2] + sb[:2]
    wake = next_wake(now, shown)
    with open(NEXT_WAKE_FILE, "w") as fh:
        fh.write(str(wake))
    log("next wake in %ds" % wake)

    fields = build_fields(now, weather, weather_error, nb, sb,
                          train_error, battery(), wake)

    with open(OUT_SVG, "w", encoding="utf-8") as fh:
        fh.write(fill_template(fields))
    subprocess.run([RSVG, "--background-color=white",
                    "-o", OUT_PNG, OUT_SVG], check=True)
    stage("render")
    subprocess.run([FBINK, "-q", "-c", "-f", "-g",
                    "file=%s,halign=center,valign=center" % OUT_PNG])
    stage("display")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Never leave the loop without a wake time, or start.sh falls back
        # to its default and we lose the schedule.
        try:
            with open(NEXT_WAKE_FILE, "w") as fh:
                fh.write(str(OFFPEAK_INTERVAL))
        except OSError:
            pass
        subprocess.run([FBINK, "-q", "-y", "-2", "--",
                        "dashboard error: %s" % exc])
        log("fatal: %s" % exc)
        sys.exit(1)
