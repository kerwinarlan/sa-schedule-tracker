"""RA Availability Tracker - Streamlit + Plotly heatmap."""
import datetime as dt
import json
import re
import sys
from pathlib import Path

import plotly.graph_objects as go

BASE_FILE = Path(__file__).parent / "schedule.json"
OVERRIDE_FILE = Path(__file__).parent / "overrides.json"
OFF_WHITE, FOREST, ORANGE = "#F4F6F5", "#014421", "#F18A1C"
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


def load_json(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return []


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2))


def week_of(date):
    return date - dt.timedelta(days=date.weekday())


def build_week(parsed, overrides, monday, slots):
    """Availability counts, hover text, and override mask for one week.

    Returns (counts, hovers, mask): each is slots x days, in heatmap
    orientation (outer list = slot rows, inner list = day columns).
    """
    members = sorted(parsed)
    days = [monday + dt.timedelta(days=i) for i in range(7)]
    counts, hovers, mask = [], [], []
    for a, b in slots:
        c_row, h_row, m_row = [], [], []
        for day in days:
            iso, dayname = day.isoformat(), day.strftime("%A")
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
            hover = (
                "Available: " + (", ".join(avail) if avail else "none")
                + " and Busy: " + (", ".join(busy) if busy else "none")
            )
            hover += "".join(f"<br>Event: {e} ({p})" for p, e in events)
            c_row.append(len(avail))
            h_row.append(hover)
            m_row.append(1 if events else float("nan"))
        counts.append(c_row)
        hovers.append(h_row)
        mask.append(m_row)
    return counts, hovers, mask


def make_figure(members, counts, hovers, mask, monday, slots):
    days = [monday + dt.timedelta(days=i) for i in range(7)]
    x = [d.strftime("%a %b %d") for d in days]
    y = [f"{fmt_min(a)} to {fmt_min(b)}" for a, b in slots]
    fig = go.Figure()
    fig.add_trace(
        go.Heatmap(
            z=counts,
            zmin=0,
            zmax=max(1, len(members)),
            colorscale=[[0, OFF_WHITE], [1, FOREST]],
            x=x,
            y=y,
            customdata=hovers,
            hovertemplate="%{customdata}<extra></extra>",
            colorbar={"title": "Available RAs"},
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
    fig.update_layout(
        title=f"Week of {monday.strftime('%b %d, %Y')}",
        yaxis_autorange="reversed",  # earliest slot on top
        height=650,
        plot_bgcolor=OFF_WHITE,
        paper_bgcolor="white",
        margin=dict(l=10, r=10, t=50, b=10),
    )
    return fig


def main():
    import streamlit as st

    st.set_page_config(page_title="RA Availability", page_icon="📅", layout="wide")
    data = load_json(BASE_FILE)
    overrides = load_json(OVERRIDE_FILE)
    if not isinstance(overrides, list):
        overrides = []
    parsed = parse_data(data)
    slots = unified_slots(data)
    members = sorted(data)
    slot_labels = [f"{fmt_min(a)} to {fmt_min(b)}" for a, b in slots]
    slot_by_label = dict(zip(slot_labels, slots))

    st.title("RA Schedule Tracker")
    st.caption("Green intensity = number of available RAs. Orange = exam/event override.")

    with st.sidebar:
        st.header("Week")
        date = st.date_input("Pick any date in the week", value=dt.date.today())
        monday = week_of(date)
        st.caption(f"Showing **{monday.strftime('%b %d, %Y')}**")

        st.header("Add Override")
        with st.form("override_form"):
            person = st.selectbox("RA", members)
            o_date = st.date_input("Event date")
            o_slot = st.selectbox("Time slot", slot_labels)
            event = st.text_input("Event name", placeholder="e.g. CE 152 Exam")
            if st.form_submit_button("Add override"):
                if event.strip():
                    start, end = slot_by_label[o_slot]
                    overrides.append(
                        {
                            "person": person,
                            "date": o_date.isoformat(),
                            "start": start,
                            "end": end,
                            "event": event.strip(),
                        }
                    )
                    save_json(OVERRIDE_FILE, overrides)
                    st.rerun()

        st.header("Overrides This Week")
        week_o = [
            o
            for o in overrides
            if monday <= dt.date.fromisoformat(o["date"]) < monday + dt.timedelta(days=7)
        ]
        if not week_o:
            st.caption("None")
        for i, o in enumerate(week_o):
            c1, c2 = st.columns([3, 1])
            c1.write(
                f"{o['person']} · {o['date']} "
                f"{fmt_min(o['start'])} to {fmt_min(o['end'])} · {o['event']}"
            )
            if c2.button("✕", key=f"del_{i}", help="Remove"):
                overrides.remove(o)
                save_json(OVERRIDE_FILE, overrides)
                st.rerun()

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
    assert counts[1][0] == 1, f"11-11:30am Mon: 1 free, got {counts[1][0]}"
    assert hovers[1][0] == "Available: sam and Busy: jade", hovers[1][0]
    assert counts[2][0] == 2, f"11:30-1pm Mon: 2 free, got {counts[2][0]}"
    assert counts[3][0] == 1, f"1-2:30pm Mon: 1 free, got {counts[3][0]}"
    assert hovers[3][0] == "Available: jade and Busy: sam", hovers[3][0]
    make_figure(["jade", "sam"], counts, hovers, mask, monday, slots)  # smoke test
    print("selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        run_selfcheck()
    else:
        main()
