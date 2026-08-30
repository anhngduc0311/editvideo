# 🎵 AI Vocal Remover & Instrumental Separator (MDX-Net Turbo & Multi-Threaded)

Công cụ Python chuyên nghiệp sử dụng AI Deep Learning (**UVR MDX-Net**) để **tách bỏ giọng nói (vocals)** và **giữ lại nhạc nền (beat/instrumental)** hoặc ngược lại từ file **Âm thanh** và **Video**, hỗ trợ **Đa Luồng (Multi-Threading)** và **Tăng Tốc Siêu Nhanh (Turbo Mode - Tăng tốc 2-3x)**.

---

## 🌟 Tính Năng Nổi Bật

1. **Tăng Tốc Đột Phá (SciPy PocketFFT & Turbo Mode)**:
   - **Tăng tốc STFT/iSTFT gấp 22 lần**: Sử dụng `scipy.fft` đa luồng viết bằng C/C++ thay cho `numpy.fft`.
   - **Chế độ Siêu Tốc (Turbo Overlap 0%)**: Giảm hơn 50% số lượng chunk cần inference, đạt tốc độ **~2.4x real-time** (tách xong bài 2 phút trong ~49 giây).
   - **Bộ nhớ Zero-Copy Buffer**: Nạp tensor trực tiếp vào mảng liền kề, loại bỏ hoàn toàn chi phí cấp phát bộ nhớ trung gian.
   - **Tự động tối ưu luồng CPU (Auto-tune Threads)**: Cấu hình 8 luồng hiệu năng cao tránh nghẽn context-switch trên CPU đa nhân.

2. **Tăng Tốc Đa Luồng Toàn Diện (Multi-Threading & Multi-Core)**:
   - **Xử lý song song nhiều file (Concurrent Workers)**: Tự động chạy song song nhiều file cùng lúc trên đa nhân CPU (`ThreadPoolExecutor`).
   - **Tối ưu hóa AI ONNX Runtime**: Kích hoạt bộ nhớ đệm arena (`enable_cpu_mem_arena`) và tối ưu hóa đồ thị mức cao nhất (`ORT_ENABLE_ALL`).
   - **Đa luồng FFmpeg**: Nén và xuất audio/video đa luồng (`-threads 0`), rút ngắn đáng kể thời gian xuất file.

3. **Chất Lượng AI Cao Cấp (MDX-Net)**:
   - Sử dụng kiến trúc mạng nơ-ron MDX-Net hiện đại từ dự án *Ultimate Vocal Remover 5*.
   - Khôi phục trọn vẹn dải tần âm thanh nhạc nền (bass sâu, tiếng trống rõ nét, dải cao không bị méo tiếng hay rè).
    
4. **Hỗ Trợ Đa Dạng Định Dạng**:
   - **Audio**: `.mp3`, `.wav`, `.flac`, `.m4a`, `.aac`, `.ogg`, `.wma`, `.opus`
   - **Video**: `.mp4`, `.mkv`, `.avi`, `.mov`, `.webm`, `.flv`

5. **4 Chế Độ Tách Linh Hoạt (Modes)**:
   - **Chỉ lấy Nhạc Nền (Instrumental)**: Tách sạch giọng hát, tạo bản beat Karaoke chuẩn.
   - **Chỉ lấy Giọng Nói (Vocals)**: Tách riêng giọng đọc, giọng hát để làm lồng tiếng, podcast, remix.
   - **Xuất Cả 2 Track (Both)**: Xuất đồng thời 2 file riêng biệt.
   - **Xuất Video Mới (Video Replace)**: Tự động ghép track nhạc nền đã tách vào video gốc, giữ nguyên 100% chất lượng hình ảnh video.

6. **Giao Diện Đồ Họa GUI Hiện Đại (CustomTkinter)**:
   - Phong cách Dark Mode sang trọng, giao diện hoàn toàn bằng tiếng Việt.
   - Bảng điều khiển chọn tốc độ xử lý: **Siêu Tốc (0% Overlap)**, **Rất Nhanh (25% Overlap)**, **Cân Bằng (50% Overlap)**, **Chất Lượng Cao (75% Overlap)**.
   - Chọn nhiều file hoặc chọn cả thư mục để xử lý hàng loạt.
   - Thanh tiến trình thực tế, hiển thị phần trăm (%), nhật ký đa luồng chi tiết.
   - Nút mở nhanh thư mục kết quả chỉ với 1 click.

---

## 🚀 Cách Cài Đặt & Sử Dụng

### 1. Khởi Chạy Nhanh (Giao diện GUI)
- **Cách 1**: Click đúp vào file `run_tool.bat`
- **Cách 2**: Mở terminal và gõ:
  ```bash
  python main.py
  ```

---

### 2. Sử Dụng Qua Dòng Lệnh (CLI)

```bash
# Tách lấy nhạc nền siêu tốc từ file mp3 (Chế độ Turbo mặc định)
python main.py -i baihat.mp3 -o output/ --speed turbo --mode instrumental

# Xử lý hàng loạt thư mục với 2 luồng song song, chế độ fast
python main.py -i D:/ThuMucNhac/ -o D:/KetQua/ -t 2 --speed fast --mode both --format mp3

# Tách nhạc từ video và xuất ra video mới đã xóa tiếng nói
python main.py -i video.mp4 -o output/ --mode video_replace
```

#### Các Tham Số Dòng Lệnh:
- `-i`, `--input`: Đường dẫn file nguồn hoặc thư mục nguồn.
- `-o`, `--output`: Thư mục lưu kết quả (mặc định: `./output`).
- `-s`, `--speed`: Chế độ tốc độ (`turbo`: 0% overlap, `fast`: 25% overlap, `balanced`: 50% overlap, `hq`: 75% overlap).
- `--overlap`: Tỉ lệ gối đầu Overlap (`0.0`, `0.25`, `0.5`, `0.75`).
- `-t`, `--threads`, `--workers`: Số file xử lý song song (mặc định: 2).
- `-B`, `--batch-size`: Kích thước batch cho AI inference (mặc định: `1` cho CPU).
- `--cpu-threads`: Số luồng CPU gán cho mỗi session AI (mặc định: tự động tối ưu hóa).
- `-m`, `--mode`: Chế độ tách (`instrumental`, `vocals`, `both`, `video_replace`).
- `--model`: Mô hình AI (`UVR-MDX-NET-Inst_HQ_3`, `UVR_MDXNET_KIM_Vocal_2`, `UVR-MDX-NET-Voc_FT`).
- `-f`, `--format`: Định dạng audio xuất ra (`mp3`, `wav`, `flac`, `m4a`).
- `-b`, `--bitrate`: Bitrate âm thanh (mặc định: `320k`).

---

## 📁 Cấu Trúc Dự Án

```
tachgiong/
│
├── engine.py              # AI Core Engine (SciPy PocketFFT, Zero-copy Buffers, ONNX Multi-threaded Inference)
├── app_gui.py             # Giao diện đồ họa CustomTkinter (Speed Presets & Multi-thread Controls)
├── cli.py                 # Giao diện dòng lệnh CLI (Turbo Speed Support)
├── main.py                # Điểm khởi chạy chính
├── run_tool.bat           # File click chạy nhanh trên Windows
├── requirements.txt       # Danh sách thư viện Python
├── models/                # Thư mục chứa AI models (.onnx)
└── README.md              # Tài liệu hướng dẫn sử dụng
```
