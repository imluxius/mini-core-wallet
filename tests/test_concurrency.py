import hashlib
import hmac
import json
import os
import sys
import threading
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

# Thêm thư mục gốc vào sys.path để gọi được module app.database
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.database import get_db_connection

BASE_URL = "http://127.0.0.1:8000"
BANK_SECRET = "super_secret_fintech_key_2026"
SENDER = "USER_KHOA_01"
RECEIVER = "USER_DUYEN_02"
TRANSFER_AMOUNT = 100000.00
NUM_THREADS = 10


def http_request(method: str, path: str, body: dict | None = None, headers: dict | None = None):
    url = f"{BASE_URL}{path}"
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)

    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def ensure_minimum_balance(min_required: float):
    status, data = http_request("GET", f"/api/v1/wallets/{SENDER}")
    if status != 200:
        raise RuntimeError(f"Không lấy được thông tin ví {SENDER}: {data}")

    current_balance = data["balance"]
    if current_balance < min_required:
        topup_amt = 400000.00
        event_id = f"QA_TOPUP_{uuid.uuid4().hex[:10]}"
        raw_sig = f"event_id={event_id}&owner_id={SENDER}&amount={topup_amt:.2f}"
        signature = hmac.new(BANK_SECRET.encode(), raw_sig.encode(), hashlib.sha256).hexdigest()

        t_status, t_data = http_request(
            "POST",
            "/api/v1/webhooks/bank-topup",
            body={
                "event_id": event_id,
                "owner_id": SENDER,
                "amount": topup_amt,
                "description": "Nạp vốn chuẩn bị Concurrency Test"
            },
            headers={"x-webhook-signature": signature}
        )
        if t_status != 200:
            raise RuntimeError(f"Nạp tiền tự động thất bại: {t_data}")
        current_balance = t_data["new_balance"]

    return current_balance


def run_concurrency_stress_test():
    print("=" * 65)
    print("BẮT ĐẦU KIỂM THỬ TRANH CHẤP ĐỒNG THỜI (CONCURRENCY STRESS TEST)")
    print("=" * 65)

    initial_balance = ensure_minimum_balance(400000.00)
    expected_success = min(NUM_THREADS, int(initial_balance // TRANSFER_AMOUNT))
    expected_rejected = NUM_THREADS - expected_success

    print(f"1. Số dư ban đầu của {SENDER}: {initial_balance:,.2f} VND")
    print(f"2. Kịch bản: Bắn đồng loạt {NUM_THREADS} lệnh chuyển {TRANSFER_AMOUNT:,.0f} VND cùng 1 tích tắc")
    print(f"   -> Kỳ vọng: Tối đa {expected_success} lệnh thành công, {expected_rejected} lệnh bị chặn (400)\n")

    # Barrier ép cả 10 luồng đợi nhau rồi cùng xuất phát tại đúng 1 thời điểm
    barrier = threading.Barrier(NUM_THREADS)

    def worker(idx: int):
        idem_key = f"stress_test_{uuid.uuid4().hex[:12]}"
        payload = {
            "sender_owner_id": SENDER,
            "receiver_owner_id": RECEIVER,
            "amount": TRANSFER_AMOUNT,
            "description": f"Stress test concurrent tx #{idx + 1}"
        }
        barrier.wait()
        code, resp = http_request(
            "POST",
            "/api/v1/transfers",
            body=payload,
            headers={"x-idempotency-key": idem_key}
        )
        return idx + 1, code, resp

    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        futures = [executor.submit(worker, i) for i in range(NUM_THREADS)]
        results = [f.result() for f in futures]

    success_count = sum(1 for _, code, _ in results if code == 200)
    rejected_count = sum(1 for _, code, _ in results if code == 400)
    other_errors = [(idx, code, resp) for idx, code, resp in results if code not in (200, 400)]

    for idx, code, resp in sorted(results, key=lambda x: x[0]):
        status_label = "THÀNH CÔNG (200)" if code == 200 else f"BỊ CHẶN ({code})"
        detail = resp.get("message") or resp.get("detail")
        print(f"   [Luồng #{idx:02d}] {status_label} -> {detail}")

    # Kiểm tra lại số dư cuối cùng và đối soát Sổ cái kép trong SQL Server
    _, final_wallet = http_request("GET", f"/api/v1/wallets/{SENDER}")
    final_balance = final_wallet["balance"]

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT ISNULL(SUM(signed_amount), 0) FROM ledger_entries")
    ledger_imbalance = float(cursor.fetchone()[0])
    conn.close()

    print("\n" + "-" * 65)
    print("KẾT QUẢ ĐỐI SOÁT KIỂM TOÁN (AUDIT & RECONCILIATION):")
    print(f" - Giao dịch thành công : {success_count}/{NUM_THREADS} (Kỳ vọng: {expected_success})")
    print(f" - Giao dịch bị chặn    : {rejected_count}/{NUM_THREADS} (Kỳ vọng: {expected_rejected})")
    print(f" - Số dư cuối ví gửi    : {final_balance:,.2f} VND (Không âm)")
    print(f" - Độ lệch Sổ cái kép   : {ledger_imbalance:.2f} VND (Chuẩn kế toán = 0.00)")
    print("-" * 65)

    assert success_count == expected_success, "Sai lệch số lượng giao dịch thành công!"
    assert rejected_count == expected_rejected, "Sai lệch số lượng giao dịch bị chặn!"
    assert final_balance >= 0, "LỖI NGHIÊM TRỌNG: Số dư ví bị âm!"
    assert ledger_imbalance == 0.0, "LỖI NGHIÊM TRỌNG: Sổ cái kép không cân bằng!"
    assert not other_errors, f"Phát sinh lỗi không mong muốn: {other_errors}"

    print("✅ PASS 100%: Hệ thống chống chịu tốt Race Condition & Đảm bảo toàn vẹn Sổ cái!")


if __name__ == "__main__":
    run_concurrency_stress_test()