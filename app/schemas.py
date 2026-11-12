from decimal import Decimal
from pydantic import BaseModel, Field

class TransferRequest(BaseModel):
    sender_owner_id: str = Field(..., example="USER_KHOA_01", description="Mã chủ ví gửi")
    receiver_owner_id: str = Field(..., example="USER_DUYEN_02", description="Mã chủ ví nhận")
    amount: Decimal = Field(..., gt=0, decimal_places=2, example=150000.00, description="Số tiền chuyển (> 0)")
    description: str = Field(default="Chuyển tiền P2P", max_length=500, example="Chuyển tiền ăn trưa")

class CreateTopupQRRequest(BaseModel):
    owner_id: str = Field(..., example="USER_KHOA_01", description="Mã chủ ví muốn nạp tiền")
    amount: Decimal = Field(..., gt=0, decimal_places=2, example=200000.00, description="Số tiền cần nạp")
    bank_bin: str = Field(default="970432", example="970432", description="Mã BIN ngân hàng nhận (970432 = VP Bank)")
    account_no: str = Field(default="0345613726", example="0345613726", description="Số tài khoản ví tổng nhận tiền")
    account_name: str = Field(default="MINI CORE WALLET", example="MINI CORE WALLET", description="Tên chủ tài khoản nhận")

class WebhookTopupPayload(BaseModel):
    event_id: str = Field(..., example="BANK_EVT_20261112_01", description="Mã giao dịch / Mã đơn nạp (order_code)")
    owner_id: str = Field(..., example="USER_KHOA_01", description="Mã chủ ví được nạp tiền")
    amount: Decimal = Field(..., gt=0, decimal_places=2, example=200000.00, description="Số tiền nạp")
    description: str = Field(default="Nạp tiền qua VietQR", max_length=500, example="Nạp tiền VietQR VP Bank")

class WithdrawalRequest(BaseModel):
    owner_id: str = Field(..., example="USER_KHOA_01", description="Mã chủ ví muốn rút tiền")
    amount: Decimal = Field(..., gt=0, decimal_places=2, example=100000.00, description="Số tiền rút về ngân hàng")
    bank_name: str = Field(..., example="MBBank", description="Tên ngân hàng nhận tiền")
    bank_account_no: str = Field(..., example="0123456789", description="Số tài khoản ngân hàng nhận")
    bank_account_name: str = Field(..., example="LE DANG KHOA", description="Tên chủ tài khoản ngân hàng")