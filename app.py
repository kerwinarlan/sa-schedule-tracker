"""SA Availability Tracker - Streamlit + Plotly heatmap."""
import datetime as dt
import json
import re
import sys
import uuid
from pathlib import Path

import plotly.graph_objects as go
import requests
import streamlit as st

BASE_FILE = Path(__file__).parent / "schedule.json"
OVERRIDE_FILE = Path(__file__).parent / "overrides.json"
OFF_WHITE, FOREST, ORANGE = "#F4F6F5", "#014421", "#F18A1C"
SA_COLORS = ["#2563EB", "#DC2626", "#16A34A", "#9333EA", "#D97706"]
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


def text_color(value, is_override, n):
    """Readable label color for a cell: white on dark fills, dark otherwise."""
    if is_override:
        return "#1a1a1a"  # dark on orange
    r, g, b = cell_rgb(value, n)
    return "white" if 0.299 * r + 0.587 * g + 0.114 * b < 140 else "#1a1a1a"


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
    if s.get("url") and s.get("anon_key"):
        return s["url"].rstrip("/"), s["anon_key"]
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


def load_overrides():
    """Overrides from Supabase when configured, else the local JSON file."""
    cfg = supabase_cfg()
    if cfg:
        return _sb_load(cfg)
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
        return _sb_insert(cfg, o)
    o["id"] = uuid.uuid4().hex
    rows = load_overrides()
    rows.append(o)
    save_json(OVERRIDE_FILE, rows)
    return o


def delete_override(oid):
    cfg = supabase_cfg()
    if cfg:
        return _sb_delete(cfg, oid)
    rows = load_overrides()
    save_json(OVERRIDE_FILE, [o for o in rows if o.get("id") != oid])


def week_of(date):
    return date - dt.timedelta(days=date.weekday())


def day_stats(parsed, overrides, day, slots):
    """Per-slot (count, hover, has_override) for one day."""
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
        avail = [p for p in members if p not in busy]
        if not avail:
            hover = "No one available and Busy: " + ", ".join(busy)
        elif len(avail) == len(members):
            hover = "All available"
        else:
            hover = "Available: " + ", ".join(avail) + " and Busy: " + ", ".join(busy)
        hover += "".join(f"<br>Event: {e} ({p})" for p, e in events)
        stats.append((len(avail), hover, 1 if events else 0, busy))
    return stats


def build_week(parsed, overrides, monday, slots):
    """Availability counts, hover text, and override mask for one week.

    Returns (counts, hovers, mask): each is slots x days, in heatmap
    orientation (outer list = slot rows, inner list = day columns).
    """
    days = [monday + dt.timedelta(days=i) for i in range(7)]
    per_day = [day_stats(parsed, overrides, day, slots) for day in days]
    counts = [[s[0] for s in d] for d in per_day]
    hovers = [[s[1] for s in d] for d in per_day]
    mask = [[float("nan") if s[2] == 0 else 1 for s in d] for d in per_day]
    return (
        [list(r) for r in zip(*counts)],
        [list(r) for r in zip(*hovers)],
        [list(r) for r in zip(*mask)],
    )


def shift_month(date, n):
    """Move `date` by n months, clamping the day to the target month."""
    y = date.year + (date.month - 1 + n) // 12
    m = (date.month - 1 + n) % 12 + 1
    last = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return dt.date(y, m, min(date.day, last))


def calendar_month(parsed, overrides, date, slots):
    """HTML month grid: one colored pin per SA busy that day, orange dots for events."""
    members = sorted(parsed)
    color = {p: SA_COLORS[i % len(SA_COLORS)] for i, p in enumerate(members)}
    n = len(members)
    first = date.replace(day=1)
    ndays = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][date.month - 1]
    cells = ['<div class="day blank"></div>'] * first.weekday()
    for daynum in range(1, ndays + 1):
        day = date.replace(day=daynum)
        stats = day_stats(parsed, overrides, day, slots)
        min_count = min(s[0] for s in stats)
        lines = [
            s[1].replace("<br>", " · ") for s in stats
            if s[0] <= 1 or (s[0] == min_count and min_count < n)
        ]
        if not lines:
            lines = ["All available all day"]
        busy = sorted({p for _, _, _, bs in stats for p in bs})
        pins = "".join(
            f'<span class="spin" style="background:{color[p]}" title="{p}"></span>'
            for p in busy
        )
        events = sorted({
            (o["person"], o["event"])
            for o in overrides
            if o["date"] == day.isoformat()
            and any(overlaps((o["start"], o["end"]), s) for s in slots)
        })
        dots = "".join(
            f'<span class="epin" title="Event: {e} ({p})"></span>' for p, e in events
        )
        title = "\n".join(lines[:6]).replace('"', "&#34;")
        cells.append(
            f'<div class="day" title="{title}">'
            f'<span class="num">{daynum}</span>{pins}{dots}</div>'
        )
    dow = "".join(
        f"<div class='dow'>{d}</div>" for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    )
    legend = "".join(
        f'<span class="leg"><span class="spin" style="background:{color[p]}"></span>{p}</span>'
        for p in members
    )
    return (
        f'<div class="calwrap"><div class="calhead">{dow}</div>'
        f'<div class="cal">{"".join(cells)}</div>'
        f'<div class="legend">{legend}</div></div>'
    )


def make_figure(members, counts, hovers, mask, monday, slots):
    days = [monday + dt.timedelta(days=i) for i in range(7)]
    x = [d.strftime("%a %b %d") for d in days]
    y = [f"{fmt_min(a)} to {fmt_min(b)}" for a, b in slots]
    n = len(members)
    fig = go.Figure()
    fig.add_trace(
        go.Heatmap(
            z=counts,
            zmin=0,
            zmax=max(1, n),
            colorscale=[[0, "#B33030"], [0.5, "#F4C542"], [1, FOREST]],
            x=x,
            y=y,
            customdata=hovers,
            hovertemplate="%{customdata}<extra></extra>",
            colorbar={"title": "Available SAs"},
        )
    )
    if any(v == 1 for row in mask for v in row):
        fig.add_trace(
            go.Heatmap(
                z=mask,
                zmin=0,
                zmax=1,
                colorscale=[[0, "rgba(0,0,0,0)"], [1, ORANGE]],
                x=x,
                y=y,
                showscale=False,
                hoverinfo="skip",
            )
        )
    xs, ys, texts, colors = [], [], [], []
    for i in range(len(slots)):
        for j in range(7):
            xs.append(x[j])
            ys.append(y[i])
            texts.append(str(counts[i][j]))
            colors.append(text_color(counts[i][j], mask[i][j] == 1, n))
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="text",
            text=texts,
            textfont=dict(color=colors, size=13),
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.update_layout(
        title=f"Week of {monday.strftime('%b %d, %Y')}",
        height=650,
        plot_bgcolor=OFF_WHITE,
        paper_bgcolor="white",
        margin=dict(l=10, r=10, t=50, b=10),
        font=dict(size=14, color="#1a1a1a"),  # explicit dark font: readable in dark mode
        xaxis=dict(tickfont=dict(size=13, color="#1a1a1a")),
        yaxis=dict(tickfont=dict(size=14, color="#1a1a1a"), autorange="reversed"),
    )
    return fig


def main():
    st.set_page_config(page_title="SA Availability", page_icon="📅", layout="wide")
    st.markdown(
        "<style>"
        "section[data-testid='stSidebar'] .block-container {padding-top: 1rem;}"
        "section[data-testid='stSidebar'] div[data-testid='stVerticalBlock'] {gap: .35rem;}"
        ".calhead {display:grid; grid-template-columns:repeat(7,1fr); gap:6px;}"
        ".cal {display:grid; grid-template-columns:repeat(7,1fr); gap:6px;}"
        ".dow {text-align:center; font-size:12px; color:#6b7280; font-weight:600;}"
        ".day {background:#F4F6F5; border:1px solid #e2e8e6; border-radius:8px;"
        " padding:6px 8px; min-height:58px; position:relative; font-size:13px;}"
        ".day.blank {background:transparent; border:none;}"
        ".day .num {color:#4b5563; font-size:12px;}"
        ".day .spin {display:inline-block; width:11px; height:11px; border-radius:50%;"
        " border:1.5px solid #fff; box-shadow:0 0 0 1px #cbd5d1; margin:1px 2px 0 0;}"
        ".day .epin {display:inline-block; width:8px; height:8px; border-radius:50%;"
        " background:#F18A1C; margin:2px 3px 0 0;}"
        ".legend {margin-top:10px; display:flex; gap:16px; flex-wrap:wrap;"
        " font-size:13px; color:#4b5563;}"
        ".leg {display:inline-flex; align-items:center; gap:5px;}"
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
    st.caption("Red = no one free, green = all free. Numbers = free SAs. Orange = exam/event override.")

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
    if view == "Calendar":
        cal = st.session_state.get("cal_date", dt.date.today())
        c1, c2, c3 = st.columns([1, 1, 3])
        if c1.button("◀ Prev month"):
            st.session_state.cal_date = shift_month(cal, -1)
            st.rerun()
        if c2.button("Next month ▶"):
            st.session_state.cal_date = shift_month(cal, 1)
            st.rerun()
        c3.subheader(cal.strftime("%B %Y"))
        st.markdown(calendar_month(parsed, overrides, cal, slots), unsafe_allow_html=True)
        st.caption(
            "Pins = SAs busy that day (no pins = everyone free). "
            "Orange dot = event override. Hover a date for details."
        )
    else:
        counts, hovers, mask = build_week(parsed, overrides, monday, slots)
        st.plotly_chart(
            make_figure(members, counts, hovers, mask, monday, slots),
            use_container_width=True,
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
    counts, hovers, mask = build_week(parsed, overrides, monday, slots)
    assert counts[0][0] == 0, f"10-11am Mon: nobody free, got {counts[0][0]}"
    assert mask[0][0] == 1, "override cell should be orange"
    assert "Event: CE 152 Exam (sam)" in hovers[0][0], hovers[0][0]
    assert hovers[0][0].startswith("No one available and Busy: jade, sam"), hovers[0][0]
    assert counts[1][0] == 1, f"11-11:30am Mon: 1 free, got {counts[1][0]}"
    assert hovers[1][0] == "Available: sam and Busy: jade", hovers[1][0]
    assert counts[2][0] == 2, f"11:30-1pm Mon: 2 free, got {counts[2][0]}"
    assert hovers[2][0] == "All available", hovers[2][0]
    assert counts[3][0] == 1, f"1-2:30pm Mon: 1 free, got {counts[3][0]}"
    assert hovers[3][0] == "Available: jade and Busy: sam", hovers[3][0]
    assert cell_rgb(0, 5)[2] < 100 and cell_rgb(5, 5) == (1, 68, 33), "scale endpoints"
    assert text_color(0, False, 5) == "white" and text_color(3, False, 5) == "#1a1a1a"
    stats = day_stats(parsed, overrides, dt.date(2024, 10, 14), slots)
    assert stats[0][0] == 0 and stats[0][1] == hovers[0][0] and stats[0][2] == 1
    assert stats[2][0] == 2 and stats[2][1].startswith("All available")
    assert shift_month(dt.date(2024, 1, 31), 1) == dt.date(2024, 2, 29)
    cal = calendar_month(parsed, overrides, dt.date(2024, 10, 1), slots)
    assert "<div class='dow'>" in cal and cal.count('class="day" title=') == 31, "Oct 2024 grid"
    assert cal.count('class="spin"') == 10, "4 Mondays x 2 busy SAs + 2 legend pins"
    assert 'style="background:#2563EB"' in cal, "jade pin color"
    assert "CE 152 Exam" in cal and '<div class="legend">' in cal, "event dot + legend"
    make_figure(["jade", "sam"], counts, hovers, mask, monday, slots)  # smoke test
    print("selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        run_selfcheck()
    else:
        main()
