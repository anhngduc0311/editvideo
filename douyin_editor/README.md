# EditVideo Studio

Dịch và lồng tiếng video YouTube/Douyin: Trung hoặc Anh → Việt hoặc Nhật.

## Cài đặt trên Windows

Môi trường kiểm tra thay đổi này: Python 3.13, CustomTkinter 6.0.0.
Chạy `setup.bat` để tạo môi trường `.venv`, cài `requirements.txt` và kiểm tra runtime.
Sau đó mở `run_gui.bat`; launcher ưu tiên Python trong `.venv`, rồi Python Launcher `py`.
Lần chạy đầu có thể cần tải FFmpeg/model. Giọng Nhật clone cần thêm tài nguyên trong
[hướng dẫn giọng Nhật](../tts/README_JAPANESE.md).

Hoặc chạy trong PowerShell từ thư mục `douyin_editor`:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe verify_setup.py
.\.venv\Scripts\python.exe app_gui.py
```

## Thông tin đăng nhập

Không có API key mặc định. Nhập key trong GUI hoặc đặt biến môi trường trước khi mở ứng dụng:

```powershell
$env:DEEPSEEK_API_KEY = "YOUR_KEY"
```

Key/cookie lưu từ GUI được mã hóa bằng Windows DPAPI, gắn với tài khoản Windows hiện tại.
Các trường bí mật trong cấu hình JSON cũ được chuyển sang dạng mã hóa ở lần lưu kế tiếp.
Biến môi trường được ưu tiên khi mở ứng dụng. Trên hệ điều hành khác, thông tin đăng nhập
chỉ giữ trong phiên/biến môi trường, không ghi dạng rõ vào JSON mới.
Không sao chép file cấu hình sang máy khác để chia sẻ thông tin đăng nhập.

Nếu API key cũ đã xuất hiện trong lịch sử Git, xóa khỏi mã nguồn không thu hồi key đó.
Chủ tài khoản cần thu hồi/thay key trên trang quản lý của nhà cung cấp.

## Duyệt, hủy và tiếp tục

- **Duyệt bản dịch trước khi tạo giọng**: bật mặc định. Sửa lời dịch ở cột bên phải,
  giữ nguyên số câu và mốc thời gian, rồi chọn **Lưu & tạo giọng**.
- **Hủy**: dừng render và ngừng bắt đầu thao tác mới. Request mạng hoặc mô hình đang chạy
  có thể phải kết thúc/timeout trước khi hủy hoàn toàn. Không khởi động tác vụ khác trong lúc chờ.
- **Tiếp tục các bước đã hoàn tất**: bật mặc định. Chạy lại cùng video sẽ dùng lại dữ liệu
  hợp lệ. Thay ngôn ngữ, giọng, bản dịch hoặc cấu hình render sẽ làm lại phần liên quan.
  Bỏ chọn để chạy lại các bước; cache audio từng câu vẫn được dùng nếu nội dung/giọng không đổi.
- TTS thiếu/hỏng audio được thử lại riêng từng câu. Sau khi hết lượt thử, tác vụ báo lỗi
  và giữ các audio thành công để lần sau không tạo lại.
- Lời đọc chỉ tăng tốc tối đa 1,25 lần. Câu dài hơn khoảng chia ước lượng được căn lại
  theo độ dài audio thực, tận dụng khoảng nghỉ và tránh chồng câu. Phụ đề đi cùng lời đọc;
  thời gian trở về mốc nguồn khi gặp khoảng nghỉ đủ dài. Nếu tổng lời đọc dài hơn video,
  giữ thêm khung hình cuối để không cắt mất lời kết. Có thể rút gọn bản dịch để bám sát cảnh hơn.

Checkpoint và audio từng câu nằm trong `workspace_temp/jobs/`. Xóa thư mục job tương ứng
khi không cần tiếp tục hoặc muốn tạo lại toàn bộ audio. Không sửa file khi tác vụ đang chạy.
Kiểm tra checkpoint dựa trên cấu hình đầu vào, kích thước và thời điểm sửa file đầu ra.

CLI hỗ trợ `--review` để dừng cho sửa file SRT, `--no-resume` để bỏ qua checkpoint:

```powershell
.\.venv\Scripts\python.exe main.py --url "VIDEO_URL" --source-language en --target-language vi --review
```

## Kiểm tra

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe ..\tts\verify_youtube_language_ui.py
```

Bộ kiểm thử mô phỏng nhà cung cấp dịch/TTS, tạo WAV thật và kiểm tra hủy FFmpeg thật;
không cần dùng API trả phí. Chưa thay thế việc kiểm tra chất lượng bản dịch và giọng đọc
trên video thực tế. `verify_setup.py` kiểm tra thư viện được cài và runtime, không kiểm tra
tài khoản API hoặc tải các model clone giọng.
