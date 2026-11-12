CREATE DATABASE core_wallet_db;
GO

USE core_wallet_db;
GO

-- 1. WALLETS (User wallets and system escrow wallet)
CREATE TABLE wallets (
    id UNIQUEIDENTIFIER PRIMARY KEY DEFAULT NEWID(),
    owner_id VARCHAR(100) NOT NULL UNIQUE,
    owner_name NVARCHAR(255) NOT NULL,
    wallet_type VARCHAR(20) NOT NULL CHECK (wallet_type IN ('USER', 'SYSTEM_ESCROW')),
    balance DECIMAL(18, 2) NOT NULL DEFAULT 0.00,
    currency VARCHAR(3) NOT NULL DEFAULT 'VND',
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'FROZEN', 'CLOSED')),
    version INT NOT NULL DEFAULT 1,
    created_at DATETIMEOFFSET NOT NULL DEFAULT SYSDATETIMEOFFSET(),
    updated_at DATETIMEOFFSET NOT NULL DEFAULT SYSDATETIMEOFFSET(),

    -- Ensure user wallets cannot have negative balances
    CONSTRAINT chk_user_wallet_non_negative 
        CHECK (wallet_type = 'SYSTEM_ESCROW' OR balance >= 0.00)
);
GO

-- 2. TRANSACTIONS (Transaction records and idempotency tracking)
CREATE TABLE transactions (
    id UNIQUEIDENTIFIER PRIMARY KEY DEFAULT NEWID(),
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    tx_type VARCHAR(30) NOT NULL CHECK (tx_type IN ('TOPUP', 'P2P_TRANSFER', 'WITHDRAWAL', 'REFUND')),
    amount DECIMAL(18, 2) NOT NULL CHECK (amount > 0.00),
    currency VARCHAR(3) NOT NULL DEFAULT 'VND',
    sender_wallet_id UNIQUEIDENTIFIER NULL REFERENCES wallets(id),
    receiver_wallet_id UNIQUEIDENTIFIER NULL REFERENCES wallets(id),
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'COMPLETED', 'FAILED')),
    description NVARCHAR(500) NULL,
    metadata NVARCHAR(MAX) NULL CHECK (metadata IS NULL OR ISJSON(metadata) = 1),
    created_at DATETIMEOFFSET NOT NULL DEFAULT SYSDATETIMEOFFSET(),
    updated_at DATETIMEOFFSET NOT NULL DEFAULT SYSDATETIMEOFFSET(),

    CONSTRAINT chk_different_wallets CHECK (sender_wallet_id <> receiver_wallet_id)
);
GO

-- 3. LEDGER_ENTRIES (Double-entry ledger)
CREATE TABLE ledger_entries (
    id BIGINT IDENTITY(1,1) PRIMARY KEY,
    transaction_id UNIQUEIDENTIFIER NOT NULL REFERENCES transactions(id),
    wallet_id UNIQUEIDENTIFIER NOT NULL REFERENCES wallets(id),
    entry_type VARCHAR(10) NOT NULL CHECK (entry_type IN ('DEBIT', 'CREDIT')),
    amount DECIMAL(18, 2) NOT NULL CHECK (amount > 0.00),
    signed_amount DECIMAL(18, 2) NOT NULL,
    balance_after DECIMAL(18, 2) NOT NULL,
    created_at DATETIMEOFFSET NOT NULL DEFAULT SYSDATETIMEOFFSET(),

    CONSTRAINT chk_signed_amount_logic CHECK (
        (entry_type = 'DEBIT' AND signed_amount = -amount) OR
        (entry_type = 'CREDIT' AND signed_amount = amount)
    )
);
GO

-- 4. WEBHOOK_LOGS (Audit trail for incoming bank webhooks)
CREATE TABLE webhook_logs (
    id BIGINT IDENTITY(1,1) PRIMARY KEY,
    provider VARCHAR(50) NOT NULL,
    event_id VARCHAR(128) NOT NULL,
    payload NVARCHAR(MAX) NOT NULL CHECK (ISJSON(payload) = 1),
    hmac_signature VARCHAR(256) NOT NULL,
    is_verified BIT NOT NULL DEFAULT 0,
    process_status VARCHAR(30) NOT NULL DEFAULT 'RECEIVED',
    received_at DATETIMEOFFSET NOT NULL DEFAULT SYSDATETIMEOFFSET()
);
GO

-- 5. Append-only trigger: block UPDATE and DELETE on ledger_entries
CREATE TRIGGER trg_immutable_ledger
ON ledger_entries
INSTEAD OF UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    THROW 50001, N'ledger_entries is append-only; UPDATE and DELETE are not allowed.', 1;
END;
GO

-- 6. Query performance indexes
CREATE INDEX idx_transactions_created_at ON transactions(created_at);
CREATE INDEX idx_ledger_wallet_created ON ledger_entries(wallet_id, created_at DESC);
CREATE INDEX idx_ledger_tx_id ON ledger_entries(transaction_id);
GO

-- 7. Seed sample wallets
INSERT INTO wallets (id, owner_id, owner_name, wallet_type, balance) VALUES
    ('00000000-0000-0000-0000-000000000001', 'SYS_ESCROW_01', N'System Escrow Account', 'SYSTEM_ESCROW', 0.00),
    ('00000000-0000-0000-0000-000000000002', 'USER_01', N'Nguyen Van A', 'USER', 0.00),
    ('00000000-0000-0000-0000-000000000003', 'USER_02', N'Tran Thi B', 'USER', 0.00);
GO