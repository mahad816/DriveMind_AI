# Encrypted-only Google credentials — isolated cutover

This feature-branch implementation is not permission to migrate a developer/demo/deployed database or enable multi-user access. No real credentials were read or changed during implementation.

## Storage and activation

`GoogleOAuthToken` has a required identity-bound Fernet envelope, owner FK, unique owner, expiry/scopes metadata, revisions, grant epoch and refresh claim. Access/refresh tokens exist only in transient SDK/payload memory; their database columns and compatibility readers/writers are removed. Metadata remains outside the envelope; PostgreSQL is trusted, and this does not claim protection against arbitrary database writes or replay of whole database backups.

Migration `20261011_1200` exclusively locks the credential table and refuses any existing row before changing schema. It never deletes/backfills credentials. Downgrade also requires an empty credential table and never decrypts into plaintext. Users, indexed data, cursors, histories and evaluation data are unaffected. Old code and the new schema cannot coexist in a rolling deployment.

Activation requires separate approval of the exact environment and any credential-only disposal, stopped/drained old processes and jobs, pending OAuth policy, backups, configured backend keys, migration and fresh browser consent tests. Preserve User identities and all indexed data. Do not reset the database for convenience.

Backend settings `GOOGLE_CREDENTIAL_ENCRYPTION_KEYRING` and `GOOGLE_CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID` supply stable keys; nothing generates them. All workers need the same keyring. Keep old keys while live rows/backups depend on them. Old-key reads and active-key refresh/reconnect writes support rotation. Missing/wrong keys and corrupt records fail closed for Drive operations. Demo requires no Google keys and rejects Google credential operations.

## Refresh state and recovery

The explicit-owner repository never commits. OAuth callers own their grant-write transaction. The coordinator uses fresh short sessions on the original event loop; it does not commit or concurrently use the caller's session. SQL work has a bounded async deadline. No credential lock crosses a Google request.

The existing SDK worker thread performs both refresh and conditional persistence. Cancelling its awaiting HTTP task does not cancel that thread. A supported SDK `refresh_handler`, without a refresh token on the Drive SDK object, routes both initial expiry and HTTP-401 refresh through coordination. Userinfo uses access-only credentials and cannot implicitly refresh an unpersisted OAuth grant.

A committed PREPARED claim must become SUBMITTED before provider I/O. Only an expired PREPARED claim can retire safely: the old holder's submit predicate fails after replacement. A SUBMITTED claim is never stolen. Waiting is bounded. Request transport has connect/read timeouts and permits only one token endpoint attempt, preventing SDK retries with an uncertain token. Read timeouts are not proof that Google did not process a request.

Known pre-send failures release only the owning matching claim. Unknown provider outcomes become RECOVERY_REQUIRED; confirmed invalid_grant becomes REAUTH_REQUIRED. Expiry alone never proves revocation. A valid late result can complete after expiry/recovery only if row, owner, claim, revision and epoch still match. Reconnect bumps revision/epoch and clears the old claim; refresh never creates a missing row. Fresh verified reconnect with a replacement refresh token can repair an unusable grant. An omitted refresh token is preserved only from an active, unclaimed, decryptable same-owner grant.

If the process/loop disappears, an unrecoverable submitted claim requires retry-later/reconnect rather than blind token reuse. There is no cross-process durable store of an uncommitted Google response and no distributed transaction with Google. Indexed data is never deleted as recovery.

## Release boundaries

Existing first-account selection, private API authorization, job actor propagation, shared Drive-ID assumptions and source/retrieval ownership remain separate multi-user release blockers. This change adds no public multi-user activation, disconnect endpoint, frontend/session redesign or deployment changes.

Application diagnostics retain parameter hiding and fixed errors. Historic logs/job errors, proxy OAuth query logging, third-party DEBUG logging and telemetry with captured locals remain operational review items. Never log tokens, complete settings, SDK credentials, headers, token URLs, ciphertext or provider response bodies.
