---
title: Threads crawler UI + AdsPower multi-account
description: >-
  Local HTML UI to import account list (xlsx/GSheet), crawl views of media posts
  in last N days via AdsPower profile, export per-account + final JSON
status: completed
priority: P2
branch: ''
tags:
  - crawler
  - playwright
  - adspower
  - ui
blockedBy: []
blocks: []
created: '2026-10-01T10:20:47.271Z'
createdBy: 'ck:plan'
source: skill
---

# Threads crawler UI + AdsPower multi-account

## Overview

Source design: `plans/reports/brainstorm-261001-threads-crawler-ui-adspower.md` (approved; amended by Red Team Review below).

`python app.py` → `http://127.0.0.1:8000`. User imports `.xlsx` (vendored SheetJS in browser) or public Google Sheet link (server builds CSV export URL from sheet ID), enters AdsPower profile ID + `days`, sees table, clicks Start. Background thread attaches Playwright to AdsPower browser (`connect_over_cdp`), crawls accounts in order (skip Status done, duplicates, invalid URLs), writes `Data_json/<handle>.json` per successful account (atomic), rewrites `Data_json/final_<ts>.json` after each account from all sheet rows' per-account files, stops AdsPower (unless it was already open). UI polls status (restorable after refresh); Download returns final JSON.

Key rules:
- cutoff = now − days×24h from `time[@datetime]` ISO attr (ignore "2d"/"09/24/26" text).
- Feed: collect own-handle (case-insensitive) in-range posts; pinned-safe stop; truncated flag at max scrolls.
- Post page: root `article` → skip if no image/video; views = first `.//span[contains(normalize-space(.),'views')]` in root (fallback page-wide); missing → `null`.
- Login wall / 429 / zero posts → row `error`, never `done 0`; per-post failure → `views: null` + `error`, account continues.
- Security: rows validated via `profile_url` rules and navigation uses rebuilt URL; Host/Origin checks; exact routes; `adspower_id` allowlisted; GSheet URL built server-side.

Deps: `playwright` only (stdlib server). Target OS: Windows; paths relative to script; AdsPower via `ADSPOWER_URL`/`ADSPOWER_KEY` env (optional).

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [DOM spike](./phase-01-dom-spike.md) | Completed |
| 2 | [Crawler refactor](./phase-02-crawler-refactor.md) | Completed |
| 3 | [Server](./phase-03-server.md) | Completed |
| 4 | [HTML UI](./phase-04-html-ui.md) | Completed |
| 5 | [Verify](./phase-05-verify.md) | Completed |

## Dependencies

None (no other plans). Runtime: AdsPower app running with Local API enabled; AdsPower profile logged in to Threads, UI in English.

## Red Team Review

### Session — 2026-10-01
**Findings:** 15 after dedupe of 24 (14 accepted incl. 4 modified, 1 partially rejected: `/api/stop` endpoint)
**Severity breakdown:** 4 Critical, 8 High, 3 Medium

| # | Finding | Severity | Disposition | Applied To |
|---|---------|----------|-------------|------------|
| 1 | Lost 429/HTTP/empty guards → silent "done 0" | Critical | Accept | Completed |
| 2 | One post failure loses whole account | Critical | Accept | Completed |
| 3 | `profile_url` deleted: arbitrary URL nav, path traversal, handle case | Critical | Accept | Completed |
| 4 | Localhost CSRF / DNS rebinding | Critical | Accept | Completed |
| 5 | `adspower_id` query injection | High | Accept | Completed |
| 6 | `/api/gsheet` SSRF | High | Accept | Phase 3 |
| 7 | Pinned-post stop rule broken | High | Accept | Phase 2 |
| 8 | Feed media detection unreliable (lazy-load) | High | Accept → media checked on post page | Phase 1, 2 |
| 9 | Page-wide views XPath may hit comment | High | Accept (modified: scope to root article, fallback page-wide) | Phase 1, 2 |
| 10 | No resume; partial final; overwrite on failure; duplicates | High | Accept (modified: final = all sheet rows' files, rolling; atomic writes; dedupe) | Phase 2, 5 |
| 11 | AdsPower API key/port/already-open | High | Accept | Phase 1, 2 |
| 12 | Header/checkbox Status normalization | High | Accept | Phase 4 |
| 13 | Thread crash/Ctrl+C/refresh lifecycle | Medium | Accept (modified: no `/api/stop`, YAGNI) | Phase 2, 3, 4 |
| 14 | Silent truncation; all-null views | Medium | Accept | Phase 2 |
| 15 | CDN SheetJS, static serving, innerHTML, session dir | Medium | Accept (+ delete `.threads_chrome_profile/`, user approved) | Phase 3, 4, 5 |

### Whole-Plan Consistency Sweep
- Delta: media check feed→post page; views scoped to root article; final merge = all sheet rows' files (not "this run"); status normalized in UI to `url`/`status`; SheetJS vendored (no CDN); `browser/stop` only if we opened it.
- Brainstorm report amended for superseded decisions (media, stop rule, final merge, SheetJS CDN).
- No unresolved contradictions.
