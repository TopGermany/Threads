"""Crawl view counts of media posts from Threads profiles through AdsPower or local Chrome.

Driven by app.py (local web UI). Run this file directly for a self-check of the
pure helpers. Selectors were verified on the live site on 2026-10-01; Threads
renders no <article>, each post lives in div[data-pressable-container].
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, time as day_start, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urlparse

from playwright.async_api import Error as PlaywrightError, Page, async_playwright


BASE = Path(__file__).resolve().parent
OUT = BASE / "Data_json"
LOCAL_CHROME_PROFILE = BASE / ".chrome_threads_profile"
LOCAL_CHROME_EXE = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
LOCAL_CHROME_CDP = "http://127.0.0.1:9222"
ADSPOWER_URL = os.environ.get("ADSPOWER_URL", "http://127.0.0.1:50325").rstrip("/")
ADSPOWER_KEY = os.environ.get("ADSPOWER_KEY", "")
ADSPOWER_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")
BROWSER_METHODS = {"adspower", "chrome"}

HANDLE_RE = re.compile(r"/@([A-Za-z0-9._]{1,30})/?")
POST_PATH_RE = re.compile(r"^/@([^/]+)/post/([^/?#]+)")
# "81 lượt xem", "65,2K lượt xem", "1.2K views". Vietnamese uses ',' as decimal.
VIEW_RE = re.compile(r"^\s*([\d.,]+)\s*(Tr|[KMBNT])?\s*(views?|lượt xem)\s*$", re.I)
VIEWS_XPATH = "xpath=//span[contains(normalize-space(.), 'lượt xem') or contains(normalize-space(.), 'views')]"
DONE_STATUSES = {"done", "checked", "true", "x", "1"}
VN_TZ = timezone(timedelta(hours=7))  # Vietnam has no DST; avoids needing tzdata on Windows
MAX_SCROLLS = 60
IDLE_WAITS_MS = (900, 1500, 2500, 4000)  # wait after a scroll, by number of scrolls without new posts

# One entry per rendered post: permalink + ISO datetime (from //a[.//time[@datetime]])
# + whether it holds its own image (<picture>) or video. Link previews have neither.
FEED_JS = """() => [...document.querySelectorAll("div[data-pressable-container]")].map(c => {
  const time = c.querySelector("a time[datetime]");
  return {
    href: time ? time.closest("a").getAttribute("href") : null,
    dt: time ? time.getAttribute("datetime") : null,
    media: [...c.querySelectorAll("picture, video")].some(m => m.closest("div[data-pressable-container]") === c),
  };
})"""

# On a post page: caption of the post at `path` + replies below it that contain links.
# Caption text = the <span>/<a> children of the text block; the Translate button and
# the "1/2" thread counter are <div> children and are skipped.
POST_JS = """(path) => {
  const conts = [...document.querySelectorAll("div[data-pressable-container]")];
  const mine = (c) => (el) => el.closest("div[data-pressable-container]") === c;
  const href = (c) => {
    const time = [...c.querySelectorAll("a time[datetime]")].find(mine(c));
    return time ? time.closest("a").getAttribute("href") : "";
  };
  const text = (c) => {
    const block = [...c.querySelectorAll('span[dir="auto"]')].find((s) => mine(c)(s)
      && !s.closest('a, [role="button"], [role="textbox"], [contenteditable]')
      && [...s.children].some((k) => k.tagName === "SPAN"));
    return block ? [...block.children].filter((k) => k.tagName === "SPAN" || k.tagName === "A")
      .map((k) => k.innerText).join("").trim() : "";
  };
  const urls = (c) => [...new Set([...c.querySelectorAll('a[href^="http"]')].filter(mine(c)).map((a) => {
    const url = new URL(a.href);  // outgoing links are wrapped as l.threads.com/?u=<real url>
    return (url.hostname.endsWith("l.threads.com") && url.searchParams.get("u")) || a.href;
  }))];
  const root = conts.findIndex((c) => href(c).toLowerCase() === path.toLowerCase());
  if (root < 0) return null;
  return {
    caption: text(conts[root]),
    comments: conts.slice(root + 1).map((c) => ({
      author: ([...c.querySelectorAll('a[href^="/@"]')].find(mine(c))?.getAttribute("href") || "").split("/")[1]?.slice(1) || "",
      link: href(c) ? "https://www.threads.com" + href(c) : "",
      text: text(c),
      urls: urls(c),
    })).filter((c) => c.urls.length),
  };
}"""
VIEW_LOADS = 3  # first load + 2 reloads when the view count does not show

Updater = Callable[[int, str], None]
Waiter = Callable[[], Awaitable[None]]
WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


class Blocked(RuntimeError):
    """Threads refused the browser (rate limit / login wall): stop the account."""


def account_file(handle: str) -> Path:
    name = f"_{handle}" if handle.split(".")[0] in WINDOWS_RESERVED else handle
    return OUT / f"{name}.json"


def profile_handle(url: str) -> str:
    """Validate a Threads profile URL and return its lowercase handle."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"https", "http"} or parsed.netloc.lower() not in {
        "threads.com", "www.threads.com", "threads.net", "www.threads.net",
    }:
        raise ValueError("not a Threads profile URL")
    matched = HANDLE_RE.fullmatch(parsed.path)
    if not matched:
        raise ValueError("URL must be a profile like https://www.threads.com/@name")
    return matched.group(1).lower()


def normalize_views(label: str) -> int:
    """Convert '81 lượt xem', '65,2K lượt xem' or '1.2K views' into integers."""
    matched = VIEW_RE.match(label)
    if not matched:
        raise ValueError(f"Không đọc được lượt xem: {label!r}")
    number, suffix, word = matched.groups()
    if word.lower() == "lượt xem":
        number = number.replace(".", "").replace(",", ".")
    else:
        number = number.replace(",", "")
    # ponytail: N/Tr/T (nghìn/triệu/tỷ) assumed, only K seen live so far
    scale = {"K": 1e3, "N": 1e3, "M": 1e6, "TR": 1e6, "B": 1e9, "T": 1e9}.get((suffix or "").upper(), 1)
    return round(float(number) * scale)


def reached_cutoff(dates: list[datetime], cutoff: datetime) -> bool:
    """True once the feed (own posts, newest first) has scrolled past the cutoff.

    One old post at the top is tolerated because it may be pinned.
    ponytail: assumes at most one pinned post; tolerate more if Threads allows it.
    """
    seen_recent, old_run = False, 0
    for posted in dates:
        if posted >= cutoff:
            seen_recent, old_run = True, 0
            continue
        old_run += 1
        if seen_recent or old_run >= 2:
            return True
    return False


def date_window(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    """Inclusive Vietnam-time dates -> [start, end) datetimes."""
    start = datetime.combine(date_from, day_start(), VN_TZ)
    return start, datetime.combine(date_to + timedelta(days=1), day_start(), VN_TZ)


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def adspower(path: str, **params: str) -> dict:
    """Call the AdsPower Local API and return its `data` payload."""
    url = f"{ADSPOWER_URL}{path}?{urllib.parse.urlencode(params)}"
    headers = {"Authorization": f"Bearer {ADSPOWER_KEY}"} if ADSPOWER_KEY else {}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        body = json.load(response)
    if body.get("code") != 0:
        raise RuntimeError(f"AdsPower {path}: {body.get('msg')}")
    return body.get("data") or {}


def open_adspower(user_id: str) -> tuple[str, bool]:
    """Return (CDP websocket, was_already_open). Reuse a profile that is already running."""
    active = adspower("/api/v1/browser/active", user_id=user_id)
    was_open = active.get("status") == "Active"
    data = active if was_open else adspower("/api/v1/browser/start", user_id=user_id)
    ws = (data.get("ws") or {}).get("puppeteer")
    if not ws:
        raise RuntimeError("AdsPower did not return a browser connection for this profile")
    return ws, was_open


def chrome_cdp_ready() -> bool:
    try:
        with urllib.request.urlopen(f"{LOCAL_CHROME_CDP}/json/version", timeout=1) as response:
            return response.status == 200
    except OSError:
        return False


def open_local_chrome() -> subprocess.Popen | None:
    """Open real Google Chrome for CDP attach; return process only if we started it."""
    if chrome_cdp_ready():
        return None
    if not LOCAL_CHROME_EXE.exists():
        raise RuntimeError(f"Chrome not found: {LOCAL_CHROME_EXE}")
    LOCAL_CHROME_PROFILE.mkdir(exist_ok=True)
    process = subprocess.Popen([
        str(LOCAL_CHROME_EXE),
        f"--remote-debugging-port={urllib.parse.urlparse(LOCAL_CHROME_CDP).port}",
        f"--user-data-dir={LOCAL_CHROME_PROFILE}",
        "--no-first-run",
        "--new-window",
    ])
    for _ in range(60):
        if chrome_cdp_ready():
            return process
        time.sleep(0.5)
    raise RuntimeError("Chrome opened but its remote debugging port did not become ready")


def write_json_atomic(path: Path, data) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(10):  # Windows refuses to replace a file that is open (download, antivirus)
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.3)


def write_final(handles: list[str], path: Path, start: datetime, end: datetime) -> None:
    """Group the sheet's per-account files by handle, keeping posts inside [start, end)."""
    final = {}
    for handle in handles:
        source = account_file(handle)
        if not source.exists():
            continue
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
            if isinstance(data, dict):  # skip files written by the old CLI version
                final[handle] = {
                    "account": data["account"],
                    "posts": [post for post in data["posts"] if start <= parse_dt(post["posted_at"]) < end],
                }
        except (ValueError, KeyError, TypeError):
            continue  # hand-edited or corrupt file: leave it out rather than stop the run
    write_json_atomic(path, final)


async def goto_when_settled(page: Page, url: str, attempts: int = 3):
    """Navigate after Threads' login/onboarding redirects have settled."""
    for attempt in range(attempts):
        try:
            return await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        except PlaywrightError as error:
            if "interrupted by another navigation" not in str(error) or attempt == attempts - 1:
                raise
            await page.wait_for_timeout(1_500)


def check_page(response, page: Page) -> None:
    """Turn rate limits and login walls into errors instead of empty results."""
    if response and response.status == 429:
        raise Blocked("HTTP 429: Threads rate-limited this browser, try again later")
    if response and response.status >= 400:
        raise RuntimeError(f"HTTP {response.status} from Threads")
    if "/login" in page.url:
        raise Blocked("Threads asked to log in (is the selected browser signed in?)")


async def collect_posts(page: Page, handle: str, cutoff: datetime) -> tuple[list[dict], bool]:
    """Scroll the profile; return (own posts in feed order, truncated)."""
    seen: dict[str, dict] = {}
    hrefs: set[str] = set()  # every post anchor, own or not
    idle = 0
    await page.mouse.move(600, 500)  # wheel events land on the feed, not the fixed side menu
    for _ in range(MAX_SCROLLS):
        before = len(hrefs)
        for item in await page.evaluate(FEED_JS):
            matched = POST_PATH_RE.match(item["href"] or "")
            if not matched or not item["dt"]:
                continue
            hrefs.add(item["href"])
            if matched.group(1).lower() != handle:  # reposts / quotes of other accounts
                continue
            link = f"https://www.threads.com/@{handle}/post/{matched.group(2)}"
            if link in seen:
                seen[link]["media"] |= item["media"]
            else:
                seen[link] = {"link": link, "posted_at": parse_dt(item["dt"]), "media": item["media"]}
        if reached_cutoff([post["posted_at"] for post in seen.values()], cutoff):
            return list(seen.values()), False
        idle = idle + 1 if len(hrefs) == before else 0
        if idle >= len(IDLE_WAITS_MS):  # end of feed
            if not hrefs:
                raise RuntimeError("no posts visible on this profile (private, empty or blocked?)")
            return list(seen.values()), False
        await page.mouse.wheel(0, 1800)
        # The next batch can take seconds to load; give up only after ~9s without new posts.
        await page.wait_for_timeout(IDLE_WAITS_MS[idle])
    return list(seen.values()), True


async def read_views(page: Page) -> int | None:
    labels = page.locator(VIEWS_XPATH)
    try:
        await labels.first.wait_for(state="attached", timeout=10_000)
    except PlaywrightError:
        return None
    # The header label is matched 2-4 times with the same value; the first is enough.
    for text in await labels.all_inner_texts():
        if VIEW_RE.match(text.strip()):
            return normalize_views(text.strip())
    return None


async def read_post(page: Page, link: str) -> dict:
    """Views, caption and link-bearing comments of one post; reload if views do not show."""
    for _ in range(VIEW_LOADS):
        check_page(await goto_when_settled(page, link), page)
        views = await read_views(page)
        if views is not None:
            break
    details = await page.evaluate(POST_JS, urlparse(link).path) or {}
    # ponytail: only comments rendered on first load; scroll the post page if long threads need more
    return {"views": views, "caption": details.get("caption"), "comments": details.get("comments", [])}


async def crawl_account(page: Page, handle: str, start: datetime, end: datetime, progress: Callable[[str], None]):
    check_page(await goto_when_settled(page, f"https://www.threads.com/@{handle}"), page)
    await page.wait_for_timeout(1_500)
    found, truncated = await collect_posts(page, handle, start)  # scroll until older than `start`
    media_posts = [post for post in found if post["media"] and start <= post["posted_at"] < end]
    posts = []
    for number, post in enumerate(media_posts, start=1):
        progress(f"running: {number}/{len(media_posts)} posts")
        row = {"link": post["link"], "posted_at": post["posted_at"].isoformat(),
               "views": None, "caption": None, "comments": []}
        try:
            row.update(await read_post(page, post["link"]))
        except Blocked:
            raise  # every further page would fail too; keep the previous file intact
        except Exception as error:  # keep the account going if one post fails
            row["error"] = str(error).splitlines()[0][:200]
        posts.append(row)
        await page.wait_for_timeout(500)
    if posts and all("error" in post for post in posts):
        raise RuntimeError(f"every post failed: {posts[0]['error']}")
    return posts, truncated


async def crawl_with_page(
    page: Page, handles: list[str], todo: list[tuple[int, str]], start: datetime, end: datetime,
    date_from: date, date_to: date, final_path: Path, on_update: Updater
) -> None:
    for index, handle in todo:
        on_update(index, "running")
        try:
            posts, truncated = await crawl_account(
                page, handle, start, end, lambda text, index=index: on_update(index, text)
            )
            write_json_atomic(account_file(handle), {
                "account": f"https://www.threads.com/@{handle}",
                "crawled_at": datetime.now(timezone.utc).isoformat(),
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "truncated": truncated,
                "posts": posts,
            })
            write_final(handles, final_path, start, end)
        except Exception as error:  # one bad account must not stop the list
            on_update(index, f"error: {str(error).splitlines()[0][:200]}")
            continue
        failed = sum(1 for post in posts if "error" in post)
        if posts and all(post["views"] is None for post in posts):
            status = f"warning: no views found on {len(posts)} posts"
        elif failed:
            status = f"warning: {failed}/{len(posts)} posts failed"
        else:
            status = f"done {len(posts)} posts" + (" (truncated)" if truncated else "")
        on_update(index, status)


async def crawl_accounts(
    browser_method: str, user_id: str, rows: list[dict], date_from: date, date_to: date,
    final_path: Path, on_update: Updater, wait_before_crawl: Waiter | None = None
) -> None:
    """Crawl sheet rows ({"url", "status"}) in order and keep `final_path` up to date."""
    if browser_method not in BROWSER_METHODS:
        raise ValueError("Browser method must be 'adspower' or 'chrome'")
    start, end = date_window(date_from, date_to)
    OUT.mkdir(exist_ok=True)
    handles: list[str] = []
    todo: list[tuple[int, str]] = []
    for index, row in enumerate(rows):
        try:
            handle = profile_handle(str(row.get("url", "")))
        except ValueError as error:
            on_update(index, f"error: {error}")
            continue
        if handle in handles:
            on_update(index, "skipped (duplicate)")
            continue
        handles.append(handle)
        if str(row.get("status", "")).strip().lower() in DONE_STATUSES:
            on_update(index, "skipped (done)")
        else:
            todo.append((index, handle))
            on_update(index, "pending")
    write_final(handles, final_path, start, end)
    if not todo:
        return

    async with async_playwright() as playwright:
        if browser_method == "adspower":
            ws, was_open = open_adspower(user_id)
            try:
                browser = await playwright.chromium.connect_over_cdp(ws)
                page = await browser.contexts[0].new_page()
                try:
                    if wait_before_crawl:
                        await wait_before_crawl()
                    await crawl_with_page(page, handles, todo, start, end, date_from, date_to, final_path, on_update)
                finally:
                    await page.close()  # only our tab; never close a browser AdsPower owns
            finally:
                if not was_open:
                    adspower("/api/v1/browser/stop", user_id=user_id)
        else:
            chrome_process = open_local_chrome()
            browser = await playwright.chromium.connect_over_cdp(LOCAL_CHROME_CDP)
            context = browser.contexts[0]
            page = await context.new_page()
            try:
                if wait_before_crawl:
                    await wait_before_crawl()
                await crawl_with_page(page, handles, todo, start, end, date_from, date_to, final_path, on_update)
            finally:
                await page.close()
                if chrome_process:
                    await browser.close()


if __name__ == "__main__":
    assert normalize_views("81 lượt xem") == 81
    assert normalize_views("65,2K lượt xem") == 65_200
    assert normalize_views("1.234 lượt xem") == 1_234
    assert normalize_views("383K lượt xem") == 383_000
    assert normalize_views("1,234 views") == 1_234
    assert normalize_views("1.2K views") == 1_200
    assert normalize_views("1 view") == 1

    assert profile_handle("https://www.threads.com/@John.Doe/") == "john.doe"
    assert account_file("con").name == "_con.json" and account_file("con.x").name == "_con.x.json"
    assert account_file("connor").name == "connor.json"
    for bad in ("https://evil.tld/@x", "file:///C:/x", "https://www.threads.com/@a/post/abc",
                r"https://www.threads.com/@..\..\x", "https://www.threads.com/@../x"):
        try:
            profile_handle(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")

    start, end = date_window(date(2026, 9, 28), date(2026, 9, 30))
    assert start == datetime(2026, 9, 27, 17, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 30, 17, tzinfo=timezone.utc)  # 30/09 23:59 VN is still inside

    cutoff = datetime(2026, 9, 26, tzinfo=timezone.utc)
    new, old = datetime(2026, 9, 30, tzinfo=timezone.utc), datetime(2026, 9, 1, tzinfo=timezone.utc)
    assert not reached_cutoff([new, new], cutoff)
    assert not reached_cutoff([old, new, new], cutoff)  # old pinned post on top
    assert reached_cutoff([old, new, old], cutoff)
    assert reached_cutoff([new, old], cutoff)
    assert reached_cutoff([old, old], cutoff)  # nothing in range
    print("self-check ok")
