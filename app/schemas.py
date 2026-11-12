from decimal import Decimal
from pydantic import BaseModel, Field

class TransferRequest(BaseModel):
    sender_owner_id: str = Field(..., example="USER_KHOA_01", description="Mã chủ ví gửi")
    receiver_owner_id: str = Field(..., example="USER_DUYEN_02", description="Mã chủ ví nhận")
    amount: Decimal = Field(..., gt=0, decimal_places=2, example=150000.00, description="Số tiền chuyển (> 0)")
    description: str = Field(default="Chuyển tiền P2P", max_length=500, example="Chuyển tiền ăn trưa")

class WebhookTopupPayload(BaseModel):
    event_id: str = Field(..., example="BANK_EVT_20261112_01", description="Mã giao dịch duy nhất phía ngân hàng")
    owner_id: str = Field(..., example="USER_KHOA_01", description="Mã chủ ví được nạp tiền")
    amount: Decimal = Field(..., gt=0, decimal_places=2, example=200000.00, description="Số tiền nạp")
    description: str = Field(default="Nạp tiền qua VietQR", max_length=500, example="Nạp tiền VietQR MB Bank")