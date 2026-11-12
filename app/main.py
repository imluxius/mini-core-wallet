import hashlib
import hmac
import json
import uuid
from decimal import Decimal
from fastapi import FastAPI, Header, HTTPException
import pyodbc

from app.database import get_db_connection
from app.schemas import TransferRequest, WebhookTopupPayload

# Khóa bí mật dùng chung giữa Ngân hàng và Hệ thống Ví
BANK_WEBHOOK_SECRET = "super_secret_fintech_key_2026"

app = FastAPI(
    title="Mini Core-Wallet & Payment Gateway API",
    description="Hệ thống Ví điện tử lõi sử dụng Sổ cái kép (Double-Entry Ledger) & ACID Transaction",
    version="1.0.0"
)

def compute_hmac_signature(payload: WebhookTopupPayload) -> str:
    raw_string = f"event_id={payload.event_id}&owner_id={payload.owner_id}&amount={payload.amount:.2f}"
    return hmac.new(
        BANK_WEBHOOK_SECRET.encode("utf-8"),
        raw_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


# API 1: Xem số dư ví và lịch sử biến động sổ cái
@app.get("/api/v1/wallets/{owner_id}", tags=["Wallets"])
def get_wallet_details(owner_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, owner_id, owner_name, wallet_type, balance, currency, status, version FROM wallets WHERE owner_id = ?",
            (owner_id,)
        )
        wallet = cursor.fetchone()
        if not wallet:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy ví của {owner_id}")

        cursor.execute(
            """
            SELECT TOP 10 id, transaction_id, entry_type, amount, signed_amount, balance_after, created_at
            FROM ledger_entries
            WHERE wallet_id = ?
            ORDER BY created_at DESC
            """,
            (wallet.id,)
        )
        entries = [
            {
                "ledger_id": row.id,
                "transaction_id": str(row.transaction_id),
                "entry_type": row.entry_type,
                "signed_amount": float(row.signed_amount),
                "balance_after": float(row.balance_after),
                "created_at": row.created_at.isoformat()
            }
            for row in cursor.fetchall()
        ]

        return {
            "wallet_id": str(wallet.id),
            "owner_id": wallet.owner_id,
            "owner_name": wallet.owner_name,
            "balance": float(wallet.balance),
            "currency": wallet.currency,
            "status": wallet.status,
            "recent_ledger_entries": entries
        }
    finally:
        conn.close()


# API 2: Chuyển tiền P2P
@app.post("/api/v1/transfers", tags=["Transfers"])
def p2p_transfer(
    req: TransferRequest,
    x_idempotency_key: str = Header(..., description="Mã định danh chống trùng giao dịch, VD: tx_p2p_001")
):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "SELECT id, status, amount, created_at FROM transactions WHERE idempotency_key = ?",
            (x_idempotency_key,)
        )
        existing_tx = cursor.fetchone()
        if existing_tx:
            return {
                "message": "Giao dịch đã được xử lý trước đó (Idempotent)",
                "is_duplicate": True,
                "transaction_id": str(existing_tx.id),
                "status": existing_tx.status,
                "amount": float(existing_tx.amount)
            }

        if req.sender_owner_id == req.receiver_owner_id:
            raise HTTPException(status_code=400, detail="Không thể tự chuyển tiền cho chính mình")

        cursor.execute(
            """
            SELECT id, owner_id, balance, status
            FROM wallets WITH (UPDLOCK, ROWLOCK)
            WHERE owner_id IN (?, ?)
            ORDER BY id ASC
            """,
            (req.sender_owner_id, req.receiver_owner_id)
        )
        locked_wallets = {row.owner_id: row for row in cursor.fetchall()}

        sender = locked_wallets.get(req.sender_owner_id)
        receiver = locked_wallets.get(req.receiver_owner_id)

        if not sender or not receiver:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Ví gửi hoặc ví nhận không tồn tại")

        if sender.status != "ACTIVE" or receiver.status != "ACTIVE":
            conn.rollback()
            raise HTTPException(status_code=400, detail="Một trong hai ví đang bị khóa")

        if Decimal(str(sender.balance)) < req.amount:
            conn.rollback()
            raise HTTPException(status_code=400, detail="Số dư ví không đủ để thực hiện giao dịch")

        tx_id = str(uuid.uuid4())
        sender_new_balance = Decimal(str(sender.balance)) - req.amount
        receiver_new_balance = Decimal(str(receiver.balance)) + req.amount

        cursor.execute(
            """
            INSERT INTO transactions (id, idempotency_key, tx_type, amount, sender_wallet_id, receiver_wallet_id, status, description)
            VALUES (?, ?, 'P2P_TRANSFER', ?, ?, ?, 'COMPLETED', ?)
            """,
            (tx_id, x_idempotency_key, req.amount, sender.id, receiver.id, req.description)
        )

        cursor.execute(
            """
            INSERT INTO ledger_entries (transaction_id, wallet_id, entry_type, amount, signed_amount, balance_after)
            VALUES (?, ?, 'DEBIT', ?, ?, ?),
                   (?, ?, 'CREDIT', ?, ?, ?)
            """,
            (
                tx_id, sender.id, req.amount, -req.amount, sender_new_balance,
                tx_id, receiver.id, req.amount, req.amount, receiver_new_balance
            )
        )

        cursor.execute(
            "UPDATE wallets SET balance = ?, version = version + 1, updated_at = SYSDATETIMEOFFSET() WHERE id = ?",
            (sender_new_balance, sender.id)
        )
        cursor.execute(
            "UPDATE wallets SET balance = ?, version = version + 1, updated_at = SYSDATETIMEOFFSET() WHERE id = ?",
            (receiver_new_balance, receiver.id)
        )

        conn.commit()

        return {
            "message": "Chuyển tiền thành công",
            "is_duplicate": False,
            "transaction_id": tx_id,
            "sender": req.sender_owner_id,
            "receiver": req.receiver_owner_id,
            "amount": float(req.amount),
            "sender_new_balance": float(sender_new_balance)
        }

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Lỗi hệ thống: {str(e)}")
    finally:
        conn.close()


# API 3: Cổng nhận thông báo nạp tiền từ Ngân hàng (Webhook Payment Gateway)
@app.post("/api/v1/webhooks/bank-topup", tags=["Webhooks"])
def receive_bank_webhook(
    payload: WebhookTopupPayload,
    x_webhook_signature: str = Header(..., description="Chữ ký bảo mật HMAC-SHA256 từ Ngân hàng")
):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        expected_signature = compute_hmac_signature(payload)
        # Dùng compare_digest để chống tấn công dò thời gian (Timing Attack)
        is_valid_sig = hmac.compare_digest(expected_signature, x_webhook_signature)
        raw_json = json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)

        # 1. Luôn lưu vết gói tin vào WEBHOOK_LOGS trước (Audit Log bất kể đúng hay sai)
        cursor.execute(
            """
            INSERT INTO webhook_logs (provider, event_id, payload, hmac_signature, is_verified, process_status)
            OUTPUT INSERTED.id
            VALUES ('VIETQR_BANK', ?, ?, ?, ?, ?)
            """,
            (
                payload.event_id,
                raw_json,
                x_webhook_signature,
                1 if is_valid_sig else 0,
                "VERIFIED" if is_valid_sig else "REJECTED_INVALID_SIGNATURE"
            )
        )
        log_id = cursor.fetchone()[0]

        if not is_valid_sig:
            conn.commit()
            raise HTTPException(status_code=401, detail="Chữ ký HMAC-SHA256 không hợp lệ! Từ chối giao dịch.")

        # 2. Kiểm tra Idempotency dựa trên event_id của Ngân hàng
        cursor.execute(
            "SELECT id, status, amount FROM transactions WHERE idempotency_key = ?",
            (payload.event_id,)
        )
        existing_tx = cursor.fetchone()
        if existing_tx:
            conn.commit()
            return {
                "message": "Webhook này đã được ghi nhận trước đó (Idempotent)",
                "webhook_log_id": log_id,
                "transaction_id": str(existing_tx.id),
                "amount": float(existing_tx.amount)
            }

        # 3. Khóa ví tổng SYS_ESCROW_01 và ví người nhận để hạch toán Sổ cái kép
        cursor.execute(
            """
            SELECT id, owner_id, balance, status
            FROM wallets WITH (UPDLOCK, ROWLOCK)
            WHERE owner_id IN ('SYS_ESCROW_01', ?)
            ORDER BY id ASC
            """,
            (payload.owner_id,)
        )
        locked_wallets = {row.owner_id: row for row in cursor.fetchall()}

        escrow_wallet = locked_wallets.get("SYS_ESCROW_01")
        user_wallet = locked_wallets.get(payload.owner_id)

        if not user_wallet:
            conn.rollback()
            raise HTTPException(status_code=404, detail=f"Không tìm thấy ví người nhận {payload.owner_id}")

        tx_id = str(uuid.uuid4())
        escrow_new_balance = Decimal(str(escrow_wallet.balance)) - payload.amount
        user_new_balance = Decimal(str(user_wallet.balance)) + payload.amount

        cursor.execute(
            """
            INSERT INTO transactions (id, idempotency_key, tx_type, amount, sender_wallet_id, receiver_wallet_id, status, description)
            VALUES (?, ?, 'TOPUP', ?, ?, ?, 'COMPLETED', ?)
            """,
            (tx_id, payload.event_id, payload.amount, escrow_wallet.id, user_wallet.id, payload.description)
        )

        cursor.execute(
            """
            INSERT INTO ledger_entries (transaction_id, wallet_id, entry_type, amount, signed_amount, balance_after)
            VALUES (?, ?, 'DEBIT', ?, ?, ?),
                   (?, ?, 'CREDIT', ?, ?, ?)
            """,
            (
                tx_id, escrow_wallet.id, payload.amount, -payload.amount, escrow_new_balance,
                tx_id, user_wallet.id, payload.amount, payload.amount, user_new_balance
            )
        )

        cursor.execute(
            "UPDATE wallets SET balance = ?, version = version + 1, updated_at = SYSDATETIMEOFFSET() WHERE id = ?",
            (escrow_new_balance, escrow_wallet.id)
        )
        cursor.execute(
            "UPDATE wallets SET balance = ?, version = version + 1, updated_at = SYSDATETIMEOFFSET() WHERE id = ?",
            (user_new_balance, user_wallet.id)
        )

        conn.commit()

        return {
            "message": "Nạp tiền qua Webhook thành công",
            "webhook_log_id": log_id,
            "transaction_id": tx_id,
            "owner_id": payload.owner_id,
            "amount": float(payload.amount),
            "new_balance": float(user_new_balance)
        }

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Lỗi xử lý Webhook: {str(e)}")
    finally:
        conn.close()


# API Phụ trợ (Dev Helper): Tạo chữ ký HMAC-SHA256 hợp lệ để test Swagger UI
@app.post("/api/v1/dev/generate-signature", tags=["Dev Helper"])
def generate_test_signature(payload: WebhookTopupPayload):
    return {
        "x_webhook_signature": compute_hmac_signature(payload),
        "note": "Copy chuỗi này dán vào ô x-webhook-signature ở API /api/v1/webhooks/bank-topup"
    }