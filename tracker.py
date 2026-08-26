"""SA Schedule Tracker - domain logic (pure Python, no UI).

Parsing, unified time axis, and availability computation.
build_site.py uses these functions to generate the static site;
the JS client only overlays live override rows from Supabase.
"""
import datetime as dt
import re
from zoneinfo import ZoneInfo

SA_COLORS = ["#2563EB", "#DC2626", "#16A34A", "#9333EA", "#D97706"]
CN_DOW = ["一", "二", "三", "四", "五", "六", "日"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MANILA = ZoneInfo("Asia/Manila")
PIN_POS = [(50, 18), (18, 48), (82, 48), (28, 80), (72, 80)]


def ph_today():
    """Today's date in Philippine Standard Time (UTC+8)."""
    return dt.datetime.now(MANILA).date()


def parse_slot(text):
    """'10:00AM to 11:30AM' -> (start, end) minutes since midnight."""
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(AM|PM) to (\d{1,2}):(\d{2})(AM|PM)", text)
    if not m:
        raise ValueError(f"bad time slot: {text!r}")

    def to_min(h, mm, ap):
        h = int(h) % 12
        if ap == "PM":
            h += 12
        return h * 60 + int(mm)

    h1, m1, ap1, h2, m2, ap2 = m.groups()
    return to_min(h1, m1, ap1), to_min(h2, m2, ap2)


def fmt_min(mins):
    h, mm = divmod(mins, 60)
    return f"{h % 12 or 12:02d}:{mm:02d}{'AM' if h < 12 else 'PM'}"


def unified_slots(data):
    """One shared time axis from the union of every SA's slot boundaries."""
    bounds = sorted(
        {t for days in data.values() for slots in days.values()
         for s in slots for t in parse_slot(s)}
    )
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]


def parse_data(data):
    return {
        sa: {d: [parse_slot(s) for s in data[sa].get(d, [])] for d in DAYS}
        for sa in data
    }


def overlaps(a, b):
    """Half-open [start, end) interval overlap."""
    return a[0] < b[1] and b[0] < a[1]


_COLOR_STOPS = [(0.0, (179, 48, 48)), (0.5, (244, 197, 66)), (1.0, (1, 68, 33))]


def cell_rgb(value, n):
    """Interpolated cell color for `value` of `n` available, matching the scale."""
    pos = value / max(1, n)
    for (p1, c1), (p2, c2) in zip(_COLOR_STOPS, _COLOR_STOPS[1:]):
        if p1 <= pos <= p2:
            t = (pos - p1) / (p2 - p1)
            return tuple(round(a + (b - a) * t) for a, b in zip(c1, c2))
    return _COLOR_STOPS[-1][1]


def day_stats(parsed, overrides, day, slots):
    """Per-slot (free_count, busy_names) for one day."""
    members = sorted(parsed)
    iso, dayname = day.isoformat(), day.strftime("%A")
    stats = []
    for a, b in slots:
        events = [
            (o["person"], o["event"])
            for o in overrides
            if str(o["date"])[:10] == iso
            and overlaps((int(o["start"]), int(o["end"])), (a, b))
        ]
        busy = [
            p
            for p in members
            if any(overlaps(iv, (a, b)) for iv in parsed[p].get(dayname, []))
            or any(p.lower() == str(ep).strip().lower() for ep, _ in events)
        ]
        stats.append((len(members) - len(busy), busy))
    return stats


def shift_month(date, n):
    """Move `date` by n months, clamping the day to the target month."""
    y = date.year + (date.month - 1 + n) // 12
    m = (date.month - 1 + n) % 12 + 1
    last = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return dt.date(y, m, min(date.day, last))


def run_selfcheck():
    assert parse_slot("10:00AM to 11:00AM") == (600, 660)
    assert parse_slot("01:00PM to 02:30PM") == (780, 870)
    assert fmt_min(600) == "10:00AM"
    assert fmt_min(780) == "01:00PM"
    utc_day = dt.datetime.now(dt.timezone.utc).date()
    assert ph_today() - utc_day in (dt.timedelta(0), dt.timedelta(days=1)), "PH = UTC+8"

    data = {
        "sam": {
            "Monday": ["10:00AM to 11:00AM", "01:00PM to 02:30PM"],
            "Tuesday": [], "Wednesday": [], "Thursday": [],
            "Friday": [], "Saturday": [], "Sunday": [],
        },
        "jade": {
            "Monday": ["10:00AM to 11:30AM"],
            "Tuesday": [], "Wednesday": [], "Thursday": [],
            "Friday": [], "Saturday": [], "Sunday": [],
        },
    }
    slots = unified_slots(data)
    assert slots == [(600, 660), (660, 690), (690, 780), (780, 870)], slots
    parsed = parse_data(data)
    monday = dt.date(2024, 10, 14)  # a Monday
    overrides = [
        {"person": "Sam ", "date": "2024-10-14T00:00:00", "start": "600", "end": "660", "event": "CE 152 Exam"}
    ]
    stats = day_stats(parsed, overrides, monday, slots)
    assert stats[0][0] == 0 and stats[0][1] == ["jade", "sam"], stats[0]
    assert stats[1][0] == 1 and stats[1][1] == ["jade"], stats[1]
    assert stats[2][0] == 2 and stats[2][1] == [], stats[2]
    assert stats[3][0] == 1 and stats[3][1] == ["sam"], stats[3]
    assert cell_rgb(0, 5)[2] < 100 and cell_rgb(5, 5) == (1, 68, 33), "scale endpoints"
    assert shift_month(dt.date(2024, 1, 31), 1) == dt.date(2024, 2, 29)
    print("selfcheck OK")


if __name__ == "__main__":
    run_selfcheck()
