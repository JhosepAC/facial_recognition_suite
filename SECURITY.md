# Security Policy

## Biometric Data

This software processes biometric data (faces), considered sensitive data
under Peru's Law No. 29733 on Personal Data Protection and equivalent
regulations in other countries. Before deploying it on real people:

- Obtain **informed consent** from data subjects.
- Define a **lawful basis for processing**.
- Document the **retention period** for the data.
- Enable the **access and audit controls** already present in the data
  model (`User`, `Role`, `AuditLog`).

## Local Processing

All processing (detection, embeddings, attributes, 1:N search) happens
100% locally. No images or biometric vectors are sent to external services.

## Credentials and Encryption

- There are no default users or passwords; the administrator account is
  created on first launch.
- Passwords are stored with `bcrypt` (cost 12).
- Sensitive configuration is encrypted at rest with Fernet/AES (local key in
  `config/.secret.key`, outside version control).
- If the local key is lost, encrypted values can no longer be recovered.
  Consider backing it up as part of the continuity plan.
- When a person is deleted, their recognition events and video detections
  (and evidence files) are purged explicitly; photos and biometric
  vectors are deleted transactionally (DB before disk).
- The application enforces account lockout on failed attempts and session
  lockout on inactivity.
- "Remember session" uses a random token (only its SHA-256 hash is persisted
  in the `remembered_sessions` table, with expiration); the password is never
  stored on the machine.
- The remembered token is **revoked** when the password is changed or reset
  and when the account is deactivated or deleted. It never bypasses 2FA: if
  the user has two-step verification enabled, startup opens the pre-filled
  login instead of entering directly (the token is preserved and rotated upon
  re-authentication).
- The "remember session" token is persisted on the machine **encrypted** with
  the local Fernet key (not in plaintext) and its reuse via auto-login is
  **audited** (`LOGIN_OK via=remembered_token`), just like a normal login:
  there are no untraced accesses.
- The database uses **WAL journal** (with `busy_timeout` and
  `synchronous=NORMAL`): concurrent writes from background workers and the
  GUI do not produce "database is locked" errors and the file is more resilient
  to interruptions. When restoring a backup, orphaned `-wal`/`-shm` files are
  removed so SQLite does not replay frames from the old file.
- Login error messages are generic: they do not reveal whether the account
  exists, is locked, or is deactivated (prevents user enumeration).
- Login enforces **rate limiting**: each failed attempt (password, 2FA, or
  account registration) waits `security.login_failure_delay_ms` (default
  250 ms) before responding, slowing down brute force. Non-existent, locked,
  and deactivated accounts consume the same verification time as a real hash
  (prevents timing oracle).
- **2FA code failures also count toward account lockout**
  (`lockout_attempts`/`lockout_minutes`): an incorrect TOTP code N times
  locks the account just like an incorrect password.
- The dashboard recognition rate is **broken down by source**
  (webcam/video/image): webcam and video only record matches, so their rate
  is not directly comparable to that of images.

## Reporting a Vulnerability

This is a local/personal project. If you discover a vulnerability:

1. Do not publish or exploit it.
2. Contact the maintainer by email or private issue describing the problem,
   steps to reproduce, and potential impact.
3. A response will be provided as soon as possible. Please do not include real
   biometric data or credentials in the report.

## Limits of Local Mitigation

- Encryption of `secure_settings` protects the database file at rest, but a
  local key is accessible to anyone with access to the machine.
- Biometric embeddings are stored in the SQLite database without encryption. If
  your policy requires full encryption of vectors, apply filesystem-level
  encryption (BitLocker/LUKS) or extend the `security.py` layer.
- Write operations on persons (creation, editing, photos, and deletion)
  revalidate role permissions at the service layer (`person_service`), not
  just in the UI. Deleting a person also requires administrator access. Any
  programmatic integration is subject to the same authorization.
