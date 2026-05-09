-- Track email-notification status per share recipient. Sent in the
-- background after ``POST /api/sessions/{id}/share``; failure here is
-- non-fatal (the share still works, recipient just doesn't get an email).

ALTER TABLE chat_share_recipients
    ADD COLUMN IF NOT EXISTS email_sent_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS email_error TEXT;
