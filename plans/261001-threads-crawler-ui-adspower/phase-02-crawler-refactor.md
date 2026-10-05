---
phase: 2
title: Crawler refactor
status: completed
priority: P1
effort: 4h
dependencies:
  - 1
---

# Phase 2: Crawler refactor

## Overview
Rework `threads_views_crawler.py` into crawl functions driven by AdsPower; drop CLI + hardcoded Windows paths; keep existing safety checks.

## Requirements
- Functional: AdsPower start/stop, per-account scroll+collect, per-post media+views, per-account JSON, rolling final merge, progress callback.
- Non-functional: sequential; delays kept (900ms scroll, 500ms between posts); selectors as top-level constants; Python ≥3.9 (`timezone.utc`, not `datetime.UTC`).

## Architecture
```python
BASE = Path(__file__).parent; OUT = BASE / "Data_json"
ADSPOWER_URL = os.environ.get("ADSPOWER_URL", "http://local.adspower.net:50325")
ADSPOWER_KEY = os.environ.get("ADSPOWER_KEY")          # Bearer header if set
ADSPOWER_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")

def profile_handle(url) -> str          # reuse profile_url() rules (https, threads.com, /@[A-Za-z0-9._]+/?) → lowercase handle; else ValueError
def adspower_call(path, **params) -> dict  # urlencode params; Bearer if key; code!=0 → RuntimeError(msg)
# start: if browser/active says Active → reuse its ws, remember was_open=True (don't stop at end)

async def collect_posts(page, handle, cutoff) -> tuple[list[dict], bool]   # (posts[{link, posted_at}], truncated)
    # per scroll: one page.evaluate over a[.//time[@datetime]] → [{href, dt}]
    # in-range own post: href.lower() matches ^/@{handle}/post/  and dt >= cutoff  (no media check here)
    # stop: own post older than cutoff seen after an in-range one
    #       | 2 consecutive own posts older than cutoff (no in-range posts; 1 old pinned tolerated)
    #       | 3 scrolls no new anchors | max_scrolls (=60) → truncated=True if never saw older post
    # 0 anchors total → raise "no posts visible (login wall / blocked?)"

async def read_post(page, link) -> dict | None
    # goto (timeout 30s); root = first_post_article(page)  (kept, timeout 10s)
    # media = root has video or img not avatar; not media → None (skipped)
    # views: root.locator("xpath=.//span[contains(normalize-space(.),'views')]") first VIEW_RE match;
    #        fallback page-wide same XPath; none → None value
    # → {"link", "posted_at", "views": int|null}

async def crawl_accounts(user_id, rows, days, on_update) -> Path
    # rows = [{url, status}] (normalized by UI); cutoff = now(timezone.utc) - timedelta(days)
    # pre-pass: status done → skipped; invalid url → error; duplicate handle → skipped(duplicate)
    # adspower start INSIDE try; finally: page.close(); stop only if not was_open
    # per account:
    #   resp = goto_when_settled(profile); resp.status 429/>=400 or url has /login → error (port of :177-191)
    #   posts, truncated = collect_posts
    #   for post: try read_post except → {"link","posted_at","views":None,"error":str(e)}; sleep 500ms
    #   write OUT/<handle>.json atomically (tmp + os.replace), only on account success
    #   status: done N | done N (truncated) | warning: no views (all null, N>0) | error: msg
    #   rewrite final after each account
    # final = merge OUT/<handle>.json for ALL sheet rows that have a file (incl. skipped-done) → OUT/final_<run ts>.json
```
Row output: `{"account": url, "link": post_url, "posted_at": iso, "views": int|null}` (+ `"error"` on per-post failure).
Per-account file: `{"account", "crawled_at", "days", "truncated", "posts": [...]}`.

## Related Code Files
- Modify: `threads_views_crawler.py` — keep `VIEW_RE`, `POST_PATH_RE`, `normalize_views`, `profile_url` (as validator), `goto_when_settled`, `first_post_article`; port HTTP/empty guards from `crawl` (:177-191); delete `parse_range`, `output_path_for_profile`, `crawl`, `main`, Windows constants.
- Delete: `test_threads_views.json`

## Implementation Steps
1. Constants from Phase 1 + relative paths + env AdsPower config.
2. `profile_handle` from `profile_url` + lowercase; output path asserted inside `OUT` (`resolve().parent == OUT.resolve()`).
3. `adspower_call` with `urllib.parse.urlencode`, optional Bearer, `browser/active` check.
4. `collect_posts` with pinned-safe stop + truncated flag + zero-anchor error.
5. `read_post` with root-article media + views, explicit timeouts.
6. `crawl_accounts` with per-post try/except, atomic writes, rolling final merge, `on_update`.
7. `KeyboardInterrupt` path: `finally` still stops AdsPower (if we opened it) and writes final.
8. `__main__`: assert self-check for `normalize_views`, `profile_handle` (case, traversal `@..`, post URL rejected), in-range/stop logic as pure fn.

## Success Criteria
- [ ] Self-check passes
- [ ] No absolute Windows paths
- [ ] Login wall / 429 → row `error`, never `done 0`
- [ ] One failed post does not lose the account
- [ ] Failed account never overwrites existing `<handle>.json`

## Risk Assessment
- `connect_over_cdp`: never `browser.close()` on an AdsPower browser we did not open; close only our page.
- Extra page loads (text-only posts visited to check media) — accepted for correctness.
