# Local Google Drive sync

Sync discovers read-only Drive metadata and updates the local inventory/cursor. It does not download document
content, create embeddings or call a chat model; those are later preparation stages. A real Google sync still
requires explicit operator authorization and a valid owner-bound connection. Integration tests use synthetic providers.

## Availability and safe retry

Normal-mode `GET /api/v1/index/status` returns `connected`, `job` and `sync_available`.
`connected` reports the stored connection, not proof that Google will accept its next use. `sync_available: false`
means the supervisor is not healthy or admission is not ready; true is advisory, not a guarantee of admission.
Older/unknown responses may omit the field or contain null. Demo status does not report this normal-mode capability.

The Library offers **Check sync status** while unavailable, blocked or uncertain. This is a read. A definite
pre-admission refusal releases the matching pending marker; the person can check and retry explicitly. Unknown
responses, timeouts and unrecognised 5xx responses retain the marker. Neither refresh nor tab return resubmits it.
A stored job id is polled by identity; latest-job status alone cannot resolve a missing acknowledgement.

## Enabling the normal worker

The default is `INDEXING_ENABLED=false`. Follow [normal indexing runtime](v2-normal-indexing-runtime.md)
and [private-beta deployment](RAILWAY_PRIVATE_BETA.md), including the activation fingerprint and recovery gates.
Verified prerequisites in source include normal mode, `DEBUG=false`, a nonempty OpenAI key, the expected database
migration head, and an existing compatible concrete Qdrant collection. Startup does not provision the collection.
It checks vector dimension, distance and owner/file payload indexes. Sync itself does not spend the model key.

Application sign-in also needs its configured Google client, session settings, credential-encryption configuration
and a nonempty sign-in allow-list. Do not print or commit their values. With `DEBUG=false`, the trusted frontend
origin must use HTTPS, and the Google callback must match the same-origin `/api/v1/auth/session/google/callback`.
Use a locally trusted certificate when testing that actual configuration. Do not weaken production validation to
make a local test pass, and do not change an existing OAuth client without authorization.

## Migration ordering

Apply and verify `20261125_1200` before starting the backend that maps `indexing_jobs.failure_class`.
Use [deployment ordering and rollback instructions](DEPLOYMENT.md#migration-before-the-new-backend-starts-required).
The availability flag adds no database column. Never point test migrations at an existing user database.
