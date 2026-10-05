# Threads views crawler

Cào lượt xem (views) của các bài **có ảnh hoặc video** trong N ngày gần nhất, trên nhiều profile Threads, thông qua một profile **AdsPower** đã đăng nhập Threads. Có giao diện web để nhập danh sách acc từ Excel hoặc Google Sheet.

## Cài một lần

```powershell
py -m pip install -r requirements.txt
```

Không cần `playwright install`: crawler dùng trình duyệt của AdsPower.

Trong AdsPower: bật **Local API** (Settings → Local API), ghi lại địa chỉ (mặc định `http://127.0.0.1:50325`) và **API key**.

## Chạy

```powershell
$env:ADSPOWER_KEY = "api-key-cua-ban"
$env:ADSPOWER_URL = "http://127.0.0.1:50325"   # chỉ cần nếu khác mặc định
py .\app.py
```

Trong UI, chọn **AdsPower profile** để chạy qua AdsPower như trước, hoặc chọn
**Chrome on this PC** để mở Google Chrome trực tiếp trên máy này. Chrome mode
dùng profile riêng trong thư mục `.chrome_threads_profile`; lần đầu có thể cần
đăng nhập Threads trong cửa sổ Chrome vừa mở.

Mở Chrome mode thủ công để cài extension:

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="$PWD\.chrome_threads_profile" --no-first-run
```

Khi bấm **Bắt đầu cào**, app mở browser trước và chờ. Sau khi đã đăng nhập
Threads / kiểm tra extension xong, bấm **Already signed** trong UI để crawler
bắt đầu chạy.

Trình duyệt mở `http://127.0.0.1:8000`:

1. **Nhập danh sách**: chọn file `.xlsx` / `.csv`, hoặc dán link Google Sheet (phải chia sẻ "Bất kỳ ai có đường liên kết đều xem được").
2. Điền **AdsPower profile ID** (cột ID trong AdsPower, ví dụ `k19y5vo6`) và chọn **Từ ngày** – **Đến ngày** (tính cả hai ngày, giờ Việt Nam UTC+7, tối đa 1 năm; mặc định 5 ngày gần nhất). Khoảng ngày càng xa hiện tại thì càng phải cuộn nhiều; acc đăng nhiều có thể chạm giới hạn cuộn → `truncated`.
3. Bấm **Bắt đầu cào**. Cột "Tiến độ" cập nhật trực tiếp; tải lại trang không làm mất tiến độ.
4. Xong thì bấm **Tải JSON tổng**.

Dừng giữa chừng: nhấn `Ctrl+C` ở cửa sổ PowerShell. Crawler đóng tab của nó và đóng AdsPower (nếu chính nó đã mở).

## Định dạng sheet

| Ten acc | Status |
|---|---|
| https://www.threads.com/@ten_tai_khoan | |
| https://www.threads.com/@acc_da_xong | done |

- `Ten acc`: link profile Threads (bắt buộc). Link không phải profile Threads sẽ báo lỗi và bị bỏ qua.
- `Status`: `done`, `checked`, `x`, `1` hoặc ô checkbox được tick → acc đó **bỏ qua**. Các cột khác chỉ để hiển thị.
- Acc trùng nhau chỉ cào một lần.

## Kết quả

- `Data_json/<username>.json`: kết quả từng acc, ghi ngay khi acc đó xong. Acc bị lỗi **không** ghi đè file cũ.
- `Data_json/final_<ngày_giờ>.json`: gộp tất cả acc trong sheet có file kết quả (kể cả acc đánh dấu `done` từ lần trước), chỉ giữ bài trong khoảng ngày đã chọn của lần chạy này, cập nhật sau mỗi acc.

File tổng nhóm theo tên acc, mỗi acc chứa danh sách bài:

```json
{
  "ten_tai_khoan": {
    "account": "https://www.threads.com/@ten_tai_khoan",
    "posts": [
      {
        "link": "https://www.threads.com/@ten_tai_khoan/post/ABC",
        "posted_at": "2026-10-01T05:28:30+00:00",
        "views": 81,
        "caption": "Nội dung bài đăng...",
        "comments": [
          {
            "author": "ten_tai_khoan",
            "link": "https://www.threads.com/@ten_tai_khoan/post/XYZ",
            "text": "For anyone who needs it 👇 #ad",
            "urls": ["https://geni.us/p5xGY"]
          }
        ]
      }
    ]
  }
}
```

- `views`: nếu không hiện, crawler tải lại bài thêm 2 lần; vẫn không có thì để `null` (một số bài Threads không hiển thị lượt xem). Có thể có thêm trường `error` nếu bài lỗi khi mở.
- `caption`: nội dung bài (bỏ nút "Dịch" và số thứ tự "1/2").
- `comments`: chỉ các bình luận/trả lời **có link** (của bất kỳ ai), `urls` là link thật (đã bỏ lớp chuyển hướng `l.threads.com`). Chỉ lấy bình luận hiện sẵn khi mở bài.

**Cào tiếp sau khi bị gián đoạn**: đánh dấu `done` cho các acc đã xong trong sheet rồi chạy lại. File tổng mới vẫn gồm kết quả cũ của các acc đó.

## Ý nghĩa cột "Tiến độ"

- `done N posts`: xong, N bài có ảnh/video trong khoảng ngày.
- `done N posts (truncated)`: chạm giới hạn cuộn (60 lần) trước khi tới mốc ngày, có thể thiếu bài cũ.
- `warning: no views found`: có bài nhưng không đọc được lượt xem.
- `warning: X/N posts failed`: một số bài lỗi khi mở (`views: null`, có trường `error`).
- `error: ...`: lỗi (Threads giới hạn truy cập 429, yêu cầu đăng nhập, profile riêng tư...). Acc tiếp theo vẫn chạy.
- `skipped (done)` / `skipped (duplicate)`: bỏ qua.

## Lưu ý

- Crawler dùng phiên **đăng nhập** của profile AdsPower và chỉ đọc trang, không tương tác (like, follow, bình luận).
- Chỉ lấy bài gốc của chính acc đó (bỏ repost), và chỉ bài có ảnh hoặc video. Bài chỉ có chữ hoặc chỉ có link preview bị bỏ qua.
- Đọc được giao diện Threads tiếng Việt ("lượt xem") và tiếng Anh ("views").
- Server chỉ nghe ở `127.0.0.1`, không truy cập được từ máy khác.
- Kiểm tra nhanh logic: `py .\threads_views_crawler.py` (in `self-check ok`).
