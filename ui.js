// Every file- or server-supplied string is rendered with textContent, never innerHTML.
const DONE = new Set(["done", "checked", "true", "x", "1"]);
const $ = (id) => document.getElementById(id);
let sheet = null; // {columns, rows: [{url, status, cells}]}
let polling = null;

function say(text, isError = false) {
  $("message").textContent = text;
  $("message").className = isError ? "error" : "";
}

function findColumn(columns, names) {
  return columns.find((c) => names.includes(String(c).trim().toLowerCase()));
}

function loadRows(columns, objects) {
  const urlCol = findColumn(columns, ["ten acc", "tên acc"]);
  if (!urlCol) {
    sheet = null;
    render();
    say("Không thấy cột 'Ten acc' trong file.", true);
    return;
  }
  const statusCol = findColumn(columns, ["status"]);
  const rows = objects.map((cells) => ({
    url: String(cells[urlCol] ?? "").trim(),
    status: statusCol ? String(cells[statusCol] ?? "").trim().toLowerCase() : "",
    cells: Object.fromEntries(columns.map((c) => [c, String(cells[c] ?? "")])),
  })).filter((row) => row.url);
  sheet = { columns, rows };
  say(`Đã nhập ${rows.length} acc.`);
  render(rows.map((row) => (DONE.has(row.status) ? "skipped (done)" : "pending")));
}

$("file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const book = XLSX.read(await file.arrayBuffer());
    const ws = book.Sheets[book.SheetNames[0]];
    const columns = (XLSX.utils.sheet_to_json(ws, { header: 1 })[0] || []).map(String);
    loadRows(columns, XLSX.utils.sheet_to_json(ws, { defval: "" }));
  } catch (error) {
    say(`Không đọc được file: ${error.message}`, true);
  }
});

$("loadSheet").addEventListener("click", async () => {
  say("Đang tải sheet...");
  const data = await api("/api/gsheet", { url: $("gsheet").value.trim() });
  if (data) loadRows(data.columns, data.rows);
});

$("start").addEventListener("click", async () => {
  $("start").disabled = true; // no double submit
  const data = await api("/api/start", {
    browser_method: $("browserMethod").value,
    adspower_id: $("adspower").value.trim(),
    date_from: $("dateFrom").value,
    date_to: $("dateTo").value,
    columns: sheet.columns,
    rows: sheet.rows,
  });
  if (data) {
    say("Đang cào...");
    poll();
  } else {
    $("start").disabled = false;
  }
});

$("browserMethod").addEventListener("change", () => {
  const useAdsPower = $("browserMethod").value === "adspower";
  $("adspowerWrap").hidden = !useAdsPower;
  $("adspower").disabled = !useAdsPower;
});

$("alreadySigned").addEventListener("click", async () => {
  $("alreadySigned").disabled = true;
  const data = await api("/api/already-signed", {});
  if (data) {
    say("Starting crawl...");
  } else {
    $("alreadySigned").disabled = false;
  }
});

async function api(path, body) {
  try {
    const response = await fetch(path, {
      method: body ? "POST" : "GET",
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await response.json();
    if (!response.ok) {
      say(data.error || `Lỗi ${response.status}`, true);
      return null;
    }
    return data;
  } catch (error) {
    say(`Không kết nối được app.py: ${error.message}`, true);
    return null;
  }
}

function statusClass(status) {
  const kind = status.split(/[ :]/)[0];
  return ["done", "warning", "error", "skipped", "running"].includes(kind) ? `s-${kind}` : "";
}

function render(statuses = [], running = false) {
  const table = $("table");
  table.replaceChildren();
  $("start").disabled = !sheet || running;
  $("file").disabled = $("loadSheet").disabled = running;
  $("browserMethod").disabled = running;
  $("adspower").disabled = running || $("browserMethod").value !== "adspower";
  if (!sheet) {
    $("summary").textContent = "Chưa có dữ liệu.";
    return;
  }
  const head = table.createTHead().insertRow();
  for (const name of [...sheet.columns, "Tiến độ"]) {
    const th = document.createElement("th");
    th.textContent = name;
    head.appendChild(th);
  }
  const body = table.createTBody();
  sheet.rows.forEach((row, i) => {
    const tr = body.insertRow();
    for (const name of sheet.columns) tr.insertCell().textContent = row.cells[name] ?? "";
    const status = statuses[i] || "pending";
    const cell = tr.insertCell();
    cell.textContent = status;
    cell.className = `progress ${statusClass(status)}`;
    if (status.startsWith("skipped")) tr.className = "dim";
  });
  const count = (prefix) => statuses.filter((s) => s.startsWith(prefix)).length;
  $("summary").textContent = `${sheet.rows.length} acc · ${count("done")} xong · ${count("warning")} cảnh báo · ` +
    `${count("error")} lỗi · ${count("skipped")} bỏ qua`;
}

async function refresh() {
  const data = await api("/api/status");
  if (!data) return;
  if (data.rows.length && (data.running || !sheet || data.result)) {
    sheet = { columns: data.columns, rows: data.rows };
    render(data.statuses, data.running);
  }
  $("log").textContent = data.log.join("\n");
  $("log").scrollTop = $("log").scrollHeight;
  $("alreadySigned").style.display = data.waiting_for_signin ? "inline" : "none";
  $("alreadySigned").disabled = !data.waiting_for_signin;
  $("download").style.display = data.result ? "inline" : "none";
  if (data.waiting_for_signin) say("Browser is open. Log in if needed, then click Already signed.");
  if (data.error) say(data.error, true);
  if (!data.running && polling) {
    clearInterval(polling);
    polling = null;
    if (!data.error) say("Xong. Bấm 'Tải JSON tổng' để tải kết quả.");
  }
  if (data.running && !polling) poll();
}

function poll() {
  if (!polling) polling = setInterval(refresh, 2000);
  refresh();
}

// Default range: the last 5 days including today (local date of this computer).
const isoDay = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
$("dateTo").value = isoDay(new Date());
$("dateFrom").value = isoDay(new Date(Date.now() - 4 * 86400000));
$("browserMethod").dispatchEvent(new Event("change"));
$("alreadySigned").style.display = "none";

refresh(); // restore an ongoing or finished crawl after a page refresh
