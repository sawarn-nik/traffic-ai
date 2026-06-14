"""
metro_timetable.py — Kolkata Metro static timetable (all 5 lines)
==================================================================

Data sources:
  - Metro Railway Kolkata official site / mtp.indianrailways.gov.in
  - Indian Express: Green Line 180 services, 8-min peak (Aug 2025)
  - Financial Express: Purple Line 84 weekday services (Oct 2024)
  - Indian Express: Purple Line extended hours from May 2025
  - ET Infra: Yellow Line 120 weekday services, 7:18am–9:30pm (Nov 2025)
  - Wikipedia: Yellow Line Saturday/Sunday schedule
  - Telegraph India: Blue/Green Sunday start at 9am normally
  - Scribd timetable snippet: Blue Line station-wise first/last trains

Lines covered:
  BLUE   — North-South (Line 1): Dakshineswar ↔ Shahid Khudiram (26 stations;
            Kavi Subhash closed since Jul 28 2025 due to structural damage)
  GREEN  — East-West   (Line 2): Howrah Maidan ↔ Salt Lake Sector V
            (12 stations; Esplanade–Sealdah section opened Aug 22 2025 —
             the 12-station full-line timetable applies)
  PURPLE — Joka-Majerhat (Line 3): Joka ↔ Majerhat (7 stations, 7.75 km)
  ORANGE — Kavi Subhash ↔ Beleghata (Line 6, 9 stations; extended Aug 2025)
  YELLOW — Noapara ↔ Jai Hind Bimanbandar (Line 5, 4 stations; opened 2025)

Timetable model
---------------
We store:
  • first departure from each terminus (Mon-Sat and Sunday separately)
  • last  departure from each terminus (Mon-Sat)
  • service frequency (peak / off-peak / Sunday) in minutes

"Peak"    = Mon-Sat 08:00-11:00 and 17:00-20:00 IST
"Off-peak"= all other Mon-Sat slots
"Sunday"  = Sunday any time

From terminus first-departure + frequency we compute station-level
departure times using cumulative inter-station travel time offsets.

All times are IST (UTC+5:30).  Timetable correct as of June 2026.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import NamedTuple


# ── IST timezone ──────────────────────────────────────────────────────────────
IST = timezone(timedelta(hours=5, minutes=30))


# ── Data structures ───────────────────────────────────────────────────────────

class LineSchedule(NamedTuple):
    line:          str          # "blue" | "green" | "purple" | "orange" | "yellow"
    color_hex:     str
    display_name:  str
    terminus_a:    str          # station name (northern/western terminus)
    terminus_b:    str          # station name (southern/eastern terminus)
    stations:      list[str]    # ordered terminus_a → terminus_b
    # Travel time between consecutive stations (minutes), len = len(stations)-1
    inter_station_mins: list[int]
    # ── Weekday (Mon-Sat) ──
    first_a: tuple[int, int]   # HH, MM — first departure from terminus_a
    first_b: tuple[int, int]   # HH, MM — first departure from terminus_b
    last_a:  tuple[int, int]   # HH, MM — last departure from terminus_a
    last_b:  tuple[int, int]   # HH, MM — last departure from terminus_b
    freq_peak:    int           # minutes between trains during peak
    freq_offpeak: int           # minutes off-peak
    # ── Sunday ──
    first_a_sun: tuple[int, int] = (9, 0)
    first_b_sun: tuple[int, int] = (9, 0)
    last_a_sun:  tuple[int, int] = (21, 30)
    last_b_sun:  tuple[int, int] = (21, 30)
    freq_sunday: int = 15
    # Days of operation
    operating_days: str = "daily"   # "daily" | "mon-sat"


# ── BLUE LINE (North-South, Line 1) ──────────────────────────────────────────
# Sources:
#   • Scribd snippet: Kavi Subhash 06:45, Noapara 07:02 (first), 21:49 last
#   • Shahid Khudiram is current southern terminus (Kavi Subhash closed Jul 2025)
#   • Weekday: 7-min peak, 10-min off-peak  (252 daily services on full line)
#   • Sunday: starts 09:00, 15-min frequency, 152 services
#   • First from Dakshineswar: 06:50  Last: ~22:10
#   • First from Shahid Khudiram: 06:45  Last: ~21:58
#
# Inter-station times tuned to match ~53 min end-to-end (24 gaps → 25 stations,
# but Kavi Subhash closed so effective 25 stations / 24 gaps operational).
# We keep Kavi Subhash in the schedule data for forward-compatibility; at query
# time the caller should note it is temporarily closed.

BLUE_STATIONS = [
    "Dakshineswar",
    "Baranagar Road",
    "Noapara",
    "Dum Dum",
    "Belgachia",
    "Shyambazar",
    "Shobhabazar Sutanuti",
    "Girish Park",
    "Mahatma Gandhi Road",
    "Central",
    "Chandni Chowk",
    "Esplanade",
    "Park Street",
    "Maidan",
    "Rabindra Sadan",
    "Netaji Bhavan",
    "Jatin Das Park",
    "Kalighat",
    "Tollygunge",
    "Mahanayak Uttam Kumar",
    "Netaji",
    "Masterda Surya Sen",
    "Gitanjali",
    "Kavi Nazrul",
    "Shahid Khudiram",         
    # temporarily closed — kept for data completeness
]

# Inter-station times (min) — 24 gaps totalling ~53 min
BLUE_INTER = [6, 3, 5, 3, 2, 2, 2, 2, 2, 2, 1, 2, 1, 2, 2, 2, 2, 2, 3, 4, 3, 2, 2, 4]

BLUE_LINE = LineSchedule(
    line="blue", color_hex="#2196F3",
    display_name="Blue Line (North-South)",
    terminus_a="Dakshineswar", terminus_b="Shahid Khudiram",
    stations=BLUE_STATIONS,
    inter_station_mins=BLUE_INTER,
    # Weekday
    first_a=(6, 55), first_b=(6, 54),
    last_a=(21, 28),  last_b=(21, 33),
    freq_peak=7, freq_offpeak=10,
    # Sunday — starts at 09:00
    first_a_sun=(9, 0),  first_b_sun=(9, 4),
    last_a_sun=(21, 33), last_b_sun=(21, 30),
    freq_sunday=15,
    operating_days="daily",
)


# ── GREEN LINE (East-West, Line 2) ────────────────────────────────────────────
# Sources:
#   • Indian Express (Aug 2025): 180 daily services, 8-min peak, 10-min off-peak
#   • Full route Howrah Maidan ↔ Salt Lake Sector V (12 stations, 16.6 km)
#     including Esplanade–Sealdah gap opened Aug 22 2025
#   • First train: 06:30 from both termini (Mon-Sat)
#   • Last train: ~21:47 from Howrah Maidan, ~21:53 from Salt Lake Sector V
#   • Sunday: starts 09:00, ~15-min frequency, 108 services
#   • No service on Sundays was the old rule; now operates 7 days a week

GREEN_STATIONS = [
    "Howrah Maidan",
    "Howrah",
    "Mahakaran",
    "Esplanade",
    "Sealdah",
    "Phoolbagan",
    "Salt Lake Stadium",
    "Bengal Chemical",
    "City Centre",
    "Central Park",
    "Karunamoyee",
    "Salt Lake Sector V",
]

# Inter-station times (min) — 11 gaps, total ~35 min end-to-end
GREEN_INTER = [2, 3, 2, 3, 3, 3, 3, 4, 2, 3, 4]

GREEN_LINE = LineSchedule(
    line="green", color_hex="#4CAF50",
    display_name="Green Line (East-West)",
    terminus_a="Howrah Maidan", terminus_b="Salt Lake Sector V",
    stations=GREEN_STATIONS,
    inter_station_mins=GREEN_INTER,
    # Weekday
    first_a=(6, 45), first_b=(6, 39),
    last_a=(21, 55),  last_b=(21, 55),
    freq_peak=8, freq_offpeak=10,
    # Sunday
    first_a_sun=(9, 0),  first_b_sun=(9, 2),
    last_a_sun=(21, 55), last_b_sun=(21, 55),
    freq_sunday=15,
    operating_days="daily",
)


# ── PURPLE LINE (Joka-Majerhat, Line 3) ──────────────────────────────────────
# Sources:
#   • Financial Express (Oct 2024): 84 weekday services, first 06:40 Joka,
#     07:03 Majerhat; last 21:05 Joka, 21:26 Majerhat
#   • Indian Express (May 2025): first from Majerhat advanced to 07:57,
#     first from Joka at 08:00; frequency ~12-min Mon-Fri
#   • ET Infra (Aug 2025): 80 trains (40+40) from Aug 11
#   • Financial Express latest (84 services): peak 12 min, off-peak 15 min
#   • Sunday: no regular service (confirmed multiple sources)
#   Note: The Oct 2024 Financial Express data (06:40 first from Joka) is the
#   most comprehensive; May 2025 IE says 08:00 — difference likely reflects
#   further timetable revisions. We use the later/broader 06:40 first train
#   as that gives passengers the most conservative next-train estimate.

PURPLE_STATIONS = [
    "Joka",
    "Thakurpukur",
    "Sakherbazar",
    "Behala Chowrasta",
    "Behala Bazar",
    "Taratala",
    "Majerhat",
]

# Inter-station times (min) — 6 gaps, total ~21 min
PURPLE_INTER = [4, 3, 4, 3, 3, 4]

PURPLE_LINE = LineSchedule(
    line="purple", color_hex="#9908B2",
    display_name="Purple Line (Joka–Majerhat)",
    terminus_a="Joka", terminus_b="Majerhat",
    stations=PURPLE_STATIONS,
    inter_station_mins=PURPLE_INTER,
    # Weekday
    first_a=(6, 40), first_b=(7, 3),
    last_a=(21, 5),  last_b=(21, 26),
    freq_peak=12, freq_offpeak=15,
    # Sunday — no regular service; use sentinel (09:00 / few trains)
    first_a_sun=(13, 25),  first_b_sun=(13, 49),
    last_a_sun=(20, 11), last_b_sun=(20, 32),
    freq_sunday=25,
    operating_days="mon-sat",
)


# ── ORANGE LINE (Kavi Subhash–Beleghata, Line 6) ──────────────────────────────
# Sources:
#   • Original 5 stations (Mar 2024): Kavi Subhash, Satyajit Ray,
#     Jyotirindra Nandi, Kavi Sukanta, Hemanta Mukhopadhyay
#   • Extended to Beleghata (Aug 22 2025) adding 4 more stations:
#     VIP Bazar, Ritwik Ghatak, Barun Sengupta (Science City), Beleghata
#     = 9 stations total
#   • Frequency: 20-min all day (limited service line)
#   • Operating hours: ~08:00 – 20:00 (limited, not 24h)
#   • Sunday: no service confirmed

ORANGE_STATIONS = [
    "Kavi Subhash",           # interchange with Blue Line
    "Satyajit Ray",
    "Jyotirindra Nandi",
    "Kavi Sukanta",
    "Hemanta Mukhopadhyay",
    "VIP Bazar",
    "Ritwik Ghatak",
    "Barun Sengupta",
    "Beleghata",
]

# Inter-station times (min) — 8 gaps, ~40 min total
ORANGE_INTER = [3, 3, 2, 3, 2, 3, 7, 5]

ORANGE_LINE = LineSchedule(
    line="orange", color_hex="#FF9800",
    display_name="Orange Line (Kavi Subhash–Beleghata)",
    terminus_a="Kavi Subhash", terminus_b="Beleghata",
    stations=ORANGE_STATIONS,
    inter_station_mins=ORANGE_INTER,
    # Weekday
    first_a=(7, 40),  first_b=(8, 10),
    last_a=(20, 20), last_b=(20, 45),
    freq_peak=25, freq_offpeak=25,
    # Sunday — no service
    first_a_sun=(9, 0),  first_b_sun=(9, 45),
    last_a_sun=(15, 0),  last_b_sun=(15, 40),
    freq_sunday=30,
    operating_days="mon-sat",
)


# ── YELLOW LINE (Noapara–Jai Hind Bimanbandar, Line 5) ────────────────────────
# Sources:
#   • ET Infra (Nov 2025): 120 weekday services (60+60), 07:18–21:30 from Noapara
#     (last train to Jai Hind ~21:58, last from Jai Hind ~21:18)
#   • Wikipedia Yellow Line article: Saturday 92 trains 07:18–21:30;
#     Sunday 78 trains 09:18–21:30
#   • Frequency: weekday ~9 min, Saturday ~13 min, Sunday ~16 min
#   • 4 operational stations (Noapara to Jai Hind Bimanbandar, 4 stops/3 gaps)

YELLOW_STATIONS = [
    "Noapara",                 # interchange with Blue Line
    "Jessore Road",
    "Nagerbazar",
    "Jai Hind Bimanbandar",   # Kolkata Airport station
]

# Inter-station times (min) — 3 gaps, ~22 min total
YELLOW_INTER = [7, 7, 8]

YELLOW_LINE = LineSchedule(
    line="yellow", color_hex="#FFC107",
    display_name="Yellow Line (Noapara–Jai Hind)",
    terminus_a="Noapara", terminus_b="Jai Hind Bimanbandar",
    stations=YELLOW_STATIONS,
    inter_station_mins=YELLOW_INTER,
    # Weekday (Mon-Fri)
    # 120 daily services, ~9-min peak, ~12-min off-peak (ET Infra Nov 2025)
    first_a=(7, 18), first_b=(7, 40),
    last_a=(20, 58), last_b=(21, 18),
    freq_peak=9, freq_offpeak=12,
    # Saturday (same first/last, more trains)
    # Sunday
    first_a_sun=(9, 18), first_b_sun=(9, 40),
    last_a_sun=(20, 58), last_b_sun=(21, 18),
    freq_sunday=18,
    operating_days="daily",
)


# ── Master registry ───────────────────────────────────────────────────────────
ALL_LINES: list[LineSchedule] = [
    BLUE_LINE, GREEN_LINE, PURPLE_LINE, ORANGE_LINE, YELLOW_LINE,
]

# Station name → list of lines it appears on
_STATION_LINE_MAP: dict[str, list[str]] = {}
for _line in ALL_LINES:
    for _stn in _line.stations:
        _STATION_LINE_MAP.setdefault(_stn.lower(), []).append(_line.line)


# ── Time helpers ──────────────────────────────────────────────────────────────

def _is_sunday(dt: datetime) -> bool:
    return dt.astimezone(IST).weekday() == 6


def _is_saturday(dt: datetime) -> bool:
    return dt.astimezone(IST).weekday() == 5


def _is_peak(dt: datetime) -> bool:
    """
    True if Mon-Sat morning peak (08:00-11:00) or evening peak (17:00-20:00).
    """
    ist = dt.astimezone(IST)
    if ist.weekday() >= 6:  # Sunday
        return False
    h = ist.hour
    return (8 <= h < 11) or (17 <= h < 20)


def _get_frequency(line: LineSchedule, dt: datetime) -> int:
    if _is_sunday(dt):
        return line.freq_sunday
    if _is_peak(dt):
        return line.freq_peak
    return line.freq_offpeak


def _time_to_minutes(h: int, m: int) -> int:
    return h * 60 + m


def _minutes_to_time_str(mins: int) -> str:
    """Convert absolute minutes-since-midnight to 12h AM/PM string."""
    total = int(mins) % (24 * 60)
    h = total // 60
    m = total % 60
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}"


def _compute_station_offset(line: LineSchedule, station_idx: int) -> int:
    """Cumulative travel minutes from terminus_a to station at index."""
    return sum(line.inter_station_mins[:station_idx])


# ── Core departure calculator ─────────────────────────────────────────────────

def get_departures_at_station(
    line: LineSchedule,
    station_name: str,
    direction: str,          # "a_to_b" or "b_to_a"
    now: datetime,
    n: int = 5,
) -> list[dict]:
    """
    Return the next `n` departure times at `station_name` for the given
    direction and current datetime (IST-aware).

    Returns list of dicts:
      {
        departure_time: str,   # e.g. "8:32 AM"
        minutes_away: int,     # minutes from now (0 = now / just departed)
        terminus: str,         # final destination of this train
        line, line_name, color, direction,
      }
    """
    stations = line.stations
    stn_lower = [s.lower() for s in stations]
    try:
        stn_idx = stn_lower.index(station_name.lower())
    except ValueError:
        return []

    is_sun = _is_sunday(now)
    is_sat = _is_saturday(now)

    if direction == "a_to_b":
        if is_sun:
            first_h, first_m = line.first_a_sun
            last_h,  last_m  = line.last_a_sun
        else:
            first_h, first_m = line.first_a
            last_h,  last_m  = line.last_a
        terminus = line.terminus_b
        offset   = _compute_station_offset(line, stn_idx)
    else:  # b_to_a
        if is_sun:
            first_h, first_m = line.first_b_sun
            last_h,  last_m  = line.last_b_sun
        else:
            first_h, first_m = line.first_b
            last_h,  last_m  = line.last_b
        terminus = line.terminus_a
        rev_idx  = len(stations) - 1 - stn_idx
        offset   = _compute_station_offset(line, rev_idx)

    # Arrival time at this station = terminus departure + offset
    first_at_stn = _time_to_minutes(first_h, first_m) + offset
    last_at_stn  = _time_to_minutes(last_h,  last_m)  + offset

    freq = _get_frequency(line, now)

    ist_now  = now.astimezone(IST)
    now_mins = ist_now.hour * 60 + ist_now.minute

    results: list[dict] = []
    t = first_at_stn
    while t <= last_at_stn + 2:   # +2 min tolerance for rounding
        if t >= now_mins:
            results.append({
                "departure_time": _minutes_to_time_str(t),
                "minutes_away":   t - now_mins,
                "terminus":       terminus,
                "line":           line.line,
                "line_name":      line.display_name,
                "color":          line.color_hex,
                "direction":      direction,
            })
            if len(results) >= n:
                break
        t += freq

    return results


# ── Public API ────────────────────────────────────────────────────────────────

def next_trains_at_station(
    station_name: str,
    now: datetime | None = None,
    n: int = 3,
) -> dict:
    """
    Find the next `n` trains at a named station across all lines and both
    directions, sorted by minutes_away.

    Returns:
      {
        station: str,
        queried_at: str,        # IST time string
        trains: [
          { departure_time, minutes_away, terminus,
            line, line_name, color, direction }
        ]
      }
    """
    if now is None:
        now = datetime.now(tz=IST)

    all_trains: list[dict] = []

    for line in ALL_LINES:
        stn_lower = [s.lower() for s in line.stations]
        if station_name.lower() not in stn_lower:
            continue

        # Skip non-operating days
        if line.operating_days == "mon-sat" and _is_sunday(now):
            continue

        for direction in ("a_to_b", "b_to_a"):
            trains = get_departures_at_station(line, station_name, direction, now, n=n)
            all_trains.extend(trains)

    # Sort by minutes_away, deduplicate by (line, direction, minutes_away)
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for t in sorted(all_trains, key=lambda x: x["minutes_away"]):
        key = (t["line"], t["direction"], t["minutes_away"])
        if key not in seen:
            seen.add(key)
            deduped.append(t)

    ist_now    = now.astimezone(IST)
    h12        = ist_now.hour % 12 or 12
    suffix     = "AM" if ist_now.hour < 12 else "PM"
    queried_at = f"{h12}:{ist_now.minute:02d} {suffix} IST"

    return {
        "station":    station_name,
        "queried_at": queried_at,
        "trains":     deduped[:n * 2],  # up to n*2 results across all lines
    }


def next_train_for_journey(
    src_station: str,
    dst_station: str,
    direction: str,
    line_name: str,
    now: datetime | None = None,
) -> dict | None:
    """
    Get the next train at src_station going toward dst_station on the
    specified line (by color name e.g. "blue").

    Returns a single train dict or None if no service.
    """
    if now is None:
        now = datetime.now(tz=IST)

    line = next((l for l in ALL_LINES if l.line == line_name.lower()), None)
    if line is None:
        return None

    if line.operating_days == "mon-sat" and _is_sunday(now):
        return None

    trains = get_departures_at_station(line, src_station, direction, now, n=1)
    return trains[0] if trains else None


def get_all_lines_summary() -> list[dict]:
    """Return a lightweight summary of all lines for the frontend."""
    now = datetime.now(tz=IST)

    def _fmt(h: int, m: int) -> str:
        return _minutes_to_time_str(_time_to_minutes(h, m))

    summaries = []
    for l in ALL_LINES:
        is_sun = _is_sunday(now)
        fa = _fmt(*l.first_a_sun) if is_sun else _fmt(*l.first_a)
        fb = _fmt(*l.first_b_sun) if is_sun else _fmt(*l.first_b)
        la = _fmt(*l.last_a_sun)  if is_sun else _fmt(*l.last_a)
        lb = _fmt(*l.last_b_sun)  if is_sun else _fmt(*l.last_b)
        freq = l.freq_sunday if is_sun else l.freq_offpeak

        summaries.append({
            "line":            l.line,
            "color":           l.color_hex,
            "name":            l.display_name,
            "terminus_a":      l.terminus_a,
            "terminus_b":      l.terminus_b,
            "stations":        l.stations,
            "num_stations":    len(l.stations),
            "first_train_a":   fa,
            "first_train_b":   fb,
            "last_train_a":    la,
            "last_train_b":    lb,
            "freq_peak":       l.freq_peak,
            "freq_offpeak":    l.freq_offpeak,
            "freq_sunday":     l.freq_sunday,
            "operating_days":  l.operating_days,
            "current_freq_min": freq,
            "operates_today":  not (l.operating_days == "mon-sat" and _is_sunday(now)),
        })

    return summaries
