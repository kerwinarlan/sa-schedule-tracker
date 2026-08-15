<div align="center">

# 📅 RA Schedule Tracker

**Shift coverage at a glance**

[![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)](https://www.python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io)
[![Plotly](https://img.shields.io/badge/Plotly-3F4F75?logo=plotly&logoColor=white)](https://plotly.com/python)
[![uv](https://img.shields.io/badge/uv-000000?logo=astral&logoColor=white)](https://docs.astral.sh/uv)

</div>

RA Schedule Tracker turns static class-schedule images into a live
availability heatmap for duty shifts. Class schedules are loaded from a
single JSON database, rendered as an interactive Plotly heatmap in a
Streamlit app, and updated on the fly with one-off event overrides for
exams and meetings. Colors use the UP Sampa palette: off-white for zero
available scaling to forest green for full coverage, with an orange accent
for override cells.

---

## Table of Contents

- [Why it exists: schedules are images, not data](#why-it-exists-schedules-are-images-not-data)
- [Architecture](#architecture)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Validation Rules](#validation-rules)
- [Repository Layout](#repository-layout)
- [Local Setup](#local-setup)
- [Checks](#checks)

---

## Why it exists: schedules are images, not data

Shift leads need to know which RAs are free at any given hour, but the raw
source material is a folder of schedule screenshots. Reading five images by
eye to answer one question is slow and error-prone. This project closes the
chain:

| Problem | Solution | Result |
|---|---|---|
| Schedules are images, not data | macOS Vision OCR extracts each SA's class blocks into `schedule.json` | A machine-readable database per SA |
| Each image uses a different time grid | A unified time axis is derived from the union of all slot boundaries | One exact, comparable heatmap for everyone |
| Coverage is hard to eyeball | Plotly heatmap colors each cell by how many RAs are free | Full, partial, and zero coverage at a glance |
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
│  overrides.json  │──▶│  build_week()          │──▶│  Plotly heatmap       │
│  (one-off events)│   │  interval overlap      │   │  hover: Available /   │
└──────────────────┘   │  available vs busy     │   │  Busy / Event names   │
                       └────────────────────────┘   └───────────────────────┘
```

Data flow:

1. **Parse** - `parse_slot()` converts every `"HH:MMAM to HH:MMPM"` label
   into minute intervals since midnight.
2. **Unify** - `unified_slots()` collects every slot boundary across all SAs
   and builds one shared time axis (13 rows for the current data), so cells
   are comparable even though each source image used a different grid.
3. **Compute** - `build_week()` marks an SA busy in any cell their classes
   overlap (half-open intervals, so adjacent slots never double-count) and
   applies date-matched overrides.
4. **Render** - `make_figure()` draws the Plotly heatmap with a custom
   colorscale, an orange overlay layer for override cells, and full-name
   hover tooltips.

## Features

- **OCR-built schedule database** - `schedule.json` holds each SA's busy
  slots as exact Y-axis label strings from their own schedule image.
- **Unified time axis** - every SA is projected onto one shared grid built
  from the union of all slot boundaries, so a 10:00-11:30 class and a
  10:00-11:00 class compare precisely instead of blurring into an hourly
  grid.
- **Hover with exact names** - every cell tooltip shows
  `Available: Name1, Name2 and Busy: Name3`, plus
  `Event: CE 152 Exam (Sam)` lines when overrides exist.
- **Week picker** - pick any date; the app snaps to its week (Mon-Sun) and
  labels columns with real dates.
- **One-off overrides** - sidebar form to mark any RA busy for a date and
  time slot with an event name. Overrides persist to `overrides.json`,
  turn the cell orange, and are removable from the sidebar.
- **UP Sampa branding** - off-white `#F4F6F5` at zero available scaling to
  forest green `#014421` at full coverage, with Sampa orange `#F18A1C` for
  override cells.

## Tech Stack

| Component   | Technology                    |
| ----------- | ----------------------------- |
| Language    | Python 3                      |
| Web app     | Streamlit                     |
| Charts      | Plotly (graph_objects)        |
| Data source | `schedule.json` (OCR-extracted) |
| Overrides   | `overrides.json` (persisted)  |
| OCR (one-off) | macOS Vision framework (Swift) |
| Environment | uv                            |

## Validation Rules

Time slots in `schedule.json` must match this exact format:

- `HH:MMAM to HH:MMPM` (e.g. `10:00AM to 11:30AM`, `01:00PM to 02:30PM`)
- No space before AM/PM; two-digit hours; `12:00PM` for noon.

Overlap rules in the heatmap:

- A class or override makes an RA busy in every cell its interval overlaps.
- Intervals are half-open `[start, end)`: a class ending at 11:00 never
  marks the 11:00-11:30 cell busy.
- A cell's count is the number of SAs not busy there.

## Repository Layout

```
app.py             Streamlit app: parsing, heatmap, sidebar overrides
schedule.json      Base weekly schedule (per SA, per day, time-slot strings)
overrides.json     One-off events added from the sidebar
requirements.txt   streamlit, plotly
```

## Local Setup

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv) (or use `venv` + `pip`)

### Setup and run

```bash
cd ra-schedule-tracker
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

## Checks

```bash
uv run python app.py --selfcheck
```

Runs an assert-based self-check: slot parsing, time-axis unification,
interval-overlap availability, override-to-orange mapping, and hover text.
