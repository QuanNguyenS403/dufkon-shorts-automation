# Dufkon YouTube Shorts Automation (`dufkonltd@gmail.com`)

Hệ thống sản xuất và hẹn giờ đăng **YouTube Shorts (9:16)** hoàn toàn tự động 24/7 cho kênh **Dufkon** (`UCVEH1Fr34ceSw4FY27i656A`), sử dụng **Gemini API + NASA/Wikimedia/Stock + Edge-TTS + FFmpeg**.

## Kiến trúc vận hành 24/7 (Cloud + Local Backup)
1. **Cloud 24/7 (GitHub Actions — chạy ngay cả khi máy tính tắt):**
   - Workflow [`.github/workflows/continuous-shorts.yml`](.github/workflows/continuous-shorts.yml) chạy tự động **3 lần/ngày** (`08:00`, `16:00`, `00:00` giờ `+07:00`).
   - Duy trì quỹ dự trữ **14 ngày (28 video hẹn giờ sẵn)** cho 2 khung giờ cố định `02:00` & `19:00` (`+07:00`), tối đa `3` video/lượt để an toàn quota YouTube (`10.000 units/ngày`).
   - Tự đồng bộ `jobs/*/job.json`, `jobs/*/upload_receipt.json`, `PRODUCTION_LEDGER.json`, `PRODUCTION_SCHEDULE.md` về repo private.
2. **Local Backup (Windows Task Scheduler + Antigravity):**
   - Task `DufkonShortsContinuousProducer` (cài qua [install_windows_task.ps1](install_windows_task.ps1)) chạy **ẩn hoàn toàn** (`pythonw.exe`) ngay khi mở máy (`AtLogOn`) và lặp lại mỗi `2 giờ`.
   - Khi mở máy tính và nhắn **`"bắt đầu triển khai"`**, Antigravity tự động đồng bộ repo, kiểm tra quỹ video và tiếp tục quy trình tự động hóa theo [GEMINI.md](GEMINI.md).

## Cấu trúc thư mục tối giản
- `config/channel_policy.json` — Khóa kênh `Dufkon`, khung giờ `02:00` & `19:00`, thông số render & rate limits.
- `scripts/` — Pipeline (`continuous_producer.py`, `generate_job.py`, `fetch_media.py`, `generate_audio.py`, `assemble_short.py`, `schedule_batch.py`, `upload_video.py`, `youtube_auth.py`, `prep_video.py`, `analytics_report.py`).
- `assets/presenters/` — Video presenter nền cho bố cục split/hybrid.
- `jobs/` — Đặc tả `job.json` và biên nhận `upload_receipt.json` (file tạm `clips/`, `build/` tự động dọn sau khi upload).
- `secrets/` & `.env` — Chứng chỉ OAuth và API keys (không bao giờ commit lên Git).
- `PRODUCTION_SCHEDULE.md` & `PRODUCTION_LEDGER.json` — Bảng đối chiếu trạng thái thực tế với YouTube Data API v3.

## Lệnh nhanh thường dùng
```powershell
# Cài lại / cập nhật Windows Task Scheduler chạy ẩn
powershell -ExecutionPolicy Bypass -File .\install_windows_task.ps1

# Đồng bộ sổ cái từ YouTube API (chỉ đọc/cập nhật bảng)
python scripts/schedule_batch.py --sync-only

# Chạy 1 lượt sản xuất & bù lịch ngay
python scripts/continuous_producer.py --target-buffer-days 14 --batch-limit 3

# Xem thống kê kênh & video gần nhất
python scripts/analytics_report.py --max-videos 10
```

## Lưu ý bảo mật & OAuth
- Nếu OAuth Consent Screen trên Google Cloud Console đang ở chế độ **Testing**, `refresh_token` có thể hết hạn sau 7 ngày. Hãy chuyển sang **In production** (hoặc định kỳ chạy lại `python scripts/youtube_auth.py --bind-channel` và cập nhật secret `YOUTUBE_TOKEN_JSON` trên GitHub).
