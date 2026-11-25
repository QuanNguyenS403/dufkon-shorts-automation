# Quy Tắc Vận Hành Tự Động Kênh YouTube Shorts (`Dufkon`)

## 1. Phạm Vi & Khóa Kênh Tuyệt Đối
- Dự án này chỉ phục vụ kênh **Dufkon** (`UCVEH1Fr34ceSw4FY27i656A` / `dufkonltd@gmail.com`) theo [channel_policy.json](file:///d:/Youtube/config/channel_policy.json).
- Không dùng ComfyUI (đã loại bỏ hoàn toàn); pipeline sử dụng **Gemini API + NASA/Wikimedia/Stock + Edge-TTS + FFmpeg**.

## 2. Lệnh Kích Hoạt Khi Người Dùng Online: `"bắt đầu triển khai"`
Mỗi khi người dùng mở máy tính và nhắn **`"bắt đầu triển khai"`** (hoặc biến thể tương đương trong workspace `d:\Youtube`), agent **PHẢI** tự động thực hiện ngay chuỗi tác vụ sau mà không hỏi xác nhận rườm rà:

1. **Đồng bộ Cloud & Local:**
   - Chạy `git pull --rebase origin main` (nếu đã cấu hình remote) để nhận toàn bộ job/lịch sử mà GitHub Actions đã chạy khi máy offline.
   - Kiểm tra trạng thái workflow cloud (`gh workflow list` / `gh run list --limit 3`) và Windows Scheduled Task `DufkonShortsContinuousProducer` (đảm bảo vẫn ở trạng thái `Ready`/`Running`, không bị tắt).
2. **Kiểm tra quỹ dự trữ & Bù lịch ngay:**
   - Chạy `python scripts/continuous_producer.py --target-buffer-days 14 --batch-limit 3` (hoặc kích hoạt thêm `gh workflow run continuous-shorts.yml` nếu cần chạy trên cloud).
   - Hệ thống tự quét `jobs/*` (zero-orphan), tự sản xuất video mới (tối đa 3 video/lượt) nếu số slot hẹn giờ tương lai `< 28` (14 ngày × 2 slot `02:00`, `19:00`), upload hẹn giờ lên YouTube và tự xóa thư mục tạm `clips/`, `build/` sau khi upload thành công.
3. **Lưu & Đồng bộ trạng thái:**
   - Kiểm tra lại [PRODUCTION_LEDGER.json](file:///d:/Youtube/PRODUCTION_LEDGER.json) và [PRODUCTION_SCHEDULE.md](file:///d:/Youtube/PRODUCTION_SCHEDULE.md).
   - Commit và push (`jobs/*/job.json`, `jobs/*/upload_receipt.json`, `PRODUCTION_LEDGER.json`, `PRODUCTION_SCHEDULE.md`, `producer_daemon.log`) lên repo private `QuanNguyenS403/dufkon-shorts-automation`.
4. **Báo cáo ngắn gọn cho người dùng:**
   - Số video `PUBLIC_LIVE`, số video `SCHEDULED_ON_YOUTUBE` (số ngày dự trữ), mốc phát sóng xa nhất, và trạng thái Cloud + Windows Task.
