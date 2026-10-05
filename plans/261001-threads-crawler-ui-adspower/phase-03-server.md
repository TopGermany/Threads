---
phase: 3
title: Server
status: completed
priority: P1
effort: 2h
dependencies:
  - 2
---

# Phase 3: Server

## Overview
`app.py`: stdlib `BaseHTTPRequestHandler` (exact routes only) exposing UI + JSON API; crawl in background thread.

## Requirements
- Functional: serve page + vendored SheetJS, fetch GSheet CSV, start crawl, status (incl. rows), download result.
- Non-functional: bind `127.0.0.1:8000` only; one crawl at a time (409); CSRF/DNS-rebinding defense.

## Architecture
| Method | Path | Body / Result |
|---|---|---|
| GET | `/` | `index.html` |
| GET | `/xlsx.full.min.js` | vendored SheetJS |
| POST | `/api/gsheet` | `{url}` → `{columns, rows}` |
| POST | `/api/start` | `{adspower_id, days, rows:[{url,status,...}]}` → 202; 409 running; 400 invalid |
| GET | `/api/status` | `{running, rows, statuses, log[-200:], result, error}` |
| GET | `/api/result` | final JSON attachment |
Everything else → 404 (never `SimpleHTTPRequestHandler`).

Security (every request): `Host` ∈ {`127.0.0.1:8000`, `localhost:8000`} else 403; POST requires `Content-Type: application/json` and `Origin` (if present) = `http://127.0.0.1:8000`/`http://localhost:8000`. Header `Content-Security-Policy: default-src 'self'` on HTML.

State: dict + `threading.Lock`; `on_update` takes the lock; `/api/status` returns a copy. Thread (daemon) target wraps `asyncio.run(crawl_accounts(...))` in `try/except/finally` → always `running=False`, store `error`.

## Related Code Files
- Create: `app.py`
- Modify: `README.md` (later, Phase 5)

## Implementation Steps
1. `ThreadingHTTPServer(("127.0.0.1", 8000), Handler)`; `webbrowser.open`.
2. Host/Origin/Content-Type checks in one helper used by all handlers.
3. Validate start: `adspower_id` matches `[A-Za-z0-9_-]{1,32}`, `days` int 1..365 (changed from 60 during implementation; truncation flag covers large values), rows non-empty list.
4. GSheet: extract `/spreadsheets/d/([\w-]+)` + optional `gid=(\d+)`; build `https://docs.google.com/spreadsheets/d/{id}/export?format=csv&gid={gid}` ourselves (never fetch user URL); non-CSV / HTML login page → 400 "Sheet must be shared: Anyone with link can view"; `csv.reader` header = first row (same rule as SheetJS).
5. Store submitted rows in state so refreshed page can rebuild table.
6. Ctrl+C: `KeyboardInterrupt` → `server.shutdown()`; crawler `finally` handles AdsPower stop.

## Success Criteria
- [ ] `/api/status` works during crawl, returns rows
- [ ] Second Start → 409; crawl exception → `running=false` + error shown
- [ ] Request with `Host: evil.tld` → 403; cross-origin POST → 403
- [ ] `/api/gsheet` with `file:///...` or non-Google URL → 400
- [ ] `GET /.threads_chrome_profile/...` → 404

## Risk Assessment
- Local-only, no auth beyond Host/Origin: acceptable for single-user localhost tool.
