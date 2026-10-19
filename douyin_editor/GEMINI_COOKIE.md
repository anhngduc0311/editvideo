# Dịch phụ đề bằng Gemini Cookie

Trong tab **Nguồn video**, cuộn xuống **Dịch thuật AI** và chọn **Gemini Cookie**.
Chế độ này dùng phiên đăng nhập Gemini Web của bạn, không dùng API key Google AI Studio.
Các lựa chọn Trung → Việt, Trung → Nhật và Anh → Nhật đều được hỗ trợ.

1. Mở [Gemini](https://gemini.google.com/) và đăng nhập tài khoản của bạn.
2. Nhấn **F12**, mở **Application/Storage → Cookies** và chọn miền Google/Gemini.
3. Sao chép **giá trị** `__Secure-1PSID` vào ô đầu tiên.
4. Nếu có `__Secure-1PSIDTS`, dán giá trị vào ô thứ hai. Có thể để trống nếu tài khoản không có cookie này.
5. Bấm **Kiểm tra kết nối**, rồi chạy xử lý video như bình thường.

Ô đầu cũng nhận chuỗi Cookie header chứa hai cookie trên. Nút hình mắt hiển thị/che cả hai ô.

Ứng dụng chỉ giữ giá trị cookie trong bộ nhớ và không ghi vào JSON cài đặt.
Khi mở lại ứng dụng, nhập lại cookie hoặc cấu hình biến môi trường `GEMINI_1PSID` và `GEMINI_1PSIDTS`.
Thư viện `gemini-webapi` có thể lưu cache phiên trên máy. Cookie là thông tin đăng nhập: không chia sẻ hoặc đưa vào Git.

Để cài các thư viện cần thiết, mở terminal trong thư mục `douyin_editor` và chạy:

```bat
py -m pip install -r requirements.txt
```

Kết nối dùng [gemini-webapi](https://github.com/HanaokaYuzu/Gemini-API), một thư viện không chính thức.
Ứng dụng gửi lần lượt từng nhóm phụ đề, cách nhau ít nhất 4 giây kể từ khi nhận phản hồi trước;
thử lại tối đa một lần với lỗi mạng tạm thời. Khi gặp lỗi xác thực, giới hạn tài khoản hoặc chặn tạm thời,
ứng dụng dừng và hiển thị hướng dẫn. Không có bảo đảm tránh chặn, CAPTCHA hay hạn mức của Gemini.
Phiên web được đóng sau mỗi lần kiểm tra hoặc dịch; không giữ kết nối nền khi công việc đã kết thúc.
