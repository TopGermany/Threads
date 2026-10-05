# Brainstorm: Threads crawler — HTML UI + AdsPower + multi-account

Date: 2026-10-01 · Status: approved

## Problem / requirements
- UI (HTML) to import Excel (.xlsx) or Google Sheet (public link). Columns: `Ten acc` (full profile URL), `Status`.
- Inputs: AdsPower profile ID, `days` (rolling window: now − days×24h → now).
- After import: table of all file columns + Start crawl button.
- Crawl: open AdsPower profile, visit accounts in file order, skip rows with Status done/checked.
- Per account: scroll profile, collect post URLs within window, skip posts without image/video, then visit each post, read views.
- Output: per-account JSON + combined final JSON, downloadable from UI. No write-back to Excel/Sheet.

## Decisions
| Topic | Decision |
|---|---|
| UI stack | Stdlib `http.server` + single `index.html`; SheetJS (CDN) parses xlsx in browser; server fetches GSheet CSV export (CORS) |
| Status | Read at import for skipping; live in-session status only; no file write-back |
| Days | Rolling: cutoff = now − days×24h (Asia/Ho_Chi_Minh irrelevant, compare aware datetimes) |
| Post date | From `time[@datetime]` ISO attr via `//a[.//time[@datetime]]`; display text ("2d", "09/24/26") ignored |
| Originals | Keep only `/@<same handle>/post/...` (drops reposts) |
| Media | Image (non-avatar) or video in post block; text/link-preview-only skipped |
| Views | `//span[contains(normalize-space(.),'views')]`, first non-empty; reuse `normalize_views`; missing → `views: null` |
| AdsPower | Local API `browser/start?user_id=` → ws → `connect_over_cdp`; `browser/stop` at end |
| Concurrency | One crawl at a time, sequential (rate-limit safety) |

## Approaches evaluated
- **A. Local stdlib server + HTML (chosen)**: real HTML UI, crawl in background thread survives page refresh, zero new Python deps.
- B. Streamlit: rerun model fights long crawls, heavy dep, not HTML. Rejected.
- C. Static HTML only: cannot drive Playwright / attach to AdsPower. Rejected.

## Architecture
- `app.py` (new): endpoints `GET /`, `POST /api/gsheet`, `POST /api/start`, `GET /api/status`, `GET /api/result`; background thread runs crawl.
- `index.html` (new): import, inputs, table w/ live status (poll 2s), Start, Download.
- `threads_views_crawler.py` (refactor): crawler functions; drop CLI + hardcoded Windows paths; paths relative to script.
- Scroll stop: no new in-range posts in a scroll AND older-than-cutoff post seen (pinned-post safe) | 3 scrolls nothing new | max scrolls.
- Output: `Data_json/<handle>.json` written per account immediately; `Data_json/final_<YYYYmmdd_HHMM>.json` = `[{account, link, posted_at, views}]`.
- Per-account error → status `error(msg)`, continue.

## Risks
1. Post container / media selector unverified on live DOM — first implementation step is a spike on a real AdsPower profile.
2. AdsPower profile must render Threads in English ("views"); else add "lượt xem" to regex.
3. Threads DOM changes break selectors; keep selectors as constants at top of crawler.

## Validation
- Import sample xlsx + GSheet link → table shows all columns.
- Run on 2 accounts, days=5: per-account JSONs + final JSON; no post older than cutoff; no text-only posts; no reposts; done rows skipped.
- Self-check asserts for `normalize_views`, cutoff/handle filter.

## Next steps
`/ck:plan` with this report.

## Amendments (Red Team, 2026-10-01) — supersede above where conflicting
- Media: checked on post page inside root `article`, not on profile feed.
- Views: user XPath scoped to root article; fallback page-wide.
- Scroll stop: based on own posts of any type; stop when an older-than-cutoff post follows an in-range one, or after 2 consecutive older posts (1 old pinned tolerated).
- Final JSON: merge of all sheet rows' `Data_json/<handle>.json` (incl. Status-done rows), rewritten after each account.
- SheetJS vendored locally (no CDN). Server: exact routes, Host/Origin checks, GSheet URL built from sheet ID.
- Login wall / 429 / zero posts → row error; per-post failure keeps account.
- AdsPower: optional `ADSPOWER_URL`/`ADSPOWER_KEY`; don't stop browser that was already open.
- Delete `.threads_chrome_profile/` during verify phase (user approved).
