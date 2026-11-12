import uuid
from decimal import Decimal
from fastapi import FastAPI, Header, HTTPException
import pyodbc

from app.database import get_db_connection
from app.schemas import TransferRequest

app = FastAPI(
    title="Mini Core-Wallet & Payment Gateway API",
    description="Hệ thống Ví điện tử lõi sử dụng Sổ cái kép (Double-Entry Ledger) & ACID Transaction",
    version="1.0.0"
)

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


# API 2: Chuyển tiền P2P (Dịch 1-1 từ Flowchart Draw.io)
@app.post("/api/v1/transfers", tags=["Transfers"])
def p2p_transfer(
    req: TransferRequest,
    x_idempotency_key: str = Header(..., description="Mã định danh chống trùng giao dịch, VD: tx_p2p_001")
):
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # [HÌNH THOI 1]: Kiểm tra Idempotency-Key đã tồn tại chưa?
        cursor.execute(
            "SELECT id, status, amount, created_at FROM transactions WHERE idempotency_key = ?",
            (x_idempotency_key,)
        )
        existing_tx = cursor.fetchone()
        if existing_tx:
            # Nhánh YES (Trùng lệnh): Trả về kết quả cũ, KHÔNG trừ tiền lần 2
            return {
                "message": "Giao dịch đã được xử lý trước đó (Idempotent)",
                "is_duplicate": True,
                "transaction_id": str(existing_tx.id),
                "status": existing_tx.status,
                "amount": float(existing_tx.amount)
            }

        # Kiểm tra nhanh điều kiện Ví gửi != Ví nhận
        if req.sender_owner_id == req.receiver_owner_id:
            raise HTTPException(status_code=400, detail="Không thể tự chuyển tiền cho chính mình")

        # [HÌNH CHỮ NHẬT 1]: Bật Transaction & Khóa 2 dòng ví theo thứ tự ID tăng dần (Chống Deadlock)
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

        # [HÌNH THOI 2]: Kiểm tra tồn tại ví, trạng thái ACTIVE và Số dư A >= Tiền chuyển
        if not sender or not receiver:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Ví gửi hoặc ví nhận không tồn tại")

        if sender.status != "ACTIVE" or receiver.status != "ACTIVE":
            conn.rollback()
            raise HTTPException(status_code=400, detail="Một trong hai ví đang bị khóa")

        if Decimal(str(sender.balance)) < req.amount:
            # Nhánh NO (Vi phạm): Hủy giao dịch & Báo lỗi 400
            conn.rollback()
            raise HTTPException(status_code=400, detail="Số dư ví không đủ để thực hiện giao dịch")

        # [HÌNH CHỮ NHẬT 2]: Ghi nhận lệnh & Hạch toán Sổ cái kép
        tx_id = str(uuid.uuid4())
        sender_new_balance = Decimal(str(sender.balance)) - req.amount
        receiver_new_balance = Decimal(str(receiver.balance)) + req.amount

        # 1. INSERT bảng TRANSACTIONS
        cursor.execute(
            """
            INSERT INTO transactions (id, idempotency_key, tx_type, amount, sender_wallet_id, receiver_wallet_id, status, description)
            VALUES (?, ?, 'P2P_TRANSFER', ?, ?, ?, 'COMPLETED', ?)
            """,
            (tx_id, x_idempotency_key, req.amount, sender.id, receiver.id, req.description)
        )

        # 2. INSERT 2 dòng DEBIT / CREDIT vào LEDGER_ENTRIES
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

        # [HÌNH CHỮ NHẬT 3]: Cập nhật số dư mới vào WALLETS & Chốt sổ (COMMIT)
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