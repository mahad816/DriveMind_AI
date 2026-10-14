# Authorized normal indexing runtime

This implementation does not authorize deployment or activation on existing data.
Default `INDEXING_ENABLED=false` starts no normal executor and leaves admission
closed. Demo mode rejects activation. No HTTP route or app.state runtime override
can select this adapter; the factory captures trusted configuration/test arguments.
The disposable adapter's target/interval validation is unchanged.

For a separately approved long-running normal backend (initially one process):

1. Provision/migrate the intended PostgreSQL database using the existing Alembic
   procedure. Startup checks accepted indexing, encrypted-grant, session and file
   schema capabilities, validated constraints and owner exclusion. It accepts the
   additive conversation migration; no exact revision equality is required.
2. Provision the intended **concrete** Qdrant collection separately. It must have
   unnamed COSINE vectors of the configured embedding dimension, and keyword/UUID
   `user_id` and `drive_file_id` payload indexes. Aliases, missing collections and
   incompatible configurations fail startup. Startup/monitor probes never create,
   repair or clear collections. Existing authenticated BUILD algorithms are retained.
3. Configure explicit `DATABASE_URL`, `QDRANT_URL`, `QDRANT_COLLECTION`,
   `EMBEDDING_MODEL`, and `INDEXING_DATABASE_SCHEMA` (default `public`). The schema
   setting validates the actual search path; it does not change the connection's
   search path. Require `DEBUG=false`, the accepted application-session callback,
   trusted HTTPS frontend origin, Google client configuration, credential keyring
   and active key ID, and a configured embedding API key. Startup makes no Google
   or embedding requests and never logs those values.
4. Compute the nonsecret target binding **offline**, with that intended configuration:

   ```bash
   cd backend
   uv run python -c 'from app.core.config import get_settings; from app.services.indexing_runtime import activation_target; print(activation_target(get_settings()))'
   ```

   Only after separate operational approval set `INDEXING_ACTIVATION_TARGET` to
   that fingerprint and `INDEXING_ENABLED=true`. The binding covers PostgreSQL
   endpoint/database/principal/schema, Qdrant endpoint/concrete collection, model,
   dimension and distance. Credentials are excluded, so key/password rotation is
   not a new destination. Verify dedicated normal/demo storage operationally:
   endpoint binding and reserved demo-name rejection cannot prove data origin,
   DNS integrity, embedding provenance of old vectors or writer quiescence.
5. Run the existing `uvicorn app.main:app` long-running process. Admission opens
   only after read-only validation and successful worker/classifier SQL handshakes.
   `/api/v1/health/indexing` reports `ready/available` separately from ordinary
   app/database health. HTTP 200 alone on this diagnostic does not mean ready.

Periodic dependency checks (default five-second interval; each dependency timeout
five seconds) revalidate schema/target, cooperative maintenance and vector/index
configuration. The complete round has a two-timeout watchdog; health closes before
waiting for cancellation-resistant cleanup. Failures are terminal for this local
executor: admission rejects, no further local work is claimed, durable work is
preserved, and an operator must correct the cause and restart. Requests also probe
Qdrant before owner-lock admission. The accepted synchronous post-lock permit
remains the final authorization boundary; an earlier healthy observation is never
sufficient. An already-authorized durable job may outlive a later failure.

Shutdown closes admission, stops new rounds/claims, drains with heartbeats, then
cancels once and joins stage/admission/dependency SQL cleanup. Credential callbacks
are sealed/drained before engine disposal. Deferred disposal stays application-owned
if cleanup exceeds grace. Forced termination cannot guarantee cleanup: QUEUED work
survives; only expired, fenced attempts are classified on restart. Live jobs on
another instance are untouched. Uncertain BUILD effects retain recovery exclusion;
there is no automatic replay or owner release.

Cooperative maintenance closes this adapter when observed and prevents managed
admission/claims through the existing PostgreSQL barrier. It cannot retract an
issued remote request or stop old/unmanaged writers. Operator recovery still needs
externally enforced collection-wide maintenance and fresh quiescence attestation.
A timeout, lease expiry, process cancellation or inventory scan is not that proof.
Rollback means stop/disable this runtime, drain safely and preserve SQL/manifests and
Qdrant storage; do not clear jobs or recovery flags. Old writers must remain drained.

Frontend preparation already polls the exact admitted job ID and checks terminal
outcomes before proceeding. Refresh observes durable owner job status, but the
multi-stage `prepareKnowledge` promise is in memory: it does not resume its remaining
stage chain automatically. After an unresolved stage finishes/classifies, a user may
explicitly start preparation again; recovery-required owners remain blocked. No
frontend, OAuth, chat, conversation, migration or indexing algorithm is changed here.
