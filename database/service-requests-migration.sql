CREATE TABLE bank_service_requests (
    id VARCHAR2(32 CHAR) PRIMARY KEY,
    user_id VARCHAR2(20 CHAR) NOT NULL REFERENCES bank_users(id),
    account_id NUMBER REFERENCES bank_accounts(id),
    request_type VARCHAR2(24 CHAR) NOT NULL,
    request_value VARCHAR2(500 CHAR),
    status VARCHAR2(20 CHAR) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    CONSTRAINT bank_service_request_type_ck CHECK (
        (request_type IN ('CHANGE_OF_ADDRESS', 'KYC_UPDATE')
            AND account_id IS NULL AND request_value IS NOT NULL)
        OR (request_type = 'CHEQUE_BOOK_REQUEST'
            AND account_id IS NOT NULL AND request_value IS NULL)
    ),
    CONSTRAINT bank_service_request_status_ck CHECK (status = 'UNDER_REVIEW')
);
