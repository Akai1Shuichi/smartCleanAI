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

## Quét, dọn và khôi phục

1. **Kết quả quét** hiện dung lượng, đường dẫn và trạng thái từng mục. SmartCleanAI tra Registry và kiểm tra tệp thực thi hiện tại trước khi liệt kê bản cũ CapCut, Zalo và Postman. Danh sách còn có cache Chrome và Edge, gói tải về và báo cáo lỗi VS Code, một số cache CapCut, bộ cập nhật GoLogin và Antigravity.
2. Thoát ứng dụng đang sử dụng mục muốn dọn, chọn **Quét lại**, tích các mục cần chuyển rồi chọn **Chuyển sang ổ D**. Thư mục `quarantine` trong dự án giữ bản sao đã kiểm tra. Dung lượng trong bảng là tổng kích thước tệp, có thể khác lượng trống thực tế.
3. Trong tab **Khôi phục**, chọn một mục để đưa về vị trí gốc. Nếu ứng dụng đã tạo lại thư mục gốc, SmartCleanAI báo trùng để bạn có thể kiểm tra hai bản. Bản sao trên D vẫn được giữ sau khi khôi phục. Có thể mở kho từ giao diện và tự xóa một thư mục hồ sơ khi chắc chắn không còn cần nó.

Nếu một lần dọn bị gián đoạn, mục có trạng thái **Có thể khôi phục** có bản sao đã kiểm tra trên D. Mục **Bản sao chưa hoàn tất** cần kiểm tra dữ liệu gốc trước khi xử lý bản sao dở. Nếu app báo thư mục `.smartcleanai-…` còn trên C, có thể xem đường dẫn trong **Chi tiết**.

Quét chỉ đọc từ PowerShell:

```powershell
.\.venv\Scripts\python.exe app.py --scan
```

## Rà soát bằng Codex

Trong tab **Rà soát Codex**, chọn **Xem dữ liệu gửi** để xem mẫu đường dẫn và số liệu tổng hợp theo nhóm. Chọn **Kiểm tra bằng Codex** để nhận nhận xét và đề xuất cho từng nhóm quy tắc hiện tại, cũng như quy trình dọn cache npm, pip, pnpm, NuGet và thu gọn Ubuntu WSL đã dùng trước đây. Các quy trình lịch sử này chỉ xuất hiện trong báo cáo.

Tính năng này cần kết nối mạng và Codex CLI đã đăng nhập bằng ChatGPT. Có thể kiểm tra bằng `codex login status` và đăng nhập bằng `codex login`. App dùng phiên CLI riêng, ở chế độ chỉ đọc với công cụ shell tắt. Dữ liệu gửi gồm mẫu quy tắc và số liệu tổng hợp, không kèm đường dẫn thật, tên tệp người dùng hoặc nội dung tệp. Kết quả chỉ hiển thị trong báo cáo. Việc dọn vẫn cần bạn chọn từng mục và xác nhận trong app.

[Tài liệu OpenAI về rà soát có cấu trúc qua Codex CLI](https://developers.openai.com/cookbook/examples/codex/build_iterative_repair_loops_with_codex)

## Trợ lý AI

Tab **Trợ lý AI** dùng cùng kết nối Codex CLI để trả lời câu hỏi và lập kế hoạch từ kết quả quét. Có thể hỏi nên dọn gì trước hoặc yêu cầu mục tiêu như **2 GiB**. Bảng bên dưới hiển thị mục đề xuất, dung lượng đo trên máy, lý do và ứng dụng cần thoát.

**Chỉ tích mục sẵn sàng trong kế hoạch** thay lựa chọn hiện tại ở tab quét bằng các mục sẵn sàng do AI đề xuất. Nút này chỉ đánh dấu các mục để bạn xem lại trước khi chuyển. App bỏ kế hoạch khi quét lại để tránh dùng số liệu cũ.

**Xem dữ liệu gửi** hiển thị câu hỏi, tối đa ba lượt gần nhất, mẫu quy tắc và số liệu gắn với mã mục. App tự loại đường dẫn thật và tên tệp khỏi dữ liệu quét gửi đi. Câu hỏi được gửi nguyên văn. Lịch sử của tab được giữ trong bộ nhớ của phiên đang mở.
