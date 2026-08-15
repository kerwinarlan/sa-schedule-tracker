"""SA Availability Tracker - Streamlit + Plotly heatmap."""
import datetime as dt
import json
import re
import sys
import uuid
from pathlib import Path

import requests
import streamlit as st

BASE_FILE = Path(__file__).parent / "schedule.json"
OVERRIDE_FILE = Path(__file__).parent / "overrides.json"
SA_COLORS = ["#2563EB", "#DC2626", "#16A34A", "#9333EA", "#D97706"]
CN_DOW = ["一", "二", "三", "四", "五", "六", "日"]
GAN = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
ZHI = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]


def year_ganzhi(y):
    """Chinese sexagenary year name, e.g. 2026 -> 丙午年."""
    return GAN[(y - 1984) % 10] + ZHI[(y - 1984) % 12] + "年"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


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


def load_json(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return []


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2))


def supabase_cfg():
    """(url, anon_key) from Streamlit secrets, or None when not configured."""
    try:
        s = st.secrets.get("supabase") or {}
    except Exception:
        return None
    url = (s.get("url") or "").strip().rstrip("/")
    key = (s.get("anon_key") or "").strip()
    if url and key:
        return url, key
    return None


def _sb_headers(cfg):
    return {"apikey": cfg[1], "Authorization": "Bearer " + cfg[1]}


def _sb_load(cfg):
    r = requests.get(
        cfg[0] + "/rest/v1/overrides?select=*", headers=_sb_headers(cfg), timeout=10
    )
    r.raise_for_status()
    return r.json()


def _sb_insert(cfg, row):
    r = requests.post(
        cfg[0] + "/rest/v1/overrides",
        headers={**_sb_headers(cfg), "Prefer": "return=representation"},
        json=row,
        timeout=10,
    )
    r.raise_for_status()
    return r.json()[0]


def _sb_delete(cfg, oid):
    r = requests.delete(
        cfg[0] + f"/rest/v1/overrides?id=eq.{oid}",
        headers={**_sb_headers(cfg), "Prefer": "return=representation"},
        timeout=10,
    )
    r.raise_for_status()


def _sb_fallback(fn, *args):
    try:
        return fn(*args)
    except requests.RequestException as e:
        st.warning(
            f"Supabase unreachable - using local overrides.json. "
            f"{type(e).__name__}: {str(e)[:160]}"
        )
        return None


def load_overrides():
    """Overrides from Supabase when configured, else the local JSON file."""
    cfg = supabase_cfg()
    if cfg:
        got = _sb_fallback(_sb_load, cfg)
        if got is not None:
            return got
    rows = [o for o in load_json(OVERRIDE_FILE) if isinstance(o, dict)]
    if any("id" not in o for o in rows):
        for o in rows:
            o.setdefault("id", uuid.uuid4().hex)
        save_json(OVERRIDE_FILE, rows)
    return rows


def save_override(o):
    """Persist one override; returns the stored row (carries an id)."""
    cfg = supabase_cfg()
    if cfg:
        got = _sb_fallback(_sb_insert, cfg, o)
        if got is not None:
            return got
    o["id"] = uuid.uuid4().hex
    rows = load_overrides()
    rows.append(o)
    save_json(OVERRIDE_FILE, rows)
    return o


def delete_override(oid):
    cfg = supabase_cfg()
    if cfg:
        got = _sb_fallback(_sb_delete, cfg, oid)
        if got is not None:
            return
    rows = load_overrides()
    save_json(OVERRIDE_FILE, [o for o in rows if o.get("id") != oid])


def week_of(date):
    return date - dt.timedelta(days=date.weekday())


def day_stats(parsed, overrides, day, slots):
    """Per-slot (free_count, busy_names) for one day."""
    members = sorted(parsed)
    iso, dayname = day.isoformat(), day.strftime("%A")
    stats = []
    for a, b in slots:
        events = [
            (o["person"], o["event"])
            for o in overrides
            if o["date"] == iso and overlaps((o["start"], o["end"]), (a, b))
        ]
        busy = [
            p
            for p in members
            if any(overlaps(iv, (a, b)) for iv in parsed[p].get(dayname, []))
            or any(p == ep for ep, _ in events)
        ]
        stats.append((len(members) - len(busy), busy))
    return stats


def shift_month(date, n):
    """Move `date` by n months, clamping the day to the target month."""
    y = date.year + (date.month - 1 + n) // 12
    m = (date.month - 1 + n) % 12 + 1
    last = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return dt.date(y, m, min(date.day, last))


PIN_POS = [(50, 18), (18, 48), (82, 48), (28, 80), (72, 80)]


def calendar_month(parsed, overrides, date, slots, tint=False):
    """HTML month grid: pins punched around a big centered date number.

    tint=True colors each cell by the fewest free SAs that day (heatmap view).
    """
    members = sorted(parsed)
    idx = {p: i for i, p in enumerate(members)}
    color = {p: SA_COLORS[i % len(SA_COLORS)] for i, p in enumerate(members)}
    n = len(members)
    first = date.replace(day=1)
    ndays = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][date.month - 1]
    cells = ['<div class="day blank"></div>'] * first.weekday()
    for daynum in range(1, ndays + 1):
        day = date.replace(day=daynum)
        stats = day_stats(parsed, overrides, day, slots)
        min_count = min(s[0] for s in stats)
        busy = sorted({p for _, bs in stats for p in bs})
        lines = [f"Busy: {', '.join(busy)}"] if busy else ["Everyone free"]
        for (a, b), (cnt, bsy) in zip(slots, stats):
            if cnt == 0:
                lines.append(f"{fmt_min(a)} to {fmt_min(b)}: no one free")
            elif cnt == 1:
                avail = [p for p in members if p not in set(bsy)]
                lines.append(f"{fmt_min(a)} to {fmt_min(b)}: only {avail[0]} free")
        events = sorted({
            (o["person"], o["event"])
            for o in overrides
            if o["date"] == day.isoformat()
            and any(overlaps((o["start"], o["end"]), s) for s in slots)
        })
        lines += [f"Event: {e} ({p})" for p, e in events]
        title = "\n".join(lines[:10]).replace('"', "&#34;")
        bg = ""
        if tint:
            r, g, b = cell_rgb(min_count, n)
            bg = f"background:rgba({r},{g},{b},0.45);"
        pins = "".join(
            f'<span class="spin" style="left:{PIN_POS[idx[p] % len(PIN_POS)][0]}%;'
            f'top:{PIN_POS[idx[p] % len(PIN_POS)][1]}%;background:{color[p]}"'
            f' title="{p}"></span>'
            for p in busy
        )
        dots = "".join(
            f'<span class="epin" style="left:{12 + j * 9}%;top:16%" '
            f'title="Event: {e} ({p})"></span>'
            for j, (p, e) in enumerate(events)
        )
        cn = CN_DOW[day.weekday()]
        sun = " sun" if day.weekday() == 6 else ""
        cells.append(
            f'<div class="day{sun}" style="{bg}" title="{title}">'
            f'<span class="cn">{cn}</span>'
            f'<span class="num">{daynum}</span>{pins}{dots}</div>'
        )
    dow = "".join(
        f"<div class='dow{' sun' if d == 'Sun' else ''}'>{d}</div>"
        for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    )
    legend = "".join(
        f'<span class="leg"><span class="ldot" style="background:{color[p]}"></span>{p}</span>'
        for p in members
    )
    return (
        f'<div class="calwrap"><div class="calhead">{dow}</div>'
        f'<div class="cal">{"".join(cells)}</div>'
        f'<div class="legend">{legend}</div></div>'
    )


def main():
    st.set_page_config(page_title="SA Availability", page_icon="📅", layout="wide")
    st.markdown(
        "<style>"
        "section[data-testid='stSidebar'] .block-container {padding-top: 1rem;}"
        "section[data-testid='stSidebar'] div[data-testid='stVerticalBlock'] {gap: .35rem;}"
        ".calwrap {max-width: 900px;}"
        ".calhead {display:grid; grid-template-columns:repeat(7,1fr);}"
        ".cal {display:grid; grid-template-columns:repeat(7,1fr); gap:1px;"
        " background:#d9d3c7; border:1px solid #d9d3c7;}"
        ".dow {text-align:center; font-size:14px; color:#7a746a; font-weight:600;"
        " padding:8px 0;}"
        ".dow.sun {color:#c0392b;}"
        ".day {background:#fffdf8; aspect-ratio:1; min-height:88px; position:relative;}"
        ".day.blank {background:transparent;}"
        ".day .cn {position:absolute; top:4px; right:7px; font-size:12px; color:#c3bbaa;}"
        ".day.sun .cn {color:#c0392b;}"
        ".day .num {position:absolute; left:50%; top:44%; transform:translate(-50%,-50%);"
        " font-size:24px; font-weight:600; color:#3a3a3a;}"
        ".day.sun .num {color:#c0392b;}"
        ".day .spin {position:absolute; width:14px; height:14px; border-radius:50%;"
        " border:2px solid #fff; box-shadow:0 1px 3px rgba(0,0,0,.35);"
        " transform:translate(-50%,-50%);}"
        ".day .epin {position:absolute; width:8px; height:8px; border-radius:50%;"
        " background:#F18A1C; transform:translate(-50%,-50%); box-shadow:0 0 0 1px #fff;}"
        ".legend {margin-top:12px; display:flex; gap:18px; flex-wrap:wrap;"
        " font-size:14px; color:#1a1a1a; align-items:center;}"
        ".leg {display:inline-flex; align-items:center; gap:6px; font-weight:600;}"
        ".ldot {display:inline-block; width:11px; height:11px; border-radius:50%;"
        " border:1px solid rgba(0,0,0,.15);}"
        "</style>",
        unsafe_allow_html=True,
    )
    data = load_json(BASE_FILE)
    overrides = load_overrides()
    parsed = parse_data(data)
    slots = unified_slots(data)
    members = sorted(data)
    slot_labels = [f"{fmt_min(a)} to {fmt_min(b)}" for a, b in slots]
    slot_by_label = dict(zip(slot_labels, slots))

    st.title("SA Schedule Tracker")
    st.caption("Monthly SA availability: pins mark busy SAs, the Heatmap view tints days by coverage.")

    with st.sidebar:
        st.subheader("Week")
        date = st.date_input("Pick any date in the week", value=dt.date.today())
        monday = week_of(date)
        st.caption(f"Showing **{monday.strftime('%b %d, %Y')}**")

        with st.expander("Add override", expanded=False):
            with st.form("override_form"):
                person = st.selectbox("SA", members)
                o_date = st.date_input("Event date")
                o_slot = st.selectbox("Time slot", slot_labels)
                event = st.text_input("Event name", placeholder="e.g. CE 152 Exam")
                if st.form_submit_button("Add override"):
                    if event.strip():
                        start, end = slot_by_label[o_slot]
                        overrides.append(
                            save_override(
                                {
                                    "person": person,
                                    "date": o_date.isoformat(),
                                    "start": start,
                                    "end": end,
                                    "event": event.strip(),
                                }
                            )
                        )
                        st.rerun()

        st.subheader("Overrides this week")
        week_o = [
            o
            for o in overrides
            if monday <= dt.date.fromisoformat(o["date"]) < monday + dt.timedelta(days=7)
        ]
        if not week_o:
            st.caption("None")
        for o in week_o:
            c1, c2 = st.columns([3, 1])
            c1.write(
                f"{o['person']} · {o['date']} "
                f"{fmt_min(o['start'])} to {fmt_min(o['end'])} · {o['event']}"
            )
            if c2.button("✕", key=f"del_{o['id']}", help="Remove"):
                delete_override(o["id"])
                st.rerun()

    view = st.radio("View", ["Calendar", "Heatmap"], horizontal=True)
    cal = st.session_state.get("cal_date", dt.date.today())
    c1, c2, c3 = st.columns([1, 1, 3])
    if c1.button("◀ Prev month"):
        st.session_state.cal_date = shift_month(cal, -1)
        st.rerun()
    if c2.button("Next month ▶"):
        st.session_state.cal_date = shift_month(cal, 1)
        st.rerun()
    c3.subheader(f"{cal.strftime('%B %Y')} · {year_ganzhi(cal.year)}")
    if view == "Calendar":
        st.markdown(calendar_month(parsed, overrides, cal, slots), unsafe_allow_html=True)
        st.caption(
            "Pins = SAs busy that day (no pins = everyone free). "
            "Orange dot = event override. Hover a date for details."
        )
    else:
        st.markdown(
            calendar_month(parsed, overrides, cal, slots, tint=True),
            unsafe_allow_html=True,
        )
        st.caption(
            "Cell color = fewest free SAs that day (red = gap, green = all free). "
            "Pins = busy SAs. Hover a date for details."
        )


def run_selfcheck():
    assert parse_slot("10:00AM to 11:00AM") == (600, 660)
    assert parse_slot("01:00PM to 02:30PM") == (780, 870)
    assert fmt_min(600) == "10:00AM"
    assert fmt_min(780) == "01:00PM"

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
        {"person": "sam", "date": "2024-10-14", "start": 600, "end": 660, "event": "CE 152 Exam"}
    ]
    stats = day_stats(parsed, overrides, monday, slots)
    assert stats[0][0] == 0 and stats[0][1] == ["jade", "sam"], stats[0]
    assert stats[1][0] == 1 and stats[1][1] == ["jade"], stats[1]
    assert stats[2][0] == 2 and stats[2][1] == [], stats[2]
    assert stats[3][0] == 1 and stats[3][1] == ["sam"], stats[3]
    assert cell_rgb(0, 5)[2] < 100 and cell_rgb(5, 5) == (1, 68, 33), "scale endpoints"
    assert shift_month(dt.date(2024, 1, 31), 1) == dt.date(2024, 2, 29)
    cal = calendar_month(parsed, overrides, dt.date(2024, 10, 1), slots)
    assert cal.count('<span class="num">') == 31, "Oct 2024: 31 day cells"
    assert cal.count('class="cn"') == 31, "Chinese weekday char per cell"
    assert cal.count('class="spin"') == 8, "4 Mondays x 2 busy SAs"
    assert cal.count('class="ldot"') == 2, "legend dots for jade + sam"
    assert "background:#2563EB" in cal, "jade pin color"
    assert "CE 152 Exam" in cal and '<div class="legend">' in cal, "event dot + legend"
    cal_tint = calendar_month(parsed, overrides, dt.date(2024, 10, 1), slots, tint=True)
    assert "rgba(179,48,48," in cal_tint, "gap day -> red tint"
    assert "rgba(1,68,33," in cal_tint, "all-free day -> green tint"
    print("selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        run_selfcheck()
    else:
        main()
