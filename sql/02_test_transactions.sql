USE core_wallet_db;
GO

-- Part 1: Simulate a 500,000 VND top-up for USER_01 using an ACID transaction and row locks
BEGIN TRAN;

SELECT id, balance 
FROM wallets WITH (UPDLOCK, ROWLOCK)
WHERE id IN ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000002')
ORDER BY id ASC;

INSERT INTO transactions (id, idempotency_key, tx_type, amount, sender_wallet_id, receiver_wallet_id, status, description)
VALUES ('11111111-1111-1111-1111-111111111111', 'topup_req_001', 'TOPUP', 500000.00, 
        '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-000000000002', 'COMPLETED', N'Top-up via VietQR');

INSERT INTO ledger_entries (transaction_id, wallet_id, entry_type, amount, signed_amount, balance_after) VALUES
('11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-000000000001', 'DEBIT', 500000.00, -500000.00, -500000.00),
('11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-000000000002', 'CREDIT', 500000.00, 500000.00, 500000.00);

UPDATE wallets SET balance = balance - 500000.00, version = version + 1, updated_at = SYSDATETIMEOFFSET() WHERE id = '00000000-0000-0000-0000-000000000001';
UPDATE wallets SET balance = balance + 500000.00, version = version + 1, updated_at = SYSDATETIMEOFFSET() WHERE id = '00000000-0000-0000-0000-000000000002';

COMMIT TRAN;
GO

-- Part 2: Inspect balances, ledger entries, and verify total signed_amount = 0
SELECT owner_id, owner_name, balance, version FROM wallets;
SELECT id, entry_type, signed_amount, balance_after FROM ledger_entries;
SELECT SUM(signed_amount) AS system_imbalance FROM ledger_entries;
GO

-- Part 3: Immutability check (attempting to delete a ledger entry should raise an error)
DELETE FROM ledger_entries WHERE id = 1;
GO