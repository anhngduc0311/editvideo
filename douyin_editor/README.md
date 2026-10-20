# EditVideo Studio

Dịch và lồng tiếng video YouTube/Douyin: Trung hoặc Anh → Việt hoặc Nhật.

## Cài đặt trên Windows

### Dùng trên máy khác bằng một file EXE

Sau khi build, chỉ cần chép `dist/EditVideoStudio-Setup.exe` sang máy Windows
10/11 64-bit rồi mở file. Bộ cài tự cài vào tài khoản hiện tại, tạo shortcut
Desktop và Start Menu, rồi tự mở **EditVideo Studio** khi cài xong.
Máy nhận không cần cài Python, pip hoặc FFmpeg.
Có thể cài không hiện trình hướng dẫn bằng
`EditVideoStudio-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`.

Bản build kèm FFmpeg/ffprobe, Node.js cho YouTube, Whisper `small`, model tách giọng mặc định và
model giọng Nhật OpenVoice hiện có. Tải video, dịch và TTS trực tuyến vẫn cần
Internet và thông tin đăng nhập của người dùng. Model Whisper khác được tải
khi chọn sử dụng. Cấu hình/cookie/API key cá nhân không được đưa vào bộ cài.

Ứng dụng được cài trong `%LOCALAPPDATA%/Programs/EditVideoStudio`.
Video xuất nằm trong `%LOCALAPPDATA%/EditVideoStudio/output`; dùng nút mở thư mục
trong ứng dụng để truy cập. Cache/download/log cũng nằm trong thư mục dữ liệu
`%LOCALAPPDATA%/EditVideoStudio`, được giữ lại khi gỡ cài đặt.

### Tạo bộ cài trên máy phát triển

Cài `requirements.txt`, sau đó `py -3 -m pip install pyinstaller==6.22.3`.
Cài Node.js 22+ và [Inno Setup](https://jrsoftware.org/isdl.php) rồi chạy từ `douyin_editor`:

```bat
build_windows.bat --iscc "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

Build yêu cầu đủ tài nguyên `tts/vendor/OpenVoice`, `tts/models/openvoice_v2`,
ba file MP3 mẫu trong `tts`, model tách giọng trong `douyin_editor/models` và
Whisper `small.pt` trong `%USERPROFILE%/.cache/whisper`. Script báo lỗi nếu thiếu.
Build tự kiểm tra EXE: mở/đóng giao diện, chạy FFmpeg/ffprobe và nạp model OpenVoice
trước khi tạo bộ cài. Dùng `--app-only` nếu chỉ muốn thư mục ứng dụng portable;
khi đó phải chép toàn bộ `dist/EditVideoStudio`, gồm cả `_internal`.

`packaging/verify_installer_flow.py` kiểm tra bước tự cài với payload nhỏ và
Inno Setup tại `build/tools/InnoSetup/ISCC.exe`; script chạy bộ cài ở chế độ
thường, xác nhận cài xong mà không cần bấm Install.

Nên thử bộ cài trên máy Windows sạch trước khi phát hành rộng rãi.

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

## Hàng đợi nhiều video

Tải YouTube dùng các phần HTTP nhỏ, tự thử lại khi kết nối bị ngắt và giữ file `.part`
để tải tiếp. Nếu vẫn lỗi, ứng dụng lấy lại đường tải tối đa 3 lượt; lượt cuối tải lại
phần chưa hoàn tất từ đầu. Chỉ yêu cầu cookie khi thông báo cho thấy video cần đăng nhập.

Dán nhiều link vào ô nguồn, mỗi dòng một link, rồi bấm **Bắt đầu xử lý**.
Ứng dụng chạy lần lượt theo thứ tự đã dán, bỏ qua link trùng hoàn toàn và hiển thị
video đang chạy cùng tiến độ toàn hàng đợi. Mọi video dùng bộ cài đặt lúc bấm chạy.
Một video lỗi sẽ được ghi vào nhật ký rồi chuyển sang link tiếp theo; chỉ hiện bảng
tổng kết một lần khi hết hàng đợi. Nút phát mở video thành công gần nhất.

Để chạy tự động hoàn toàn, tắt **chỉnh vùng trực quan** trước khi bắt đầu;
nếu bật thì mỗi video vẫn chờ chọn vùng mờ/phụ đề. **Hủy** dừng video hiện tại
và không bắt đầu link tiếp theo. Dữ liệu đã hoàn tất được giữ lại; chạy lại cùng
danh sách với tùy chọn **Tiếp tục các bước đã hoàn tất** để dùng lại kết quả.

## Dịch bằng ChatGPT Web

ChatGPT Web tự chia phụ đề để mỗi lượt gửi tối đa **5.000 từ**, tính cả yêu cầu dịch
và bối cảnh (đếm theo khoảng trắng, không phải token). Video dài được dịch qua nhiều lượt;
giữ nguyên index và thời gian phụ đề. Bối cảnh được rút gọn khi cần, không cắt nội dung
các câu cần dịch. Nếu một câu hoặc yêu cầu tùy chỉnh quá dài, ứng dụng báo để rút gọn.
Bản dịch được yêu cầu tự nhiên, cuốn hút, có nhịp kể giữ chân người xem, đúng ý gốc,
không bịa tình tiết hoặc thêm lời câu tương tác. Có thể đặt `chatgpt_batch_size` lớn hơn 0
trong cấu hình Python để giới hạn thêm số câu mỗi đoạn; mặc định là 0 (tự chia theo số từ).

## Duyệt, hủy và tiếp tục

- **Tự động tạo giọng sau khi dịch**: giao diện chuyển thẳng sang tạo giọng,
  không mở bảng duyệt bản dịch, kể cả khi cấu hình cũ đã bật duyệt.
- **Hủy**: dừng render và ngừng bắt đầu thao tác mới. Request mạng hoặc mô hình đang chạy
  có thể phải kết thúc/timeout trước khi hủy hoàn toàn. Không khởi động tác vụ khác trong lúc chờ.
- **Tiếp tục các bước đã hoàn tất**: bật mặc định. Chạy lại cùng video sẽ dùng lại dữ liệu
  hợp lệ. Thay ngôn ngữ, giọng, bản dịch hoặc cấu hình render sẽ làm lại phần liên quan.
  Bỏ chọn để chạy lại các bước; cache audio từng câu vẫn được dùng nếu nội dung/giọng không đổi.
- TTS thiếu/hỏng audio được thử lại riêng từng câu. Sau khi hết lượt thử, tác vụ báo lỗi
  và giữ các audio thành công để lần sau không tạo lại.
  CapCut gửi tuần tự tối đa 8 câu/đoạn và ưu tiên chia trước khi vượt 1.500 ký tự;
  tác vụ bị từ chối sẽ tự chia nhỏ để thử lại. Lỗi đăng nhập hoặc dịch vụ vẫn dừng
  quy trình và giữ các audio đã tạo, không xuất bản lồng tiếng thiếu câu.
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
