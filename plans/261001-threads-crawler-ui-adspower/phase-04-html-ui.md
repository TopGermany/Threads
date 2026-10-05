---
phase: 4
title: HTML UI
status: completed
priority: P2
effort: 2h
dependencies:
  - 3
---

# Phase 4: HTML UI

## Overview
`index.html` (inline CSS) + `ui.js` (separate so CSP can forbid inline scripts) + vendored `xlsx.full.min.js` for import, inputs, table, start, download.

## Requirements
- Functional: import `.xlsx/.xls/.csv` file or GSheet URL; show all file columns; AdsPower ID + days inputs; Start; live Progress column; log box; Download final JSON.
- Non-functional: no build step, no CDN at runtime.

## Architecture
- File: `XLSX.read(arrayBuffer)` → first sheet → `sheet_to_json(ws, {defval: ""})` (header = row 1).
- GSheet: `POST /api/gsheet`.
- Header normalization (once, here): trim + lowercase; `ten acc` → `url`, `status` → `status`. Missing `ten acc` → error, Start disabled. Send `{url, status: String(status).trim().toLowerCase()}` + original columns for display.
- Done statuses: `done`, `checked`, `true`, `x`, `1` (checkbox booleans become `"true"`).
- On page load: `GET /api/status`; if `running` → rebuild table from server `rows`, lock import, start polling.
- Start: `POST /api/start` (JSON); poll `/api/status` every 2s until `running=false`.
- Table: original columns + Progress (pending/running/done N/done N (truncated)/warning/error/skipped).

## Related Code Files
- Create: `index.html`, `xlsx.full.min.js` (download pinned build from `cdn.sheetjs.com`, current version)

## Implementation Steps
1. Layout: import card (file + GSheet URL + Load), settings (AdsPower ID, days default 5), table, log, buttons.
2. Render every server- or file-supplied string (cells, statuses, log, filenames, errors) via `textContent` only.
3. Disable Start while running; show Download when `result` present.

## Success Criteria
- [ ] Sample xlsx and GSheet both render full table
- [ ] Header `Ten Acc ` / checkbox Status column handled
- [ ] Refresh mid-crawl → table + progress restored
- [ ] No `innerHTML` with dynamic data (grep check)

## Risk Assessment
- Untrusted cell/log content: textContent + CSP from server.
