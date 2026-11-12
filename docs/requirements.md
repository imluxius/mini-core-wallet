**User Stories**:

- Xem thông tin ví
- Chuyển tiền tới người khác
- Nạp tiền
- Xem lịch sử giao dịch

**Business Rules:**

- Chống chuyển tiền đúp, mạng lag
- Không cho chuyển âm tiền
- Không cho chuyển tiền cho bản thân
- Sổ cái kép
- Không cho phép sửa lsgd kể cả quản trị
- Luật 6 (Giới hạn số tiền hợp lệ)**:** Số tiền nạp hoặc chuyển mỗi lần phải lớn hơn `0đ` (ví dụ tối thiểu `1.000đ`), chặn các trường hợp truyền số âm (`-50.000đ`) để trục lợi cộng ngược tiền.
- Luật 7 (Xác thực thông báo từ Ngân hàng): Khi cổng thanh toán gọi sang báo  *"User A vừa chuyển khoản 200.000đ"* , hệ thống bắt buộc phải kiểm tra chữ ký bảo mật (Signature) và lưu lại toàn bộ gói tin gốc để phòng trường hợp kẻ gian giả mạo thông báo nạp tiền ảo.
