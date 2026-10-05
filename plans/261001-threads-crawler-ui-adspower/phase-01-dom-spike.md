---
phase: 1
title: DOM spike
status: completed
priority: P1
effort: 1h
dependencies: []
---

# Phase 1: DOM spike

## Overview
Confirm live Threads DOM + AdsPower API details inside a real AdsPower profile before writing crawler logic.

## Requirements
- Functional: verified selectors for (a) feed post anchor + datetime, (b) root article on post page, (c) media inside root article, (d) views span inside root article, (e) "not logged in / blocked" indicator.
- Non-functional: throwaway; findings become constants in Phase 2.

## Architecture
Manual DevTools console in AdsPower browser on a real profile page + post pages. <!-- Red Team: media check moved from feed to post page (lazy-load unreliable on feed) -->

## Related Code Files
- None (findings → Phase 2 constants)

## Implementation Steps
1. AdsPower: note Local API port (Settings → Local API; may differ from 50325) and whether "security verification" (API key) is on.
2. Profile page console: `$x("//a[.//time[@datetime]]")` → confirm href `/@handle/post/<code>`, `time.datetime` ISO, handle casing in href.
3. Pinned post: confirm it renders first with older datetime (validates stop rule in Phase 2).
4. Reposts: confirm repost anchor href points to other user's handle.
5. Post page: confirm `article` first = root post (`threads_views_crawler.py:91-95` assumption still true).
6. Media in root article: `img` excluding avatar (alt contains "profile picture") OR `video`. Test text-only → false, image → true, video → true, link-preview → false.
7. Views: `$x(".//span[contains(normalize-space(.), 'views')]", rootArticle)` → first = root views; format "1,234 views"/"1.2K views".
8. Logged-out / rate-limited state: note URL (`/login`?) or DOM marker to detect it.
9. Profile UI language: must be English; record if not.

## Success Criteria
- [ ] Root-article media test verified on ≥4 post types
- [ ] Views selector inside root article verified on ≥2 posts
- [ ] Login-wall marker recorded
- [ ] AdsPower port + key requirement recorded

## Risk Assessment
- No `article` element on post page → fall back to page-wide first match (user's XPath) and accept comment-view risk; note in README.

## Findings (2026-10-01, profile k19y5vo6, accounts @nifury4s / @remington_cross619 / @zuck)
- AdsPower: `http://127.0.0.1:50325`, API key required (Bearer) — works; `browser/active`, `start`, `stop` OK.
- No `<article>` anywhere (old `first_post_article` always timed out → old `[]` output). Post container = `div[data-pressable-container]`, one per post, one `time` each.
- Media (structural, load-independent): `picture` (image) or `video` inside container. Link preview = `img` inside `a[href^="http"]`, no `picture` → correctly excluded. Avatar img alt "Ảnh đại diện của …".
- Views: page header "Thread / N lượt xem" — user XPath matches 2–4 identical spans; take first. Per-post (A=81, B=2).
- UI language Vietnamese: label "lượt xem"; numbers "65,2K" (comma decimal), "383K". Date display "24/09/2026" (ignored).
- Threads auto-replies: media post A + link-preview reply B (~5s later), both own handle; B skipped by media rule.
- **Deviation from Red Team #8:** media checked on feed (structural `picture`/`video`, not load-dependent) instead of post page → no page loads for non-media posts. Container media merged (OR) across scrolls.
