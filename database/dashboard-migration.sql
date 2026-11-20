ALTER TABLE bank_accounts ADD (
    card_status VARCHAR2(6) DEFAULT 'ACTIVE' NOT NULL,
    CONSTRAINT bank_accounts_card_status_ck CHECK (
        card_status = 'ACTIVE' OR (card_status = 'FROZEN' AND account_type = 'CREDIT_CARD')
    )
);

ALTER TABLE bank_transactions ADD (transfer_key VARCHAR2(57));

CREATE UNIQUE INDEX bank_txn_transfer_leg_uq
    ON bank_transactions (
        transfer_key,
        CASE WHEN transfer_key IS NOT NULL THEN SIGN(amount) END
    );
