from decimal import Decimal
from pydantic import BaseModel, Field

class TransferRequest(BaseModel):
    sender_owner_id: str = Field(..., example="USER_01", description="Sender wallet owner ID")
    receiver_owner_id: str = Field(..., example="USER_02", description="Receiver wallet owner ID")
    amount: Decimal = Field(..., gt=0, decimal_places=2, example=150000.00, description="Transfer amount (> 0)")
    description: str = Field(default="P2P transfer", max_length=500, example="Lunch split")

class CreateTopupQRRequest(BaseModel):
    owner_id: str = Field(..., example="USER_01", description="Target wallet owner ID")
    amount: Decimal = Field(..., gt=0, decimal_places=2, example=200000.00, description="Top-up amount")
    bank_bin: str = Field(default="970432", example="970432", description="Receiving bank BIN (970432 = VPBank)")
    account_no: str = Field(default="0123456789", example="0123456789", description="Escrow bank account number")
    account_name: str = Field(default="MINI CORE WALLET", example="MINI CORE WALLET", description="Escrow account holder name")

class WebhookTopupPayload(BaseModel):
    event_id: str = Field(..., example="BANK_EVT_20261112_01", description="Bank event ID or top-up order code")
    owner_id: str = Field(..., example="USER_01", description="Credited wallet owner ID")
    amount: Decimal = Field(..., gt=0, decimal_places=2, example=200000.00, description="Top-up amount")
    description: str = Field(default="Top-up via VietQR", max_length=500, example="VietQR bank top-up")

class WithdrawalRequest(BaseModel):
    owner_id: str = Field(..., example="USER_01", description="Source wallet owner ID")
    amount: Decimal = Field(..., gt=0, decimal_places=2, example=100000.00, description="Withdrawal amount")
    bank_name: str = Field(..., example="MBBank", description="Destination bank name")
    bank_account_no: str = Field(..., example="0123456789", description="Destination bank account number")
    bank_account_name: str = Field(..., example="NGUYEN VAN A", description="Destination bank account holder name")