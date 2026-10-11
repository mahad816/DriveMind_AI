# Indexing admission cutover (4E1)

Normal indexing reads require a validated application session. Mutations additionally require the existing allowed Origin and session CSRF token. POST inputs never select the owner. File IDs are internal UUIDs and are authorized before admission.

## Execution is deliberately unavailable

`create_app()` initializes `app.state.indexing_admission_ready = False`. There is no environment switch and no HTTP operation to enable it. Authorized mutations return 503, create no jobs, and never dispatch the former response-bound BackgroundTasks. Only disposable integration tests explicitly open this server-owned gate.

4E2 must implement a durable PostgreSQL consumer of managed QUEUED jobs. 4E3 must establish safe claim/recovery/shutdown behavior before production lifecycle wiring opens admission. Do not enable it merely because a consumer process starts. Read/status access remains available while admission is closed. This phase does not execute jobs or activate multi-user operation.

## Acceptance and polling contract

When the readiness boundary is open, POST `/index/sync`, `/index/ingest`, `/index/chunk`, and `/index/build` commit an owner-bound QUEUED job before returning 202:

```json
{"job_id":"server-issued-uuid","status":"queued","message":"Job accepted; poll /index/status with this job_id."}
```

Sync/ingest require that owner's available Google grant; local chunk/build do not. Connection checking performs no Google network request. Admission takes short owner/target row locks and enforces one unresolved job per owner. 409 indicates unresolved work, including a FAILED job requiring recovery. Different owners may submit independently.

GET `/index/status?job_id=<uuid>` returns only the authenticated owner's exact job. Foreign and missing IDs both return 404. Without job_id it returns that owner's latest job. Disconnect does not hide job history. Stored error text is exposed only if it exactly matches a fixed application diagnostic; otherwise it is replaced with a fixed public description; raw historical/provider errors are never serialized. `/index/pending` uses the same authenticated owner. Demo mutations remain 403; its anonymous readiness and pending responses are preserved.

The frontend obtains fresh CSRF material from the existing `/auth/session` endpoint for each submission and polls the accepted job UUID. It does not use browser clocks to identify jobs or cache CSRF tokens across account changes. Existing session-login feature gates are unchanged.

## Additive schema and activation prerequisites

Migration `20261012_1200` follows `20261011_1300`. Historical rows retain their IDs, status, timestamps and errors with NULL operation. They are not managed executable jobs. New fields persist operation, optional file UUID, full-sync choice, future claim/worker IDs, heartbeat/lease, recovery state and nonnegative progress counters.

The partial unique index covers managed QUEUED/RUNNING or recovery-required jobs per owner. Admission also refuses unresolved legacy jobs. Accepted target file IDs are preserved on file deletion: execution must fail a missing target, never reinterpret it as all files.

Before activation, drain all old writers and review unresolved historical jobs through a separately authorized procedure. 4E1 does not migrate existing stores or alter their rows. Downgrade refuses if any managed job exists, avoiding loss of accepted inputs or recovery exclusions. Empty/historical-only downgrade preserves historical records.

No retry, worker, heartbeat, recovery procedure, Google refresh change, Qdrant mutation, or background executor is implemented here.
