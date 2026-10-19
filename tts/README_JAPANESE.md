# Giọng nam Nhật

Trong mục Giọng đọc, chọn **🎮 Nam Nhật Minecraft (Clone từ video)** và bấm **Nghe thử**. Khi xuất video, bước dịch sẽ dùng tiếng Nhật và TTS dùng mô hình OpenVoice cục bộ. Bước tạo âm thanh nguồn cần kết nối Internet (Edge TTS).

Giọng, mẫu nghe thử và tài nguyên được sao chép từ D:/edit1/editvideo/tts. Mã OpenVoice kèm giấy phép trong vendor/OpenVoice/LICENSE.

Tài nguyên bắt buộc:
- japanese_youtube_voice_clone.mp3
- vendor/OpenVoice/openvoice/
- models/openvoice_v2/converter/config.json
- models/openvoice_v2/converter/checkpoint.pth
- models/openvoice_v2/source_speaker.pth
- models/openvoice_v2/reference_speaker.pth

Các tài nguyên mô hình và mã vendor hiện được giữ cục bộ; quy tắc .gitignore của project bỏ qua models/, *.pth và vendor/. Khi chuyển project sang máy khác, cần sao chép kèm thư mục models/openvoice_v2 và vendor/OpenVoice. Các thư viện bổ sung nằm ở cuối douyin_editor/requirements.txt.

Kiểm tra: chạy python tts/verify_japanese_voice.py. Thêm --synthesize để kiểm tra sinh giọng thật và đồng bộ phụ đề (cần FFmpeg).

## YouTube và dịch Anh → Nhật

Dán link YouTube thường, youtu.be hoặc Shorts vào ô Link Video. Ở mục Ngôn ngữ dịch, chọn Tiếng Anh → Tiếng Nhật; ứng dụng tự chọn giọng nam Nhật và lưu lựa chọn cho lần sau. Chế độ Trung → Nhật và Trung → Việt vẫn có sẵn. File video tiếng Nhật có hậu tố _ja.mp4.

Dòng lệnh: python douyin_editor/main.py --url <link> --source-language en --target-language ja

Kiểm tra luồng: python -m unittest discover -s douyin_editor/tests -p test_youtube_english_japanese.py
