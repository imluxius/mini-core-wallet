# Mini Core Wallet

Dự án backend mô phỏng phần lõi xử lý giao dịch và sổ cái của ví điện tử. Mục tiêu chính là thực hành cách ghi nhận dòng tiền theo sổ cái kép, xử lý giao dịch đồng thời (concurrency), chống trùng lặp (idempotency) và kiểm tra chữ ký webhook thay vì làm giao diện người dùng.

Các luồng chính đã triển khai:
- Tạo lệnh nạp tiền và sinh đường dẫn mã VietQR
- Tiếp nhận và xác thực webhook nạp tiền giả lập từ ngân hàng (`HMAC-SHA256`)
- Chuyển tiền P2P giữa hai ví
- Mô phỏng rút tiền từ ví về tài khoản ngân hàng
- Tra cứu số dư ví và 10 bút toán gần nhất

> **Phạm vi dự án:** Đây là dự án thực hành chạy trên máy cá nhân. Phần đăng nhập phân quyền người dùng và kết nối trực tiếp với ngân hàng thật không nằm trong phạm vi hiện tại.

## Cách hệ thống ghi nhận tiền (Double-Entry Ledger)

Mỗi giao dịch hoàn tất sẽ ghi một cặp bút toán đối ứng vào bảng `ledger_entries`:
- `DEBIT`: trừ số dư của ví nguồn (`-amount`)
- `CREDIT`: cộng số dư cho ví đích (`+amount`)

Với mọi giao dịch hợp lệ cũng như trên toàn bộ hệ thống, tổng giá trị có dấu luôn phải cân bằng bằng 0:

```math
\sum_{i=1}^{n} \mathrm{signed\_amount}_i = 0
```

Ví dụ khi chuyển 100.000 VND từ ví `USER_01` sang `USER_02`:

| Ví | Loại bút toán | `signed_amount` |
| --- | --- | ---: |
| `USER_01` | `DEBIT` | -100.000 |
| `USER_02` | `CREDIT` | +100.000 |
| **Tổng** | | **0** |

Số dư hiện tại được lưu trực tiếp ở bảng `wallets` để đọc nhanh, còn toàn bộ lịch sử biến động được ghi tách riêng vào bảng `ledger_entries` để phục vụ đối soát.

## Các cơ chế bảo vệ dữ liệu đã cài đặt

* **Sổ cái bất biến (Append-only Ledger):** Bảng `ledger_entries` có trigger `INSTEAD OF UPDATE, DELETE` chặn mọi thao tác sửa hoặc xóa lịch sử. Nếu cần điều chỉnh sai sót, hệ thống bắt buộc phải tạo bút toán đảo ngược mới.
* **Giao dịch ACID & Khóa dòng chống Race Condition:** Việc tạo bản ghi `transactions`, ghi `ledger_entries` và cập nhật số dư ví nằm trong cùng một database transaction. Khi thực hiện giao dịch, các ví liên quan được khóa bằng `WITH (UPDLOCK, ROWLOCK)` và truy vấn theo thứ tự `ORDER BY id ASC` để tránh xung đột đồng thời và deadlock. Mỗi lần cập nhật số dư đều tăng cột `version`.
* **Chống xử lý trùng lặp (Idempotency):** API chuyển tiền và rút tiền yêu cầu header `x-idempotency-key`; webhook nạp tiền dùng `event_id` kết hợp ràng buộc `UNIQUE` trên `transactions.idempotency_key` để chặn ghi nhận lặp khi người dùng bấm đúp hoặc mạng gửi lại request.
* **Xác thực chữ ký Webhook (HMAC-SHA256):** Webhook nạp tiền được kiểm tra chữ ký bằng `hmac.compare_digest` và lưu toàn bộ payload JSON kèm trạng thái xác thực vào bảng `webhook_logs`.

## Công nghệ sử dụng

* **Backend API:** Python 3, FastAPI, Pydantic, Uvicorn
* **Database:** Microsoft SQL Server 2022 (`pyodbc`, T-SQL)
* **Môi trường & Kiểm thử:** Docker Compose, `threading.Barrier`, `ThreadPoolExecutor`
* **Tài liệu thiết kế:** Draw.io (sơ đồ ERD và luồng chuyển tiền P2P trong thư mục `docs/`)

## Cấu trúc dự án

```text
mini-core-wallet/
├── app/
│   ├── __init__.py
│   ├── database.py          # Kết nối SQL Server và xử lý kiểu DATETIMEOFFSET
│   ├── schemas.py           # Model Pydantic kiểm tra dữ liệu đầu vào
│   └── main.py              # Định nghĩa API và logic xử lý giao dịch ví
├── docs/
│   ├── requirements.md
│   ├── erd_diagram.drawio
│   ├── ERD.png
│   └── erd_diagram-P2P_Transfer_Flow.drawio.png
├── sql/
│   ├── 01_init_schema.sql   # Khởi tạo database, ràng buộc, trigger và ví mẫu
│   └── 02_test_transactions.sql
├── tests/
│   └── test_concurrency.py  # Script bắn 10 luồng đồng thời kiểm tra race condition & đối soát sổ cái
├── docker-compose.yml
└── requirements.txt
```

## Thiết kế cơ sở dữ liệu

Database `core_wallet_db` gồm 4 bảng chính:
1. `wallets`: lưu thông tin chủ ví, loại ví (`USER` hoặc `SYSTEM_ESCROW`), số dư, trạng thái (`ACTIVE`, `FROZEN`, `CLOSED`) và `version`. Ràng buộc `CHECK` đảm bảo ví người dùng không bao giờ bị âm.
2. `transactions`: lưu loại giao dịch (`TOPUP`, `P2P_TRANSFER`, `WITHDRAWAL`, `REFUND`), số tiền, ví gửi/nhận, `idempotency_key` duy nhất và trạng thái (`PENDING`, `COMPLETED`, `FAILED`).
3. `ledger_entries`: lưu từng dòng bút toán `DEBIT`/`CREDIT`, giá trị có dấu `signed_amount` và `balance_after`.
4. `webhook_logs`: lưu payload JSON gốc, chữ ký HMAC, kết quả kiểm tra và trạng thái xử lý webhook.

## Danh sách API

| Phương thức | Endpoint | Mô tả | Kiểm soát |
| --- | --- | --- | --- |
| `GET` | `/api/v1/wallets/{owner_id}` | Xem số dư và 10 bút toán gần nhất | Truy vấn chỉ đọc |
| `POST` | `/api/v1/topups/create-qr` | Tạo lệnh nạp `PENDING` và link ảnh VietQR | `order_code` duy nhất |
| `POST` | `/api/v1/webhooks/bank-topup` | Xác thực webhook ngân hàng và cộng tiền vào ví | `x-webhook-signature`, `event_id` |
| `POST` | `/api/v1/transfers` | Chuyển tiền P2P giữa hai ví | `x-idempotency-key` |
| `POST` | `/api/v1/withdrawals` | Mô phỏng rút tiền về ngân hàng | `x-idempotency-key` |
| `POST` | `/api/v1/dev/generate-signature` | Tạo chữ ký mẫu để test nhanh trên Swagger | Chỉ dùng khi phát triển |

Sau khi chạy server, có thể mở tài liệu Swagger tại `http://127.0.0.1:8000/docs` để thử trực tiếp các API.

## Hướng dẫn chạy trên máy cá nhân

### 1. Khởi chạy SQL Server và tạo bảng

```powershell
git clone https://github.com/imluxius/mini-core-wallet.git
cd mini-core-wallet
docker compose up -d
```

Kết nối tới SQL Server (`localhost,1433`, tài khoản `sa`, mật khẩu `FintechPassword@123` hoặc biến môi trường `MSSQL_SA_PASSWORD`) và chạy file `sql/01_init_schema.sql` để tạo database `core_wallet_db` cùng 3 ví mẫu (`SYS_ESCROW_01`, `USER_01`, `USER_02`).

### 2. Cài đặt thư viện và chạy API

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install --only-binary=:all: -r requirements.txt
uvicorn app.main:app --reload
```

### 3. Kiểm thử luồng nạp tiền & Giao dịch đồng thời

* **Thử luồng Webhook VietQR:** Gọi `POST /api/v1/topups/create-qr` để lấy `order_code`, truyền vào `event_id` ở `POST /api/v1/dev/generate-signature` để lấy chữ ký, sau đó gọi `POST /api/v1/webhooks/bank-topup` kèm header `x-webhook-signature`.
* **Kiểm thử tranh chấp đồng thời:** Khi server đang chạy, chạy lệnh sau:
  ```powershell
  python tests/test_concurrency.py
  ```
  Script dùng `threading.Barrier` để bắn 10 lệnh chuyển tiền cùng lúc và kiểm tra số dư ví gửi không bị âm cũng như tổng `signed_amount` trong `ledger_entries` luôn bằng `0.00`.

## Phạm vi hiện tại

* Chưa có hệ thống đăng nhập và phân quyền người dùng
* Webhook ngân hàng và lệnh rút tiền đều là mô phỏng
* Chỉ có Backend API, chưa xây dựng giao diện frontend
* Cấu hình mặc định phục vụ chạy thử nghiệm qua Docker trên máy cá nhân
