<div align="center">

# 📅 SA Schedule Tracker

**Shift coverage at a glance**

[![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io)
[![uv](https://img.shields.io/badge/uv-000000?logo=astral&logoColor=white)](https://docs.astral.sh/uv)

</div>

SA Schedule Tracker turns static class-schedule images into a live
availability calendar for duty shifts. Class schedules are loaded from a
single JSON database and rendered as a month calendar in a Streamlit app.
Each date cell gets a colored pin for every SA who is busy, a big date
number, and Chinese-calendar accents. The Heatmap view tints the same
calendar by coverage: red when no one is free, amber in between, forest
green when everyone is - so gap days jump out at a glance.

---

## Table of Contents

- [Why it exists: schedules are images, not data](#why-it-exists-schedules-are-images-not-data)
- [Architecture](#architecture)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Validation Rules](#validation-rules)
- [Repository Layout](#repository-layout)
- [Local Setup](#local-setup)
- [Deployment](#deployment)
- [Shared Overrides (Supabase)](#shared-overrides-supabase)
- [Shareable Snapshot (schedule.html)](#shareable-snapshot-schedulehtml)
- [Checks](#checks)

---

## Why it exists: schedules are images, not data

Shift leads need to know which SAs are free at any given hour, but the raw
source material is a folder of schedule screenshots. Reading five images by
eye to answer one question is slow and error-prone. This project closes the
chain:

| Problem | Solution | Result |
|---|---|---|
| Schedules are images, not data | macOS Vision OCR extracts each SA's class blocks into `schedule.json` | A machine-readable database per SA |
| Each image uses a different time grid | A unified time axis is derived from the union of all slot boundaries | One exact, comparable calendar for everyone |
| Coverage is hard to eyeball | The Heatmap view tints each date by the fewest free SAs | Gap days read red, all-free days read green |
| One-off events shift availability | Sidebar form adds exam/meeting overrides that persist | Availability stays correct, hover shows the event |

## Architecture

```
┌──────────────────┐   ┌────────────────────────┐   ┌───────────────────────┐
│  schedule.json   │──▶│  parse_slot()          │──▶│  unified_slots()      │
│  (per-SA slots)  │   │  "10:00AM to 11:30AM"  │   │  shared time axis     │
└──────────────────┘   │  -> (600, 690) minutes │   │  (union of boundaries)│
                       └────────────────────────┘   └───────────┬───────────┘
                                                                 ▼
┌──────────────────┐   ┌────────────────────────┐   ┌───────────────────────┐
│  overrides.json  │──▶│  day_stats()           │──▶│  calendar_month()     │
│  (one-off events)│   │  interval overlap      │   │  colored SA pins +    │
└──────────────────┘   │  free count + busy set │   │  coverage tint        │
                       └────────────────────────┘   └───────────────────────┘
```

Data flow:

1. **Parse** - `parse_slot()` converts every `"HH:MMAM to HH:MMPM"` label
   into minute intervals since midnight.
2. **Unify** - `unified_slots()` collects every slot boundary across all SAs
   and builds one shared time axis (13 rows for the current data), so cells
   are comparable even though each source image used a different grid.
3. **Compute** - `day_stats()` marks an SA busy in any slot their classes
   overlap (half-open intervals, so adjacent slots never double-count) and
   applies date-matched overrides.
4. **Render** - `calendar_month()` draws the month grid with a colored pin
   per busy SA, a big date number, Chinese weekday characters, and (in the
   Heatmap view) a red-to-green coverage tint per day.

## Features

- **OCR-built schedule database** - `schedule.json` holds each SA's busy
  slots as exact Y-axis label strings from their own schedule image.
- **Unified time axis** - every SA is projected onto one shared grid built
  from the union of all slot boundaries, so a 10:00-11:30 class and a
  10:00-11:00 class compare precisely instead of blurring into an hourly
  grid.
- **Calendar with one pin per SA** - every SA has a fixed pin color and a
  fixed punch spot inside each date cell. A pin shows who is busy that day;
  a clean cell means everyone is free. A legend below the grid maps each
  color to a name.
- **Coverage tint (Heatmap view)** - the same calendar with a color filter:
  each date cell is tinted red (gap) through amber to forest green
  `#014421` (all free) by the fewest free SAs that day. Gap days are the
  loudest cells, the way capacity dashboards and staffing sheets color them.
- **Traditional calendar motifs** - big centered date numbers, thin grid
  lines, red Sundays, and a Chinese weekday character (一二三四五六日) in
  each cell corner, plus the sexagenary year (e.g. 丙午年) in the header.
- **Hover with exact names** - tooltips list the busy SAs, then only the
  tight slots: `10:00AM to 11:00AM: no one free`, `01:00PM to 02:00PM:
  only matt free`, and `Event: CE 152 Exam (sam)` lines for overrides.
- **One-off overrides** - sidebar form to mark any SA busy for a date and
  time slot with an event name. Overrides persist to Supabase (or to
  `overrides.json` when Supabase is not configured), turn the cell orange,
  and are removable from the sidebar.
- **UP Sampa branding** - forest green `#014421` marks the fully-covered
  goal state, and Sampa orange `#F18A1C` dots flag override dates.

## Tech Stack

| Component   | Technology                    |
| ----------- | ----------------------------- |
| Language    | Python 3                      |
| Web app     | Streamlit                     |
| Calendar    | HTML/CSS month grid           |
| Data source | `schedule.json` (OCR-extracted) |
| Overrides   | Supabase REST API (fallback: `overrides.json`) |
| Snapshot    | `schedule.html` (Plotly.js embedded) |
| OCR (one-off) | macOS Vision framework (Swift) |
| Environment | uv                            |

## Validation Rules

Time slots in `schedule.json` must match this exact format:

- `HH:MMAM to HH:MMPM` (e.g. `10:00AM to 11:30AM`, `01:00PM to 02:30PM`)
- No space before AM/PM; two-digit hours; `12:00PM` for noon.

Overlap rules for pins and coverage:

- A class or override makes an SA busy in every cell its interval overlaps.
- Intervals are half-open `[start, end)`: a class ending at 11:00 never
  marks the 11:00-11:30 cell busy.
- A cell's count is the number of SAs not busy there.

## Repository Layout

```
app.py             Streamlit app: parsing, calendar, sidebar overrides
build_html.py      Builds schedule.html (embeds data + Plotly.js)
schedule.html      Self-contained heatmap snapshot, shareable in any chat
schedule.json      Base weekly schedule (per SA, per day, time-slot strings)
overrides.json     Local override fallback when Supabase is not configured
requirements.txt   streamlit, requests
.streamlit/        Local secrets.toml only (gitignored)
```

## Local Setup

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv) (or use `venv` + `pip`)

### Setup and run

```bash
cd sa-schedule-tracker
uv venv
uv pip install -r requirements.txt
uv run streamlit run app.py
```

The app opens in your browser at `http://localhost:8501`.

No uv? The equivalent classic setup:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

### Updating the schedule database

`schedule.json` is generated by OCR-ing each SA's schedule image (macOS
Vision framework) and mapping class blocks to the image's Y-axis labels.
To refresh it, re-run the OCR pass on new images and rebuild the JSON with
the same `SA -> Day -> ["HH:MMAM to HH:MMPM", ...]` shape. All days
Mon-Sun should be present per SA; empty days use `[]`.

## Deployment

Free public link via Streamlit Community Cloud - no HTML, no code changes:

1. Push the repo to GitHub (it is already public).
2. Sign in at [share.streamlit.io](https://share.streamlit.io) with GitHub.
3. Create app -> pick `sa-schedule-tracker`, branch `master`, main file
   `app.py`.
4. Deploy. Share the URL (e.g. `sa-schedule-tracker.streamlit.app`) in
   the group chat.

Free-tier caveat: the app sleeps after roughly 30 minutes idle and
cold-starts in about 30 seconds on the next visit.

## Shared Overrides (Supabase)

Overrides persist in Supabase so every teammate sees the same list.

1. Create a free project at [supabase.com](https://supabase.com).
2. In the SQL editor, run:

```sql
create table if not exists overrides (
  id uuid primary key default gen_random_uuid(),
  person text not null,
  date text not null,
  start int not null,
  "end" int not null,
  event text not null,
  created_at timestamptz not null default now()
);
alter table overrides enable row level security;
create policy "read" on overrides for select using (true);
create policy "insert" on overrides for insert with check (true);
create policy "delete" on overrides for delete using (true);
```

3. Copy the Project URL and the anon public key (Settings -> API).
4. Locally, create `.streamlit/secrets.toml` (gitignored):

```toml
[supabase]
url = "https://YOUR-PROJECT.supabase.co"
anon_key = "YOUR-ANON-KEY"
```

5. On Streamlit Community Cloud, add the same two keys under App
   settings -> Secrets.

Without secrets the app falls back to the local `overrides.json` file.

## Shareable Snapshot (schedule.html)

`schedule.html` is one self-contained file - schedule data embedded and
Plotly.js embedded - that renders the slot-level heatmap in any browser
with no server. (The app itself is now calendar-first; this snapshot keeps
the hour-by-hour heatmap for chat sharing.) Send it in a group chat;
tapping it shows the heatmap. Overrides embedded are a snapshot: rebuild
when `schedule.json` or `overrides.json` changes:

```bash
uv run python build_html.py
```

## Checks

```bash
uv run python app.py --selfcheck
```

Runs an assert-based self-check: slot parsing, time-axis unification,
interval-overlap availability, calendar pin placement, and the coverage
tint.
