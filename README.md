# Mini Core-Wallet & Payment Gateway API

Hệ thống lõi Ví điện tử (**Core-Wallet**) và Cổng thanh toán tự động (**Payment Gateway**) được thiết kế theo chuẩn kế toán **Sổ cái kép (Double-Entry Bookkeeping)** và giao dịch **ACID**. Dự án mô phỏng khép kín vòng đời luân chuyển dòng tiền trong FinTech: **Khởi tạo mã nạp VietQR (`PENDING`) $\rightarrow$ Xác thực Webhook Ngân hàng (`COMPLETED`) $\rightarrow$ Chuyển tiền nội bộ P2P $\rightarrow$ Rút tiền về tài khoản Ngân hàng (`WITHDRAWAL`)**.

---

## Kiến trúc & Nguyên tắc Toàn vẹn Tài chính

* **Sổ cái kép (Double-Entry Ledger):** Mọi biến động số dư đều bắt buộc sinh ra một cặp bút toán đối ứng `DEBIT` (Ghi nợ / Trừ tiền) và `CREDIT` (Ghi có / Cộng tiền) giữa ví người dùng và ví đối ứng (hoặc ví tổng hệ thống `SYS_ESCROW_01`), đảm bảo tổng đại số toàn hệ thống luôn cân bằng tuyệt đối ($\sum \text{signed\_amount} = 0$).
* **Nhật ký kiểm toán bất biến (Immutable Audit Log):** Sử dụng Database Trigger (`trg_immutable_ledger`) ở tầng SQL Server để chặn đứng mọi lệnh `UPDATE` hoặc `DELETE` trên bảng `ledger_entries`. Mọi sai sót chỉ được phép xử lý bằng bút toán đảo ngược (Reversal).
* **Quản lý vòng đời trạng thái giao dịch (Transaction State Machine):** Hỗ trợ luồng nạp tiền bất đồng bộ từ trạng thái khởi tạo chờ thanh toán (`PENDING`) sang hoàn tất (`COMPLETED`) khi nhận được xác nhận từ ngân hàng.
* **Kiểm soát tranh chấp đồng thời & Chống Deadlock:** Áp dụng khóa mức dòng (`WITH (UPDLOCK, ROWLOCK)`) kết hợp sắp xếp thứ tự khóa theo `id ASC` để loại bỏ tình trạng Race Condition (trừ âm ví khi nhiều giao dịch ập vào cùng lúc) và Deadlock, đi kèm Optimistic Locking (`version`).
* **Chống lặp giao dịch (Idempotency):** Mọi API ghi nhận biến động tiền đều kiểm tra `x-idempotency-key` hoặc `event_id` nhằm ngăn chặn việc trừ tiền hoặc cộng tiền 2 lần khi mạng gián đoạn hoặc ngân hàng gửi lại Webhook.
* **Bảo mật cổng thanh toán (HMAC-SHA256):** Xác thực chữ ký số `x-webhook-signature` từ ngân hàng bằng thuật toán so sánh chống dò thời gian (`hmac.compare_digest`), đồng thời lưu vết toàn bộ gói tin (cả hợp lệ lẫn giả mạo) vào bảng `webhook_logs`.

---

## Công nghệ sử dụng

* **Backend & API:** Python 3, FastAPI, Pydantic, Uvicorn
* **Database & Concurrency:** Microsoft SQL Server 2022 (Docker), T-SQL, `pyodbc`
* **Tích hợp thanh toán:** Chuẩn mã hóa chữ ký số HMAC-SHA256, VietQR Quick Link API
* **Thiết kế & Kiểm thử:** Draw.io (ERD & Flowchart), Python `threading.Barrier` & `ThreadPoolExecutor` (Concurrency QA)

---

## Cấu trúc thư mục

```text
mini-core-wallet/
├── app/
│   ├── __init__.py
│   ├── database.py          # Quản lý kết nối SQL Server & bộ giải mã DATETIMEOFFSET
│   ├── schemas.py           # Pydantic models kiểm tra tính hợp lệ dữ liệu đầu vào
│   └── main.py              # Toàn bộ API Ví, VietQR Topup, Webhook, P2P & Withdrawal
├── docs/
│   └── erd_diagram.drawio   # Sơ đồ thực thể liên kết (ERD) & Lưu đồ thuật toán (Flowchart)
├── sql/
│   └── 01_init_schema.sql   # Script khởi tạo DB, ràng buộc CHECK, Trigger & dữ liệu ví mẫu
├── tests/
│   └── test_concurrency.py  # Script bắn 10 luồng đồng thời kiểm chứng chống âm ví & đối soát sổ cái
├── .gitignore               # Loại trừ môi trường ảo venv và file cache
├── docker-compose.yml       # Cấu hình container Microsoft SQL Server 2022
└── requirements.txt         # Danh sách thư viện Python
```

---

## Thiết kế Cơ sở dữ liệu (`core_wallet_db`)

Hệ thống gồm 4 bảng lõi liên kết chặt chẽ theo chuẩn quan hệ:

1. **`wallets`:** Lưu trữ số dư hiện tại, loại ví (`USER` hoặc `SYSTEM_ESCROW`), trạng thái (`ACTIVE`/`LOCKED`), số phiên bản (`version`) và ràng buộc `CHECK (balance >= 0)` đối với ví người dùng.
2. **`transactions`:** Lưu thông tin tổng quan của từng lệnh giao dịch (`TOPUP`, `P2P_TRANSFER`, `WITHDRAWAL`), khóa chống trùng `idempotency_key` và trạng thái (`PENDING`, `COMPLETED`, `FAILED`).
3. **`ledger_entries`:** Bảng sổ cái kép chi tiết ghi nhận từng biến động tăng/giảm (`DEBIT`/`CREDIT`), số dư sau giao dịch (`balance_after`) và được bảo vệ bởi Trigger cấm sửa/xóa.
4. **`webhook_logs`:** Lưu trữ nguyên bản gói tin JSON (`payload`), chữ ký nhận được (`hmac_signature`) và trạng thái xác thực (`is_verified`) phục vụ truy vết và đối soát với ngân hàng.

---

## Danh sách API chính

| Phương thức | Endpoint                           | Chức năng                                                            | Header / Cơ chế bảo vệ                       |
| :------------- | :--------------------------------- | :--------------------------------------------------------------------- | :----------------------------------------------- |
| `GET`        | `/api/v1/wallets/{owner_id}`     | Tra cứu số dư hiện tại & 10 biến động sổ cái gần nhất      | Truy vấn chỉ đọc                             |
| `POST`       | `/api/v1/topups/create-qr`       | Khởi tạo lệnh nạp tiền (`PENDING`) & sinh link ảnh mã VietQR  | Sinh mã đơn duy nhất `TOPUP_XXXXXXXX`      |
| `POST`       | `/api/v1/webhooks/bank-topup`    | Nhận thông báo nạp tiền từ Ngân hàng & hạch toán cộng tiền | Header `x-webhook-signature` (`HMAC-SHA256`) |
| `POST`       | `/api/v1/transfers`              | Chuyển tiền nội bộ P2P giữa 2 ví người dùng                   | Header `x-idempotency-key`, `UPDLOCK`, ACID  |
| `POST`       | `/api/v1/withdrawals`            | Rút tiền từ ví người dùng về tài khoản Ngân hàng           | Header `x-idempotency-key`, `UPDLOCK`, ACID  |
| `POST`       | `/api/v1/dev/generate-signature` | Công cụ tạo chữ ký `HMAC-SHA256` mẫu phục vụ kiểm thử      | Dev Helper                                       |

---

## Hướng dẫn cài đặt & Chạy cục bộ

### 1. Khởi chạy SQL Server 2022 bằng Docker

```bash
git clone [https://github.com/imluxius/mini-core-wallet.git](https://github.com/imluxius/mini-core-wallet.git)
cd mini-core-wallet
docker compose up -d
```

Mở **SQL Server Management Studio (SSMS)**, kết nối vào `localhost,1433` (Tài khoản: `sa` / Mật khẩu: `FintechPassword@123`) và chạy toàn bộ file `sql/01_init_schema.sql` để tạo database `core_wallet_db` cùng 3 ví mẫu (`SYS_ESCROW_01`, `USER_KHOA_01`, `USER_DUYEN_02`).

### 2. Cài đặt môi trường Python & Khởi động API Server

```bash
python -m venv venv
.\venv\Scripts\activate
pip install --only-binary=:all: -r requirements.txt
uvicorn app.main:app --reload
```

Truy cập giao diện tài liệu tương tác **Swagger UI** tại: `http://127.0.0.1:8000/docs`

---

## Kiểm thử Nghiệp vụ & Chịu tải (QA Testing)

### 1. Kiểm thử vòng đời Nạp tiền VietQR & Bảo mật Webhook

1. Gọi `POST /api/v1/topups/create-qr` để tạo lệnh nạp tiền `PENDING` và mở đường link `qr_image_url` trên trình duyệt để xem mã VietQR thực tế.
2. Gọi `POST /api/v1/dev/generate-signature` với `event_id` trùng với `order_code` vừa tạo để lấy chữ ký `HMAC-SHA256` hợp lệ.
3. Gọi `POST /api/v1/webhooks/bank-topup` kèm `x-webhook-signature`:
   * Nếu truyền sai chữ ký: Hệ thống lưu log từ chối (`is_verified = 0`) và trả về `401 Unauthorized`.
   * Nếu truyền đúng chữ ký: Giao dịch chuyển từ `PENDING` sang `COMPLETED`, số dư ví được cộng tiền và ghi nhận đủ 2 dòng đối ứng trong `ledger_entries`.

### 2. Kiểm thử tranh chấp đồng thời (Concurrency Stress Test)

Giữ server `uvicorn` đang chạy và thực thi script kiểm thử 10 luồng bắn đồng loạt vào cùng một mili-giây:

```bash
python tests/test_concurrency.py
```

Script tự động sử dụng `threading.Barrier` để ép 10 giao dịch rút/chuyển tiền xuất phát cùng lúc và kiểm toán lại Database sau khi chạy xong:

* Đảm bảo số giao dịch thành công không bao giờ vượt quá số dư khả dụng (`balance >= 0`).
* Đảm bảo tổng toàn bộ bảng `ledger_entries` luôn cân bằng bằng `0.00`.
