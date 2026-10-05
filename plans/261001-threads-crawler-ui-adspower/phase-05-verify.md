---
phase: 5
title: Verify
status: completed
priority: P2
effort: 1h
dependencies:
  - 4
---

# Phase 5: Verify

## Overview
End-to-end run on real AdsPower profile; confirm output + failure rules; cleanup + docs.

## Implementation Steps
1. `python threads_views_crawler.py` self-check passes.
2. Sheet: 2 pending rows, 1 Status=done (with existing `<handle>.json`), 1 duplicate, 1 invalid URL. days=5.
3. Check: done row skipped but included in final; duplicate skipped; invalid → error, run continues; per-account JSONs + final JSON; all `posted_at` ≥ cutoff; no text-only posts (spot-check 3); no other-handle links; views match page (spot-check 3); AdsPower browser closed at end (or left open if it was open before).
4. Failure checks: log out AdsPower profile from Threads → row `error`, existing `<handle>.json` untouched; Ctrl+C mid-run → AdsPower stopped, final written.
5. Security checks from Phase 3 success criteria (curl with bad Host/Origin, gsheet file:// URL).
6. Delete `.threads_chrome_profile/` (user approved; old saved Threads login, unused with AdsPower).
7. README (Vietnamese, existing style): install, AdsPower Local API (port, optional `ADSPOWER_URL`/`ADSPOWER_KEY`), English UI requirement, `python app.py`, sheet format, resume = rerun with same sheet (rows with Status done skipped; final merges all existing per-account files). Remove "không đăng nhập" claim — crawler now uses logged-in AdsPower profile.

## Success Criteria
- [ ] All checks in steps 3–5 pass
- [ ] `.threads_chrome_profile/` removed
- [ ] README updated

## Risk Assessment
- Threads rate-limit mid-run: row `error`, earlier files intact; rerun after marking finished rows done.
