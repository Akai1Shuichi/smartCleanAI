# SmartCleanAI

Ứng dụng PyQt6 trên Windows để quét ổ C, chọn thư mục cần dọn và chuyển dữ liệu sang kho khôi phục trên ổ D. Các thao tác quét, chuyển và khôi phục chạy cục bộ theo quy tắc trong `cleaner.py`.

## Mở ứng dụng

Nhấp đúp **Run SmartCleanAI.bat**. Từ PowerShell trong thư mục dự án, có thể chạy:

```powershell
.\.venv\Scripts\python.exe app.py
```

Nếu cần tạo lại môi trường:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Cách dùng

1. **Dọn dẹp**: chọn ổ đĩa rồi bấm **✨ Quét ổ … bằng AI**. App quét trên máy, sau đó AI xem danh sách và chọn sẵn các mục nên dọn. Cột **AI** hiện mức rủi ro; rê chuột hoặc bấm vào dòng để xem lý do.
2. Ô **Hỏi AI** nhận câu hỏi hoặc mục tiêu, ví dụ `dọn 5 GB`; AI chọn lại các mục theo mục tiêu đó. Bấm vào dòng (hoặc phím Space) để tự bật/tắt mục.
3. Bấm **Dọn N mục**. Hộp xác nhận ghi rõ từng mục đi đâu:
   - Mục ứng dụng trên ổ C (bản cũ CapCut/Zalo/Postman, cache Chrome/Edge/VS Code/CapCut, bộ cài sót) được sao chép sang kho trên ổ D, kiểm tra từng tệp rồi mới gỡ khỏi C.
   - Thư mục dự án lập trình (`node_modules`, `.next`, `.nuxt`, `.turbo`, `.parcel-cache`, `.angular`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`) trên mọi ổ được chuyển vào Thùng rác. App chỉ nhận thư mục nằm trong dự án thật (có `package.json` kèm lock file hoặc `.git`) và bỏ qua thư mục hệ thống, `AppData`, môi trường ảo. Dọn sạch Thùng rác để lấy lại dung lượng.
4. **Khôi phục** đưa mục trong kho về chỗ cũ (chọn được nhiều mục). Thư mục dự án thì khôi phục từ Thùng rác.

Nếu AI chưa sẵn sàng, app dùng gợi ý offline theo quy tắc trên máy (ghi "Offline" ở khung AI).

Quét chỉ đọc từ PowerShell:

```powershell
.\.venv\Scripts\python.exe app.py --scan
```

## Cài đặt AI

Mục **Cài đặt** chọn một trong ba nguồn AI, giống Editor-AI-App:

- **Codex CLI**: cần `npm i -g @openai/codex` và `codex login`. Chạy ở chế độ chỉ đọc, trong thư mục tạm trống.
- **Antigravity CLI (agy)**: cần cài `agy` và chạy `agy` một lần để đăng nhập. App dừng phiên nếu agent định dùng công cụ không chỉ đọc.
- **API (Base URL + API key)**: API kiểu OpenAI, nhập Base URL (thường kết thúc bằng `/v1`), API key và model. **Tải danh sách** đọc model từ `/models`.

**Kiểm tra kết nối** không tốn lượt gọi model. Cài đặt lưu ở `%APPDATA%\SmartCleanAI\settings.json` (API key lưu dạng văn bản trên máy). **Dữ liệu gửi** cho xem chính xác những gì gửi cho AI: loại mục, dung lượng, số ngày dự án không đụng tới, không có đường dẫn hay tên tệp thật.
