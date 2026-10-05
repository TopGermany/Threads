"""Local web UI for the Threads views crawler.

    python app.py   ->  http://127.0.0.1:8000

Set ADSPOWER_KEY (and ADSPOWER_URL if not http://127.0.0.1:50325) before starting.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import threads_views_crawler as crawler


HOST, PORT = "127.0.0.1", 8000
ALLOWED_HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}
ALLOWED_ORIGINS = {f"http://{host}" for host in ALLOWED_HOSTS}
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/ui.js": ("ui.js", "text/javascript; charset=utf-8"),
    "/xlsx.full.min.js": ("xlsx.full.min.js", "text/javascript; charset=utf-8"),
}
CSP = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:"
SHEET_ID_RE = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")
GID_RE = re.compile(r"[#&?]gid=(\d+)")
MAX_ROWS = 2000

lock = threading.Lock()
state: dict = {
    "running": False,
    "columns": [],
    "rows": [],
    "statuses": [],
    "log": [],
    "result": None,
    "error": None,
    "waiting_for_signin": False,
    "signed_confirmed": False,
}
runner: dict = {}  # loop + task of the crawl in progress, for Ctrl+C


def log(line: str) -> None:
    """Append a timestamped line; caller holds the lock."""
    state["log"].append(f"{datetime.now():%H:%M:%S}  {line}")
    del state["log"][:-500]


def account_name(url: str) -> str:
    try:
        return "@" + crawler.profile_handle(url)
    except ValueError:
        return url


def on_update(index: int, status: str) -> None:
    with lock:
        state["statuses"][index] = status
        name = f"{account_name(state['rows'][index]['url'])} (dòng {index + 1}/{len(state['rows'])})"
        if status == "running":
            log(f"▶ Đang cào {name}")
        elif status.startswith(("done", "warning")):
            done = sum(s.startswith(("done", "warning")) for s in state["statuses"])
            log(f"✓ XONG {name}: {status}  [{done} acc xong]")
        elif status.startswith("error"):
            log(f"✗ LỖI {name}: {status.removeprefix('error: ')}")
        elif status.startswith("skipped"):
            log(f"– Bỏ qua {name}: {status}")
        # "pending" and per-post "running: n/m" stay in the table only


async def wait_for_signed_confirmation() -> None:
    with lock:
        state["waiting_for_signin"] = True
        state["signed_confirmed"] = False
        log("Browser opened. Log in to Threads if needed, then click Already signed.")
    while True:
        with lock:
            if state["signed_confirmed"]:
                state["waiting_for_signin"] = False
                log("Sign-in confirmed. Starting crawl.")
                return
        await asyncio.sleep(0.5)


def run_crawl(
    browser_method: str, user_id: str, rows: list[dict], date_from: date, date_to: date, final_name: str
) -> None:
    loop = asyncio.new_event_loop()
    task = loop.create_task(
        crawler.crawl_accounts(
            browser_method, user_id, rows, date_from, date_to, crawler.OUT / final_name,
            on_update, wait_for_signed_confirmation
        )
    )
    runner.update(loop=loop, task=task)
    try:
        loop.run_until_complete(task)
    except asyncio.CancelledError:
        with lock:
            state["error"] = "Stopped (Ctrl+C)"
    except Exception as error:  # surface AdsPower / connection failures in the UI
        with lock:
            state["error"] = str(error).splitlines()[0][:300]
    finally:
        loop.close()
        runner.clear()
        with lock:
            state["running"] = False
            state["waiting_for_signin"] = False
            state["statuses"] = [
                "error: stopped" if status == "pending" or status.startswith("running") else status
                for status in state["statuses"]
            ]
            count = lambda prefix: sum(s.startswith(prefix) for s in state["statuses"])  # noqa: E731
            log(f"■ KẾT THÚC: {count(('done', 'warning'))} xong, {count('error')} lỗi, "
                f"{count('skipped')} bỏ qua. File: Data_json/{final_name}")


def fetch_gsheet(url: str) -> tuple[list[str], list[dict]]:
    """Download a public Google Sheet as CSV. The URL is rebuilt, never fetched as given."""
    sheet = SHEET_ID_RE.search(url or "")
    if not sheet:
        raise ValueError("Not a Google Sheets link")
    gid = GID_RE.search(url)
    export = f"https://docs.google.com/spreadsheets/d/{sheet.group(1)}/export?format=csv"
    if gid:
        export += f"&gid={gid.group(1)}"
    not_public = ValueError("Sheet is not public: share it as 'Anyone with the link can view'")
    try:
        with urllib.request.urlopen(export, timeout=30) as response:
            if response.headers.get_content_type() != "text/csv":
                raise not_public
            text = response.read().decode("utf-8-sig")
    except urllib.error.HTTPError as error:
        raise not_public from error
    reader = csv.reader(io.StringIO(text))
    columns = next(reader, [])
    rows = [dict(zip(columns, cells)) for cells in reader if any(cell.strip() for cell in cells)]
    return columns, rows


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def send(self, code: int, body: bytes, content_type: str, headers: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, code: int, data) -> None:
        self.send(code, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def allowed(self) -> bool:
        """Block DNS rebinding (Host) and cross-site requests (Origin)."""
        origin = self.headers.get("Origin")
        if self.headers.get("Host") not in ALLOWED_HOSTS or (origin and origin not in ALLOWED_ORIGINS):
            self.send_json(403, {"error": "forbidden"})
            return False
        return True

    def do_GET(self) -> None:
        if not self.allowed():
            return
        path = self.path.split("?")[0]
        if path in STATIC:
            name, content_type = STATIC[path]
            self.send(200, (crawler.BASE / name).read_bytes(), content_type, {"Content-Security-Policy": CSP})
        elif path == "/api/status":
            with lock:
                snapshot = json.loads(json.dumps(state))
            self.send_json(200, snapshot)
        elif path == "/api/result":
            with lock:
                name = state["result"]
            result = crawler.OUT / name if name else None
            if not result or not result.exists():
                self.send_json(404, {"error": "no result yet"})
                return
            self.send(200, result.read_bytes(), "application/json; charset=utf-8",
                      {"Content-Disposition": f'attachment; filename="{name}"'})
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self.allowed():
            return
        if self.headers.get_content_type() != "application/json":
            self.send_json(415, {"error": "JSON body required"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= 5_000_000:
            self.send_json(413, {"error": "request too large"})
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self.send_json(400, {"error": "invalid JSON"})
            return
        path = self.path.split("?")[0]
        if path == "/api/gsheet":
            try:
                columns, rows = fetch_gsheet(str(body.get("url", "")))
            except (ValueError, OSError, csv.Error) as error:
                self.send_json(400, {"error": str(error)})
                return
            self.send_json(200, {"columns": columns, "rows": rows})
        elif path == "/api/start":
            self.start(body)
        elif path == "/api/already-signed":
            with lock:
                if not state["running"] or not state["waiting_for_signin"]:
                    self.send_json(409, {"error": "Crawler is not waiting for sign-in confirmation"})
                    return
                state["signed_confirmed"] = True
            self.send_json(200, {"ok": True})
        else:
            self.send_json(404, {"error": "not found"})

    def start(self, body: dict) -> None:
        browser_method = str(body.get("browser_method", "adspower")).strip().lower()
        user_id = str(body.get("adspower_id", "")).strip()
        rows, columns = body.get("rows"), body.get("columns")
        try:
            date_from = date.fromisoformat(str(body.get("date_from")))
            date_to = date.fromisoformat(str(body.get("date_to")))
        except ValueError:
            date_from = date_to = None
        if browser_method not in crawler.BROWSER_METHODS:
            error = "Choose AdsPower or Chrome"
        elif browser_method == "adspower" and not crawler.ADSPOWER_ID_RE.fullmatch(user_id):
            error = "AdsPower profile ID must be letters, digits, - or _"
        elif not date_from or not date_to:
            error = "Choose both dates (from and to)"
        elif date_from > date_to:
            error = "'From' date must not be after 'to' date"
        elif (date_to - date_from).days > 365:
            error = "Date range can be at most one year"
        elif not isinstance(rows, list) or not rows or len(rows) > MAX_ROWS or not isinstance(columns, list):
            error = f"Import a sheet with 1 to {MAX_ROWS} rows first"
        elif not all(isinstance(row, dict) and isinstance(row.get("url"), str) for row in rows):
            error = "Every row needs a 'Ten acc' value"
        else:
            error = None
        if error:
            self.send_json(400, {"error": error})
            return
        final_name = f"final_{datetime.now():%Y%m%d_%H%M%S}.json"
        with lock:
            if state["running"]:
                self.send_json(409, {"error": "A crawl is already running"})
                return
            state.update(running=True, columns=columns, rows=rows, statuses=["pending"] * len(rows),
                         log=[], result=final_name, error=None, browser_method=browser_method,
                         waiting_for_signin=False, signed_confirmed=False)
        threading.Thread(
            target=run_crawl,
            args=(browser_method, user_id, rows, date_from, date_to, final_name),
            daemon=True,
        ).start()
        self.send_json(202, {"ok": True})


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"Threads crawler UI: {url}  (Ctrl+C to quit)")
    if not crawler.ADSPOWER_KEY:
        print("Warning: ADSPOWER_KEY is not set; AdsPower calls fail if its API key check is on.")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    webbrowser.open(url)
    try:
        while True:  # time.sleep stays interruptible by Ctrl+C on Windows
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping...")
        loop, task = runner.get("loop"), runner.get("task")
        if loop and task:  # let the crawler's finally blocks close our tab and AdsPower
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:  # crawl finished and closed its loop meanwhile
                pass
            for _ in range(60):
                if not runner:
                    break
                time.sleep(1)
        server.shutdown()


if __name__ == "__main__":
    main()
