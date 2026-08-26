"""Build index.html - the static SA availability site.

Run: uv run python build_site.py
Rebuild whenever schedule.json or overrides.json changes.

The site is a single self-contained HTML file: schedule data embedded at
build time, calendar rendered client-side, overrides fetched live from
Supabase REST (or read from the embedded snapshot when Supabase is not
configured). Deploy the file to GitHub Pages.

Supabase config: SUPABASE_URL and SUPABASE_ANON_KEY env vars, else
.streamlit/secrets.toml (kept for local builds).
"""
import datetime as dt
import json
import os
import sys
from pathlib import Path

import tracker as T

HERE = Path(__file__).parent

JS = r"""
"use strict";
const DATA = window.__DATA__;
const members = DATA.members, colors = DATA.colors, slots = DATA.slots,
      dowBusy = DATA.dowBusy, pinPos = DATA.pinPos;
const SUPABASE = DATA.supabase;
const DOW = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];
const MONTHS = ["January","February","March","April","May","June","July",
  "August","September","October","November","December"];
const CN = ["一","二","三","四","五","六","日"];
const STOPS = [[0,[179,48,48]],[0.5,[244,197,66]],[1,[1,68,33]]];

let overrides = (DATA.snapshot || []).slice();
let state = { y: 0, m: 0, day: null, view: "calendar", omitRedundant: false };

const $ = s => document.querySelector(s);
const pad = n => String(n).padStart(2, "0");
const phToday = () => new Date(Date.now() + 8 * 3600e3).toISOString().slice(0, 10);
const fmtMin = m => `${pad((Math.floor(m / 60) % 12) || 12)}:${pad(m % 60)}${Math.floor(m / 60) < 12 ? "AM" : "PM"}`;
const overlap = (a, b) => a[0] < b[1] && b[0] < a[1];
const slotLabel = s => fmtMin(s[0]) + " to " + fmtMin(s[1]);
const parseIso = iso => { const [y, m, d] = iso.split("-").map(Number); return { y, m, d }; };
const isoOf = (y, m, d) => `${y}-${pad(m)}-${pad(d)}`;
const dayName = iso => DOW[new Date(parseIso(iso).y, parseIso(iso).m - 1, parseIso(iso).d).getDay()];

function rgb(count, n) {
  const pos = count / Math.max(1, n);
  for (let i = 0; i < STOPS.length - 1; i++) {
    const [p1, c1] = STOPS[i], [p2, c2] = STOPS[i + 1];
    if (pos >= p1 && pos <= p2) {
      const t = (pos - p1) / (p2 - p1);
      return c1.map((a, j) => Math.round(a + (c2[j] - a) * t));
    }
  }
  return STOPS[STOPS.length - 1][1];
}

function isRedundantOverride(o) {
  const personClean = String(o.person || "").trim().toLowerCase();
  const mi = members.findIndex(m => m.toLowerCase() === personClean);
  if (mi < 0) return true;
  const oDate = String(o.date || "").slice(0, 10);
  const dName = dayName(oDate);
  const busySlots = new Set();
  (dowBusy[dName] || []).forEach(([si, ids]) => {
    if (ids.includes(mi)) busySlots.add(si);
  });
  const oStart = Number(o.start), oEnd = Number(o.end);
  let covered = 0, redundantCovered = 0;
  slots.forEach((st, si) => {
    if (!isNaN(oStart) && !isNaN(oEnd) && overlap([oStart, oEnd], st)) {
      covered++;
      if (busySlots.has(si)) redundantCovered++;
    }
  });
  return covered > 0 && redundantCovered > 0;
}

function filterOverrides(list) {
  const seen = new Set();
  const out = [];
  for (const o of list) {
    if (isRedundantOverride(o)) continue;
    const personClean = String(o.person || "").trim().toLowerCase();
    const oDate = String(o.date || "").slice(0, 10);
    const key = `${personClean}|${oDate}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(o);
  }
  return out;
}

function dayData(iso) {
  // class busy per slot + override events merged
  const slotSets = new Map();
  for (const [si, ids] of (dowBusy[dayName(iso)] || [])) slotSets.set(si, new Set(ids));
  const events = [];
  const validOverrides = filterOverrides(overrides);
  for (const o of validOverrides) {
    const oDate = String(o.date || "").slice(0, 10);
    if (oDate !== iso) continue;
    events.push(o);
    const personClean = String(o.person || "").trim().toLowerCase();
    const mi = members.findIndex(m => m.toLowerCase() === personClean);
    if (mi < 0) continue;
    const oStart = Number(o.start);
    const oEnd = Number(o.end);
    slots.forEach((st, si) => {
      if (!isNaN(oStart) && !isNaN(oEnd) && overlap([oStart, oEnd], st)) {
        if (!slotSets.has(si)) slotSets.set(si, new Set());
        slotSets.get(si).add(mi);
      }
    });
  }
  const counts = slots.map((_, si) => {
    const s = slotSets.get(si);
    return members.length - (s ? s.size : 0);
  });
  const busySet = new Set();
  for (const s of slotSets.values()) for (const i of s) busySet.add(i);
  return { slotSets, counts, busySet, events, minCount: Math.min(...counts) };
}

function titleLines(dd) {
  const lines = [];
  if (dd.busySet.size) lines.push("Busy: " + [...dd.busySet].map(i => members[i]).join(", "));
  else lines.push("Everyone free");
  
  let bestCount = -1;
  let bestSlotText = "";
  slots.forEach((st, si) => {
    const c = dd.counts[si];
    if (c > bestCount) {
      bestCount = c;
      bestSlotText = slotLabel(st);
    }
    if (c === 0) lines.push(slotLabel(st) + ": no one free");
    else if (c === 1) {
      const s = dd.slotSets.get(si) || new Set();
      const free = members.findIndex((_, mi) => !s.has(mi));
      lines.push(slotLabel(st) + ": only " + members[free] + " free");
    }
  });
  if (bestCount > 0) lines.unshift("⭐ Best time: " + bestSlotText + " (" + bestCount + "/" + members.length + " free)");
  for (const o of dd.events) lines.push("Event: " + o.event + " (" + o.person + ")");
  return lines.slice(0, 10).join("\n");
}

function render() {
  const y = state.y, m = state.m;
  const today = phToday();
  $("#month").textContent = MONTHS[m - 1] + " " + y;
  $("#view-" + state.view).classList.add("on");
  $("#view-" + (state.view === "calendar" ? "heatmap" : "calendar")).classList.remove("on");

  const n = members.length;
  const firstDow = (new Date(y, m - 1, 1).getDay() + 6) % 7; // Monday-first, matches headers
  const ndays = new Date(y, m, 0).getDate();
  const cells = [];
  for (let i = 0; i < firstDow; i++) cells.push('<div class="day blank"></div>');
  for (let d = 1; d <= ndays; d++) {
    const iso = isoOf(y, m, d);
    const dd = dayData(iso);
    const cn = CN[new Date(y, m - 1, d).getDay() - 1] || CN[6];
    const cls = ["day"];
    if (new Date(y, m - 1, d).getDay() === 0) cls.push("sun");
    if (iso === today) cls.push("today");
    if (iso === state.day) cls.push("sel");
    let bg = "";
    let heatStripes = "";
    if (state.view === "heatmap") {
      const [r, g, b] = rgb(dd.minCount, n);
      bg = `background:rgba(${r},${g},${b},0.35);`;
      
      // Slot mini-bar gradient or stripes indicating times of day
      const slotGrads = slots.map((_, si) => {
        const c = dd.counts[si];
        const [sr, sg, sb] = rgb(c, n);
        return `rgba(${sr},${sg},${sb},0.85)`;
      });
      heatStripes = `<div class="day-heat-bar">` +
        slotGrads.map(g => `<span class="heat-seg" style="background:${g}"></span>`).join("") +
        `</div>`;
    }
    const busyIndices = [...dd.busySet].sort((a, b) => a - b);
    const pins = busyIndices.length ? `<div class="pin-row">` + busyIndices.map(i =>
      `<span class="pin" style="background:${colors[i]}" title="${members[i]}"></span>`
    ).join("") + `</div>` : "";
    const dots = dd.events.length ? `<div class="event-row">` +
      dd.events.slice(0, 4).map(o => `<span class="epin" title="Event: ${o.event} (${o.person})"></span>`).join("") +
      (dd.events.length > 4 ? `<span class="epin-more">+${dd.events.length - 4}</span>` : "") +
      `</div>` : "";
    cells.push(
      `<a class="${cls.join(" ")}" href="?day=${iso}" style="${bg}" title="${titleLines(dd).replace(/"/g, "&quot;")}">` +
      `<span class="cn">${cn}</span><span class="num">${d}</span>${pins}${dots}${heatStripes}</a>`
    );
  }
  while (cells.length % 7) cells.push('<div class="day blank"></div>');
  const dow = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"].map(d =>
    `<div class="dow${d === "Sun" ? " sun" : ""}">${d}</div>`).join("");
  const legend = members.map((p, i) =>
    `<span class="leg"><span class="ldot" style="background:${colors[i]}"></span>${p}</span>`
  ).join("");
  const he = state.view === "heatmap"
    ? `<div class="helegend"><span class="hlbl">0 free</span>` +
      `<span class="hbar"></span>` +
      `<span class="hlbl">${n} free · everyone</span></div>`
    : "";
  $("#calwrap").innerHTML =
    `<div class="calhead">${dow}</div><div class="cal">${cells.join("")}</div>` +
    `<div class="legend">${legend}</div>${he}`;

  renderDetail();
  renderOverrides();
  $("#addform").style.display = SUPABASE ? "" : "none";
  $("#offline").style.display = SUPABASE ? "none" : "";
}

function renderDetail() {
  const box = $("#detail");
  if (!state.day) { box.innerHTML = ""; return; }
  const { y, m, d } = parseIso(state.day);
  const dd = dayData(state.day);
  const head = DOW[new Date(y, m - 1, d).getDay()] + " · " + MONTHS[m - 1] + " " + d + ", " + y;
  
  // Find top recommended slots (highest free count)
  let maxFree = -1;
  slots.forEach((_, si) => { if (dd.counts[si] > maxFree) maxFree = dd.counts[si]; });
  const topSlots = [];
  if (maxFree > 0) {
    slots.forEach((st, si) => {
      if (dd.counts[si] === maxFree) topSlots.push(slotLabel(st));
    });
  }
  const recBadge = topSlots.length > 1 ? "⭐ BEST MEETING TIMES" : "⭐ BEST MEETING TIME";
  const timesFormatted = topSlots.map(t => `<div class="dd-rec-slot">🕒 ${t}</div>`).join("");
  const recBanner = topSlots.length
    ? `<div class="dd-rec">` +
      `<div class="dd-rec-content">` +
      `<div class="dd-rec-badge">${recBadge}</div>` +
      `<div class="dd-rec-times">${timesFormatted}</div>` +
      `<div class="dd-rec-sub"><b>${maxFree} of ${members.length}</b> SAs are available during this window</div>` +
      `</div>` +
      `<div class="dd-rec-logo"></div>` +
      `</div>`
    : "";

  const summary = dd.busySet.size
    ? "<strong>Busy SAs today:</strong> " + [...dd.busySet].map(i => members[i]).join(", ")
    : "<strong>Availability:</strong> Everyone free all day";
  const ev = dd.events.length
    ? `<div class="dd-events-box">` + dd.events.map(o =>
        `<div class="dd-event"><span>📌 Event: ${o.event} (${o.person})</span>` +
        `<button class="del" data-id="${o.id}">✕</button></div>`).join("") + `</div>`
    : "";
  const rows = slots.map((st, si) => {
    const c = dd.counts[si];
    const [r, g, b] = rgb(c, members.length);
    const hex = "#" + [r, g, b].map(v => pad(v.toString(16))).join("");
    let desc;
    if (c === members.length) desc = "everyone free";
    else if (c === 1) {
      const s = dd.slotSets.get(si) || new Set();
      desc = "only " + members[members.findIndex((_, mi) => !s.has(mi))] + " free";
    } else {
      const s = dd.slotSets.get(si) || new Set();
      desc = "busy: " + [...s].map(i => members[i]).join(", ");
    }
    const hot = c === maxFree && maxFree > 0;
    return `<div class="dd-row${hot ? " hot" : ""}"><span class="dd-time">${slotLabel(st)}</span>` +
      `<span class="dd-dot" style="background:${hex}"></span>` +
      `<span class="dd-count">${c} free</span><span class="dd-desc">${desc}</span></div>`;
  }).join("");
  box.innerHTML =
    `<div class="daydetail"><div class="dd-head">${head}</div>` +
    recBanner +
    `<div class="dd-summary">${summary}</div>${ev}` +
    `<div class="dd-slots">${rows}</div></div>`;
}

function renderOverrides() {
  const prefix = `${state.y}-${pad(state.m)}`;
  const allMonth = filterOverrides(overrides)
    .filter(o => String(o.date).slice(0, 10).startsWith(prefix))
    .sort((a, b) => String(a.date).localeCompare(String(b.date)));
  
  const summaryEl = $("#ovsummary");
  const box = $("#ovlist");

  if (!allMonth.length) {
    if (summaryEl) summaryEl.textContent = `📋 Overrides Log (${MONTHS[state.m - 1]}) · 0 entries`;
    box.innerHTML = "<p class='muted' style='padding:10px;'>No active overrides for this month.</p>";
    return;
  }

  if (summaryEl) {
    summaryEl.textContent = `📋 Overrides Log (${MONTHS[state.m - 1]}) · ${allMonth.length} entries`;
  }

  const selectedPerson = state.filterPerson || "all";
  const rows = selectedPerson === "all"
    ? allMonth
    : allMonth.filter(o => String(o.person || "").trim().toLowerCase() === selectedPerson.toLowerCase());

  const filterBar = `<div class="ov-filter-bar">` +
    `<label for="fov_person">Filter by SA: </label>` +
    `<select id="fov_person">` +
    `<option value="all">All SAs (${allMonth.length})</option>` +
    members.map(m => {
      const cnt = allMonth.filter(o => String(o.person || "").trim().toLowerCase() === m.toLowerCase()).length;
      return `<option value="${m}" ${selectedPerson.toLowerCase() === m.toLowerCase() ? "selected" : ""}>${m} (${cnt})</option>`;
    }).join("") +
    `</select>` +
    `</div>`;

  if (!rows.length) {
    box.innerHTML = filterBar + `<p class='muted' style='padding:10px;'>No overrides for ${selectedPerson}.</p>`;
    bindOvFilter();
    return;
  }

  const cards = rows.map(o => {
    const personClean = String(o.person || "").trim().toLowerCase();
    const mi = members.findIndex(m => m.toLowerCase() === personClean);
    const color = mi >= 0 ? colors[mi] : "var(--green)";
    const name = mi >= 0 ? members[mi] : o.person;
    const timeText = (Number(o.start) === 0 && Number(o.end) === 1440)
      ? "Full Day"
      : slotLabel([Number(o.start), Number(o.end)]);
    const dateStr = String(o.date).slice(0, 10);

    return `<div class="ov-card" style="border-left-color:${color}">` +
      `<div class="ov-card-head">` +
      `<span class="ov-person" style="background:${color}">${name}</span>` +
      `<span class="ov-date">${dateStr}</span>` +
      `<button class="del" data-id="${o.id}" title="Remove override">✕</button>` +
      `</div>` +
      `<div class="ov-event">${o.event}</div>` +
      `<div class="ov-time">🕒 ${timeText}</div>` +
      `</div>`;
  }).join("");

  box.innerHTML = filterBar + `<div class="ov-grid">${cards}</div>`;
  bindOvFilter();
}

function bindOvFilter() {
  const sel = $("#fov_person");
  if (sel) {
    sel.onchange = e => {
      state.filterPerson = e.target.value;
      renderOverrides();
    };
  }
}

async function api(method, path, body) {
  const headers = { apikey: SUPABASE.anon_key, Authorization: "Bearer " + SUPABASE.anon_key };
  if (method === "POST" || method === "DELETE") headers.Prefer = "return=representation";
  if (body) headers["Content-Type"] = "application/json";
  const r = await fetch(SUPABASE.url + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  if (!r.ok) throw new Error("Supabase error " + r.status);
  return r.status === 204 ? null : r.json();
}

async function loadOverrides() {
  if (!SUPABASE) { render(); return; }
  try {
    overrides = await api("GET", "/rest/v1/overrides?select=id,person,date,start,end,event");
  } catch (e) {
    $("#offline").style.display = "";
    overrides = (DATA.snapshot || []).slice();
  }
  render();
}

function msg(text, bad) {
  const el = $("#addmsg");
  el.textContent = text;
  el.style.color = bad ? "#c0392b" : "#014421";
  el.style.display = "";
  setTimeout(() => { el.style.display = "none"; }, 3000);
}

$("#prev").onclick = () => setMonth(state.m === 1 ? state.y - 1 : state.y, state.m === 1 ? 12 : state.m - 1);
$("#next").onclick = () => setMonth(state.m === 12 ? state.y + 1 : state.y, state.m === 12 ? 1 : state.m + 1);
$("#today").onclick = () => {
  const t = parseIso(phToday());
  state.y = t.y; state.m = t.m; state.day = phToday();
  syncUrl(); render();
};

function setMonth(y, m) { state.y = y; state.m = m; state.day = null; syncUrl(); render(); }
function setDay(iso) { state.day = iso; syncUrl(); render(); if (iso) $("#detail").scrollIntoView({ behavior: "smooth", block: "nearest" }); }
function syncUrl() {
  const p = new URLSearchParams();
  if (state.day) p.set("day", state.day);
  else { p.set("m", `${state.y}-${pad(state.m)}`); p.set("view", state.view); }
  history.replaceState({}, "", "?" + p.toString());
}

$("#calwrap").addEventListener("click", e => {
  const a = e.target.closest("a.day");
  if (!a) return;
  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  e.preventDefault();
  const iso = new URL(a.href, location.href).searchParams.get("day");
  const { y, m } = parseIso(iso);
  state.y = y; state.m = m; setDay(iso);
});
$(".bar").addEventListener("click", e => {
  const btn = e.target.closest(".viewbtn");
  if (!btn) return;
  state.view = btn.dataset.view;
  render();
});
document.addEventListener("click", async e => {
  const btn = e.target.closest(".del");
  if (!btn) return;
  if (!confirm("Remove this override?")) return;
  try {
    if (SUPABASE) await api("DELETE", "/rest/v1/overrides?id=eq." + encodeURIComponent(btn.dataset.id));
    overrides = overrides.filter(o => String(o.id) !== String(btn.dataset.id));
    render();
  } catch (err) { msg(err.message, true); }
});

function parseTimeToMin(val) {
  if (!val) return 0;
  const [h, m] = val.split(":").map(Number);
  return h * 60 + m;
}

$("#foverride_type").addEventListener("change", e => {
  const isCustom = e.target.value === "custom";
  $("#slot_preset_wrap").style.display = isCustom ? "none" : "";
  $("#custom_time_wrap").style.display = isCustom ? "grid" : "none";
});

$("#addform").addEventListener("submit", async e => {
  e.preventDefault();
  if (!SUPABASE) return;
  const mode = $("#foverride_type").value;
  let start, end;

  if (mode === "custom") {
    start = parseTimeToMin($("#fstart_time").value);
    end = parseTimeToMin($("#fend_time").value);
    if (end <= start) { msg("End time must be after start time", true); return; }
  } else {
    const slotVal = $("#fslot").value;
    if (slotVal === "fullday") {
      start = 0; end = 1440;
    } else if (slotVal === "morning") {
      start = 420; end = 720; // 7:00 AM - 12:00 PM
    } else if (slotVal === "afternoon") {
      start = 720; end = 1020; // 12:00 PM - 5:00 PM
    } else {
      const si = Number(slotVal);
      start = slots[si][0];
      end = slots[si][1];
    }
  }

  const o = {
    person: $("#fperson").value,
    date: $("#fdate").value,
    start,
    end,
    event: $("#fevent").value.trim(),
  };
  if (!o.date) { msg("Pick a date", true); return; }
  if (!o.event) { msg("Event name required", true); return; }
  try {
    const row = await api("POST", "/rest/v1/overrides", o);
    const added = Array.isArray(row) ? row[0] : row;
    if (added) overrides.push(added);
    render();
    $("#addbox").removeAttribute("open");
    $("#fevent").value = "";
    msg("Added ✔");
  } catch (err) { msg(err.message, true); }
});

function init() {
  const params = new URLSearchParams(location.search);
  const day = params.get("day");
  let y, m;
  if (day) {
    const p = parseIso(day);
    y = p.y; m = p.m;
    state.day = day;
  } else {
    const t = parseIso(phToday());
    y = t.y; m = t.m;
    const mp = params.get("m");
    if (mp) { const p = parseIso(mp + "-01"); y = p.y; m = p.m; }
  }
  state.view = params.get("view") === "heatmap" ? "heatmap" : "calendar";
  state.y = y; state.m = m;
  $("#fperson").innerHTML = members.map(p => `<option>${p}</option>`).join("");
  
  let options = '<option value="fullday">Full Day (All Slots)</option>' +
                '<option value="morning">Morning Half Day (7:00 AM - 12:00 PM)</option>' +
                '<option value="afternoon">Afternoon Half Day (12:00 PM - 5:00 PM)</option>' +
                '<optgroup label="Specific Time Slot">' +
                slots.map((s, i) => `<option value="${i}">${slotLabel(s)}</option>`).join("") +
                '</optgroup>';
  $("#fslot").innerHTML = options;
  $("#fdate").value = day || phToday();
  loadOverrides();
}
init();
"""

CSS = """
:root { --green:#014421; --orange:#F18A1C; --paper:#fffdf8; --line:#d9d3c7; }
* { box-sizing:border-box; }
body { margin:0; background:#F4F6F5; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; color:#1a1a1a; }
header { background:var(--green); color:#fff; padding:14px 16px; display:flex; align-items:center; gap:12px; }
header .logo-head { width:40px; height:40px; background:url('Sampa-logo.png') center/contain no-repeat; border-radius:6px; flex-shrink:0; }
header h1 { margin:0; font-size:19px; }
header p { margin:3px 0 0; font-size:13px; opacity:.9; }
main { max-width:900px; margin:0 auto; padding:12px 12px 48px; }
.bar { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:6px 0 10px; }
button { cursor:pointer; }
.bar button { min-height:40px; min-width:44px; border:1px solid #c9c2b4; background:#fff; border-radius:8px; font-size:15px; padding:6px 12px; touch-action:manipulation; }
.bar button:active { background:#eee; }
#month { flex:1; margin:0; font-size:19px; color:var(--green); text-align:center; }
.view { display:flex; border:1px solid #c9c2b4; border-radius:8px; overflow:hidden; }
.viewbtn { border:none; background:#fff; padding:8px 12px; font-size:13px; min-width:70px; }
.viewbtn.on { background:var(--green); color:#fff; }
.calhead { display:grid; grid-template-columns:repeat(7,1fr); }
.cal { display:grid; grid-template-columns:repeat(7,1fr); gap:1px; background:var(--line); border:1px solid var(--line); }
.dow { text-align:center; font-size:13px; color:#7a746a; font-weight:600; padding:6px 0; }
.dow.sun { color:#c0392b; }
.day { display:block; background:var(--paper); aspect-ratio:1; min-height:56px; position:relative; border:1px solid #a8a092; text-decoration:none; color:inherit; cursor:pointer; }
.day.blank { background:#fff; border:none; }
.day.today { border:3px solid var(--green); }
.day.sel { box-shadow: inset 0 0 0 3px var(--orange); }
.day .cn { position:absolute; top:2px; right:5px; font-size:11px; color:#c3bbaa; }
.day.sun .cn { color:#c0392b; }
.day .num { position:absolute; left:50%; top:44%; transform:translate(-50%,-50%); font-size:20px; font-weight:600; color:#3a3a3a; }
.day.sun .num { color:#c0392b; }
.day.today .num { color:var(--green); font-weight:700; }
.day .pin-row { position:absolute; bottom:5px; left:2px; right:2px; display:flex; justify-content:center; gap:3px; z-index:2; pointer-events:none; }
.day .pin { width:8px; height:8px; border-radius:50%; border:1px solid #fff; box-shadow:0 1px 2px rgba(0,0,0,.3); flex-shrink:0; }
.day .event-row { position:absolute; top:3px; left:3px; max-width:calc(100% - 22px); display:flex; flex-wrap:wrap; gap:2px; z-index:2; pointer-events:none; }
.day .epin { width:6px; height:6px; border-radius:50%; background:var(--orange); box-shadow:0 0 0 1px #fff; flex-shrink:0; }
.day .epin-more { font-size:9px; font-weight:800; color:var(--orange); line-height:1; }
.ov-filter-wrap { margin-bottom:10px; }
.ov-filter-label { font-size:13px; color:#4b5563; display:inline-flex; align-items:center; gap:6px; cursor:pointer; user-select:none; }
.ov-badge-red { font-size:10px; font-weight:700; color:#b45309; background:#fef3c7; border:1px solid #f59e0b; padding:1px 5px; border-radius:4px; margin-left:auto; }
.day-heat-bar { position:absolute; bottom:2px; left:2px; right:2px; height:4px; display:flex; gap:1px; border-radius:2px; overflow:hidden; z-index:1; }
.heat-seg { flex:1; height:100%; }
.legend { margin-top:10px; display:flex; gap:16px; flex-wrap:wrap; font-size:14px; align-items:center; }
.leg { display:inline-flex; align-items:center; gap:6px; font-weight:600; }
.ldot { display:inline-block; width:11px; height:11px; border-radius:50%; border:1px solid rgba(0,0,0,.15); }
.daydetail { margin-top:14px; background:var(--paper); border:1px solid var(--line); border-radius:8px; padding:14px 16px; }
.dd-head { font-size:17px; font-weight:700; }
.dd-rec { position:relative; overflow:hidden; margin:10px 0 14px; padding:16px; background:linear-gradient(135deg, #e9f6e9 0%, #d1e7d1 100%); border-left:6px solid var(--green); border-radius:8px; box-shadow:0 2px 6px rgba(1,68,33,0.12); display:flex; justify-content:space-between; align-items:center; }
.dd-rec-content { position:relative; z-index:2; }
.dd-rec-logo { width:90px; height:90px; background:url('Sampa-logo.png') center/contain no-repeat; opacity:0.18; position:absolute; right:-10px; bottom:-10px; pointer-events:none; z-index:1; }
.dd-rec-badge { font-size:11px; font-weight:800; letter-spacing:0.8px; color:var(--green); text-transform:uppercase; margin-bottom:4px; }
.dd-rec-times { display:flex; flex-direction:column; gap:4px; margin:4px 0 6px; }
.dd-rec-slot { font-size:20px; font-weight:800; color:#014421; line-height:1.2; }
.dd-rec-sub { font-size:13px; color:#2e503a; }
.dd-summary { margin:12px 0 10px; padding:10px 14px; background:#f8fafc; border:1px solid #e2e8f0; border-left:4px solid #64748b; border-radius:6px; font-size:13px; color:#334155; display:flex; align-items:center; gap:8px; }
.dd-events-box { margin:8px 0 12px; padding:10px 14px; background:#fffbe2; border:1px solid #fef08a; border-left:4px solid var(--orange); border-radius:6px; display:flex; flex-direction:column; gap:6px; }
.dd-event { display:flex; justify-content:space-between; align-items:center; gap:8px; font-size:13px; color:#B45309; font-weight:600; }
.dd-slots { display:grid; gap:4px; margin-top:8px; }
.dd-row { display:grid; grid-template-columns:minmax(92px,170px) 12px 52px 1fr; align-items:center; gap:8px; font-size:13px; }
.dd-time { color:#6b7280; }
.dd-dot { width:10px; height:10px; border-radius:50%; }
.dd-count { font-weight:600; }
.dd-desc { color:#6b7280; }
.dd-row.hot { background:#e9f6e9; box-shadow: inset 3px 0 0 var(--green); }
.dd-row.hot .dd-count, .dd-row.hot .dd-desc { font-weight:700; color:var(--green); }
.helegend { display:flex; align-items:center; gap:10px; margin-top:10px; font-size:13px; color:#4b5563; }
.hbar { flex:1; height:12px; border-radius:6px; border:1px solid var(--line); background:linear-gradient(90deg, rgba(179,48,48,.45), rgba(244,197,66,.45), rgba(1,68,33,.45)); }
.del { border:none; background:none; color:#c0392b; font-size:16px; padding:6px 10px; touch-action:manipulation; }
details { margin-top:14px; border:1px solid var(--line); border-radius:8px; background:var(--paper); }
summary { padding:10px 14px; font-weight:600; font-size:14px; cursor:pointer; }
#addform { display:grid; grid-template-columns:1fr 1fr; gap:10px; padding:12px 14px; }
#addform label { font-size:12px; color:#6b7280; display:block; margin-bottom:3px; }
#addform input, #addform select { width:100%; font-size:15px; padding:9px; border:1px solid #c9c2b4; border-radius:6px; background:#fff; }
#addform button { grid-column:1/-1; min-height:44px; font-size:15px; font-weight:600; background:var(--green); color:#fff; border:none; border-radius:8px; }
#addmsg { margin:0 14px 10px; font-weight:600; font-size:13px; display:none; }
#ovbox { margin-top:14px; border:1px solid var(--line); border-radius:8px; background:var(--paper); }
#ovbox summary { padding:10px 14px; font-weight:600; font-size:14px; cursor:pointer; color:#374151; }
#ovlist { padding:12px 14px; border-top:1px solid var(--line); }
.ov-filter-bar { display:flex; align-items:center; gap:8px; margin-bottom:12px; font-size:13px; color:#4b5563; font-weight:600; }
.ov-filter-bar select { font-size:13px; padding:4px 8px; border-radius:6px; border:1px solid #c9c2b4; background:#fff; }
.ov-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(220px, 1fr)); gap:10px; }
.ov-card { background:var(--paper); border:1px solid var(--line); border-left:4px solid var(--green); border-radius:8px; padding:10px 12px; position:relative; display:flex; flex-direction:column; gap:4px; box-shadow:0 1px 3px rgba(0,0,0,.05); }
.ov-card-head { display:flex; align-items:center; gap:6px; font-size:12px; }
.ov-person { color:#fff; font-weight:700; padding:2px 6px; border-radius:4px; text-transform:capitalize; }
.ov-date { color:#6b7280; font-weight:600; }
.ov-card .del { position:absolute; top:4px; right:4px; padding:2px 6px; font-size:14px; }
.ov-event { font-weight:700; font-size:14px; color:#1a1a1a; margin-top:2px; word-break:break-word; padding-right:20px; }
.ov-time { font-size:12px; color:#4b5563; }
.muted { color:#9ca3af; font-size:13px; }
#offline { display:none; color:#B45309; font-size:13px; margin-top:10px; }
footer { text-align:center; color:#9ca3af; font-size:12px; margin-top:18px; }
@media (max-width:480px) {
  .day .num { font-size:16px; }
  .day .pin { width:10px; height:10px; }
  .dd-row { grid-template-columns:minmax(86px,120px) 10px 44px 1fr; gap:5px; font-size:12px; }
  .legend { font-size:13px; gap:10px; }
  #addform { grid-template-columns:1fr; }
  #month { font-size:17px; }
}
"""

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SA Schedule Tracker</title>
<style>{css}</style>
</head>
<body>
<header>
  <div class="logo-head"></div>
  <div>
    <h1>📅 SA Schedule Tracker</h1>
    <p>Pins = busy SAs · orange dot = event override · heatmap tints coverage</p>
  </div>
</header>
<main>
  <div class="bar">
    <button id="prev" title="Previous month">◀ Prev month</button>
    <button id="today" title="Jump to today">Today</button>
    <button id="next" title="Next month">Next month ▶</button>
    <h2 id="month"></h2>
    <div class="view">
      <button class="viewbtn on" id="view-calendar" data-view="calendar">Calendar</button>
      <button class="viewbtn" id="view-heatmap" data-view="heatmap">Heatmap</button>
    </div>
  </div>
  <div id="calwrap"></div>
  <div id="detail"></div>
  <details id="addbox">
    <summary>Add override (exam, activity, duty...)</summary>
    <form id="addform">
      <div><label for="fperson">SA</label><select id="fperson"></select></div>
      <div><label for="fdate">Date</label><input type="date" id="fdate"></div>
      <div>
        <label for="foverride_type">Time Mode</label>
        <select id="foverride_type">
          <option value="preset">Preset Range / Full Day</option>
          <option value="custom">Custom Time (From - To)</option>
        </select>
      </div>
      <div id="slot_preset_wrap"><label for="fslot">Preset Slot</label><select id="fslot"></select></div>
      <div id="custom_time_wrap" style="display:none; grid-column:1/-1; grid-template-columns:1fr 1fr; gap:10px;">
        <div><label for="fstart_time">Start Time</label><input type="time" id="fstart_time" value="08:00"></div>
        <div><label for="fend_time">End Time</label><input type="time" id="fend_time" value="17:00"></div>
      </div>
      <div style="grid-column:1/-1;"><label for="fevent">Event name</label><input id="fevent" placeholder="e.g. CE 152 Exam"></div>
      <button type="submit">Add override</button>
    </form>
    <div id="addmsg"></div>
  </details>
  <p id="offline">⚠ Supabase not configured - showing the build-time snapshot (read-only).</p>
  <details id="ovbox">
    <summary id="ovsummary">📋 Overrides Log</summary>
    <div id="ovlist"></div>
  </details>
  <footer>SA Schedule Tracker · rebuilt with <code>uv run python build_site.py</code></footer>
</main>
<script>window.__DATA__ = {data};</script>
<script>
{js}
</script>
</body>
</html>
"""


def dow_busy(parsed, members, slots):
    """Per weekday: [[slot_idx, [member_idx...]], ...] for slots anyone is busy in."""
    idx = {p: i for i, p in enumerate(members)}
    out = {}
    for d in T.DAYS:
        rows = []
        for si, (a, b) in enumerate(slots):
            busy = [idx[p] for p in members
                    if any(T.overlaps(iv, (a, b)) for iv in parsed[p].get(d, []))]
            if busy:
                rows.append([si, busy])
        if rows:
            out[d] = rows
    return out


def supabase_cfg():
    """(url, anon_key) from env vars, else .streamlit/secrets.toml; None when absent."""
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    if not (url and key):
        try:
            import tomllib
            s = tomllib.loads((HERE / ".streamlit" / "secrets.toml").read_text())
            s = s.get("supabase", {})
            url = (s.get("url") or "").strip().rstrip("/")
            key = (s.get("anon_key") or "").strip()
        except (FileNotFoundError, ValueError):
            return None
    if url and key:
        return url, key
    return None


def is_redundant_override(parsed, o, slots):
    person = str(o.get("person", "")).strip().lower()
    members = sorted(parsed)
    if person not in [m.lower() for m in members]:
        return True
    m_name = next(m for m in members if m.lower() == person)
    iso = str(o.get("date", ""))[:10]
    try:
        dt_obj = dt.date.fromisoformat(iso)
    except ValueError:
        return True
    dayname = dt_obj.strftime("%A")
    a_min, b_min = int(o.get("start", 0)), int(o.get("end", 0))

    covered = 0
    redundant = 0
    for a, b in slots:
        if T.overlaps((a_min, b_min), (a, b)):
            covered += 1
            if any(T.overlaps(iv, (a, b)) for iv in parsed[m_name].get(dayname, [])):
                redundant += 1
    return covered > 0 and redundant > 0


def filter_overrides(parsed, list_ov, slots):
    seen = set()
    out = []
    for o in list_ov:
        if not isinstance(o, dict) or is_redundant_override(parsed, o, slots):
            continue
        p = str(o.get("person", "")).strip().lower()
        d = str(o.get("date", ""))[:10]
        key = f"{p}|{d}"
        if key in seen:
            continue
        seen.add(key)
        out.append(o)
    return out


def build():
    data = json.loads((HERE / "schedule.json").read_text())
    for sa, days in data.items():
        missing = [d for d in T.DAYS if d not in days]
        assert not missing, f"{sa}: missing days {missing}"
        for d in T.DAYS:
            for s in days[d]:
                T.parse_slot(s)  # validates format

    parsed = T.parse_data(data)
    slots = T.unified_slots(data)
    members = sorted(data)
    colors = [T.SA_COLORS[i % len(T.SA_COLORS)] for i in range(len(members))]
    db = dow_busy(parsed, members, slots)

    # verify the compact weekly data against the tested day_stats() on a real week
    week = dt.date(2024, 10, 14)  # Monday
    for d in T.DAYS:
        day = week + dt.timedelta(days=T.DAYS.index(d))
        stats = T.day_stats(parsed, [], day, slots)
        expect = [[si, [members.index(p) for p in busy]]
                  for si, (_, busy) in enumerate(stats) if busy]
        assert db.get(d, []) == expect, (d, db.get(d), expect)

    snapshot = []
    ovfile = HERE / "overrides.json"
    if ovfile.exists():
        raw_ov = [o for o in json.loads(ovfile.read_text()) if isinstance(o, dict)]
        snapshot = filter_overrides(parsed, raw_ov, slots)

    cfg = supabase_cfg()
    payload = {
        "members": members,
        "colors": colors,
        "slots": slots,
        "dowBusy": db,
        "pinPos": T.PIN_POS,
        "snapshot": snapshot,
        "supabase": {"url": cfg[0], "anon_key": cfg[1]} if cfg else None,
    }
    html = TEMPLATE.replace("{css}", CSS).replace("{js}", JS).replace(
        "{data}", json.dumps(payload).replace("</", "<\\/"))
    (HERE / "index.html").write_text(html)
    print(f"index.html written ({len(html)//1024} KB, {len(members)} members, "
          f"{len(slots)} slots, {'Supabase live' if cfg else 'snapshot-only'})")


def selfcheck():
    # tracker selfcheck already covers parse/unify/overlap; verify dow_busy here
    data = {
        "sam": {"Monday": ["10:00AM to 11:00AM", "01:00PM to 02:30PM"],
                "Tuesday": [], "Wednesday": [], "Thursday": [],
                "Friday": [], "Saturday": [], "Sunday": []},
        "jade": {"Monday": ["10:00AM to 11:30AM"], "Tuesday": [], "Wednesday": [],
                 "Thursday": [], "Friday": [], "Saturday": [], "Sunday": []},
    }
    parsed = T.parse_data(data)
    slots = T.unified_slots(data)
    members = sorted(data)
    assert dow_busy(parsed, members, slots)["Monday"] == \
        [[0, [0, 1]], [1, [0]], [3, [1]]], "jade=0, sam=1"
    print("build selfcheck OK")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        selfcheck()
    else:
        build()
