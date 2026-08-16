<div align="center">

# 📅 SA Schedule Tracker

**Shift coverage at a glance - zero servers**

[![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)](https://www.python.org)

</div>

SA Schedule Tracker turns static class-schedule images into a live
availability calendar for duty shifts. Class schedules are loaded from a
single JSON database and rendered as a month calendar. Each date cell gets
a colored pin for every SA who is busy, a big date number, and
Chinese-calendar accents. The Heatmap view tints the same calendar by
coverage: red when no one is free, amber in between, forest green when
everyone is - so gap days jump out at a glance.

The whole app is **one static HTML file** served from GitHub Pages.
There is no server, no build step at deploy time, no cold start. The link
opens instantly on phones in the group chat.

---

## Table of Contents

- [Why it exists: schedules are images, not data](#why-it-exists-schedules-are-images-not-data)
- [Architecture](#architecture)
- [Features](#features)
- [Repository Layout](#repository-layout)
- [Local Build](#local-build)
- [Deployment (GitHub Pages)](#deployment-github-pages)
- [Overrides (Supabase)](#overrides-supabase)
- [Updating the Schedule](#updating-the-schedule)
- [Checks](#checks)

---

## Why it exists: schedules are images, not data

Shift leads need to know which SAs are free at any given hour, but the raw
source material is a folder of schedule screenshots. Reading five images by
eye to answer one question is slow and error-prone. This project closes the
chain:

| Problem | Solution | Result |
|---|---|---|
| Schedules are images, not data | OCR extracts each SA's class blocks into `schedule.json` | A machine-readable database per SA |
| Each image uses a different time grid | A unified time axis is derived from the union of all slot boundaries | One exact, comparable calendar for everyone |
| Coverage is hard to eyeball | The Heatmap view tints each date by the fewest free SAs | Gap days read red, all-free days read green |
| One-off events shift availability | The Add override form marks anyone busy for a date and slot | Availability stays correct, cells show an orange dot |

## Architecture

```
schedule.json ──▶ tracker.py ──▶ build_site.py ──▶ index.html ──▶ GitHub Pages
(per-SA slots)    (pure domain)   (embeds data +  (one static file)
                   parse, unify,   renders the     │
                   overlap, tint)  calendar)       ▼
                                         Supabase REST (live overrides)
```

Two parts, two kinds of change frequency:

1. **Static part (build time).** `tracker.py` parses the weekly class
   schedule, builds one shared time axis from the union of every slot
   boundary, and computes, per weekday, which SAs are busy in which slot.
   `build_site.py` embeds that compact table into `index.html` together
   with the calendar renderer. Class blocks are semester-fixed, so this
   runs rarely - only when `schedule.json` changes.
2. **Live part (runtime).** The page fetches override rows from Supabase
   REST on load. Anyone in the group chat can add or remove an override
   (person + date + slot + event name) straight from their phone. The
   renderer merges overrides into the busy table client-side, so pins,
   tints, tooltips, and the day detail panel always reflect reality.

Half-open `[start, end)` interval overlap is the only rule: a class ending
at 11:00 never marks the 11:00-11:30 cell busy, and a class or override
makes an SA busy in every cell its interval overlaps.

## Features

- **Calendar with one pin per SA** - every SA has a fixed pin color and a
  fixed punch spot inside each date cell. A pin shows who is busy that
  day; a clean cell means everyone is free. A legend maps colors to names.
- **Coverage tint (Heatmap view)** - each date cell is tinted red (gap)
  through amber to forest green by the fewest free SAs that day. Gap days
  are the loudest cells. A gradient legend under the grid maps tint to
  free count.
- **Traditional calendar motifs** - big centered date numbers, red
  Sundays, a Chinese weekday character (一二三四五六日) in each cell
  corner.
- **Hover with exact names** - tooltips list the busy SAs, then only the
  tight slots: `10:00AM to 11:00AM: no one free`, `01:00PM to 02:00PM:
  only matt free`, and `Event: CE 152 Exam (sam)` lines for overrides.
- **Day detail panel** - tap any day for a per-slot breakdown: time,
  free count, busy names, and every event on that day with a remove
  button. Slots where most SAs are free are highlighted with a green
  bar and bold text.
- **One-off overrides** - the Add override form marks any SA busy for a
  date and time slot with an event name. Rows persist to Supabase and
  sync to everyone's phone immediately. Orange dots flag override dates.
- **Honest URLs** - `index.html?day=2025-08-16` deep-links to a day and
  `?m=2025-08&view=heatmap` to a month view. Plain links, no JavaScript
  bridges.
- **UP Sampa branding** - forest green `#014421` marks the fully-covered
  goal state, and Sampa orange `#F18A1C` dots flag override dates.

## Repository Layout

```
tracker.py        Domain logic: parsing, unified time axis, overlap, tint
build_site.py     Builds index.html (embeds schedule + renderer + CSS)
index.html        The whole app, one self-contained file (committed)
schedule.json     Base weekly schedule (per SA, per day, time-slot strings)
overrides.json    Build-time override snapshot for offline/local preview
.streamlit/       secrets.toml only (Supabase keys, gitignored)
```

Only stdlib. `requests`, `streamlit`, and the venv are gone.

## Local Build

```bash
uv run python tracker.py --selfcheck   # domain logic
uv run python build_site.py --selfcheck
uv run python build_site.py            # writes index.html
python3 -m http.server 8000            # preview at :8000
```

## Deployment (GitHub Pages)

No server, no cold start, free forever:

1. Push the repo to GitHub (it is already public).
2. GitHub -> Settings -> Pages -> Deploy from branch -> `master` -> `/`.
3. The app is live at `https://<user>.github.io/sa-schedule-tracker/`.
   Send that link in the group chat.

The committed `index.html` is what Pages serves. Rebuild and push
whenever `schedule.json` or `overrides.json` changes:

```bash
uv run python build_site.py
git add index.html && git commit -m "Rebuild site" && git push
```

## Overrides (Supabase)

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
4. Build with the keys so the page can talk to Supabase. Locally they
   come from `.streamlit/secrets.toml` (gitignored, kept for local
   builds) or `SUPABASE_URL` / `SUPABASE_ANON_KEY` env vars:

```toml
[supabase]
url = "https://YOUR-PROJECT.supabase.co"
anon_key = "YOUR-ANON-KEY"
```

5. Rebuild and push the site.

The anon key is embedded in the page - that is deliberate. The data is a
public group calendar and the RLS policies let anyone in the group add or
remove overrides. ponytail: no per-person auth; add a shared edit token
or per-person keys if the group ever outgrows trust.

Without keys, `build_site.py` embeds `overrides.json` as a read-only
snapshot instead.

## Updating the Schedule

`schedule.json` is generated by OCR-ing each SA's schedule image (macOS
Vision framework) and mapping class blocks to the image's Y-axis labels.
Class blocks are fixed for the semester, so this is a one-off per
semester. Re-run the OCR pass on new images and rebuild the JSON with the
same `SA -> Day -> ["HH:MMAM to HH:MMPM", ...]` shape. All days
Mon-Sun should be present per SA; empty days use `[]`. Time slots must
match exactly: `HH:MMAM to HH:MMPM`, no space before AM/PM, `12:00PM` for
noon.

## Checks

```bash
uv run python tracker.py --selfcheck
uv run python build_site.py --selfcheck
```

Assert-based self-checks cover slot parsing, time-axis unification,
interval-overlap availability, the coverage tint, and the compact weekly
data the site embeds (verified against the same day over a real week).
