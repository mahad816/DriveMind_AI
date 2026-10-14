# Railway Hobby: isolated normal-mode beta packaging

This is a preparation/runbook, **not deployment or indexing authorization**.
Leave the existing `drivemind-demo` project untouched. Create no services until
packaging acceptance and separate deployment approval. Use a new project and
environment with four services, one replica each, in the same region:

**Dependency deployment hold:** packaging verification on 2026-10-14 found
pre-existing production dependency advisories in the unchanged lockfile, including
Next.js 15.5.20 (critical image-optimization advisory
[GHSA-2xp9-vwfh-vxw4](https://github.com/advisories/GHSA-2xp9-vwfh-vxw4), custom-server
Server Actions SSRF [GHSA-89xv-2m56-2m9x](https://github.com/advisories/GHSA-89xv-2m56-2m9x))
and proxy-addr/shadcn transitive packages. Audit counts do not establish that every
advisory is reachable here; the Windows-only advisory does not apply to these
Linux images. Nevertheless, **do not expose this beta until dependency remediation
and focused regression acceptance**. No lockfile upgrades are hidden in packaging.

| Service | Source/root | Listener | Persistence / public access |
| --- | --- | --- | --- |
| Frontend | this branch, `/frontend`, `/frontend/railway.toml` | assigned `PORT`, dual-stack | no volume; only public HTTPS service |
| Backend | this branch, `/backend`, `/backend/railway.toml` | `PORT=8000`, IPv4 | no volume; private only; one Uvicorn worker |
| PostgreSQL | official `postgres:16.15-bookworm` image | 5432 | volume `/var/lib/postgresql/data`; no public domain/TCP proxy |
| Qdrant | `qdrant/qdrant:v1.18.0` image | 6333 HTTP | volume `/qdrant/storage`; no public domain/TCP proxy |

Select each application root and config path explicitly in Railway. Dockerfile
paths in the configs refer to the service build root. Review the effective build
settings before approving deployment; no monorepo-root build or automatic demo
deployment. Disable auto-deploy initially. Application base images pin multi-arch
digests; resolve/store storage image digests in the release record too. Deliberate
base/security updates and rebuilt releases must be rechecked. Debian OCR packages
come from signed repositories at build time, so record each resulting image digest
for rollback rather than promising bit-identical future OS packages.
Application dependencies use `npm ci` and `uv sync --frozen`.
Python 3.12 / Node 22 Debian images support ARM64 and AMD64. Runtime users are
non-root. Tesseract is installed; OCR uses ephemeral temporary disk. No downloaded
originals need a persistent application volume. Database and Qdrant volumes do.

## Platform contracts verified from official documentation

- [HTTP limits](https://docs.railway.com/networking/public-networking/specs-and-limits):
  HTTP can run up to 15 minutes with traffic; idle connections close after five
  minutes. The packaged proxy has an absolute 180-second response budget,
  exceeding the backend's 120-second generation budget plus bounded SQL work.
  No streaming heartbeat or detached generation is introduced. Actual edge,
  browser, private DNS and cookie behavior remains a live acceptance gate.
- [Private networking](https://docs.railway.com/networking/private-networking/how-it-works):
  isolated per project/environment; IPv4/IPv6 supported, **runtime only**. Builds
  must not query the database, vector service or other private services.
- [Deployment teardown](https://docs.railway.com/deployments/reference): default
  SIGTERM-to-SIGKILL grace is zero. Set `RAILWAY_DEPLOYMENT_DRAINING_SECONDS=210`
  on both applications and review the effective value. The checked-in application
  configs also pin `drainingSeconds=210`, `overlapSeconds=0` and
  `sleepApplication=false`; verify effective settings, not just variable labels.
  Backend Uvicorn allows
  150 seconds for active HTTP requests; accepted indexing drain/cleanup follow.
  Frontend joins active connections, closes remaining waits after 185 seconds.
  Set a 60-second drain allowance on PostgreSQL/Qdrant too, and stop application
  writers first before stopping either storage service.
  No finite grace proves remote cancellation or guarantees completion of
  cancellation-resistant cleanup. Forced kills retain accepted crash uncertainty.
- [Volumes](https://docs.railway.com/volumes/reference): Hobby defaults to 5 GB
  per volume. Monitor used space, snapshots and metadata headroom; a redeploy must
  reattach the original volume, never initialize an ephemeral replacement.
- [Health checks](https://docs.railway.com/deployments/healthchecks): deployment
  HTTP-200 gates are not ongoing monitoring. Frontend `/_deployment/health` checks
  its process; backend `/api/v1/health/ready` checks DB connectivity. Separately
  inspect `/api/v1/health/indexing` JSON: HTTP 200 does not imply admission ready.

Disable Serverless/auto-sleep on all four services. Do not use cron, multiple
Uvicorn workers, a second executor service, or overlapping unmanaged writers.
Rolling replacements can briefly overlap application processes; accepted DB
claims coordinate them, but this is not operator-recovery quiescence.

## Environment ownership (no real values in this repository)

Copy the sanitized `infra/railway/backend.env.example` and
`infra/railway/frontend.env.example` by service. Enter secrets only in Railway's
service variables/approved secret storage, never Docker build arguments.

| Service | Names / meaning |
| --- | --- |
| Frontend runtime | `PORT`, `BACKEND_URL` (private backend origin), `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` |
| Frontend build | `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_DEMO_MODE`: this normal image fixes `/api/v1` and `false`. Next public variables are compiled at build time; runtime changes cannot change the bundle. No secret is public. |
| Backend | `PORT`, `APP_ENV`, `DEBUG`, `LOG_LEVEL`, `API_PREFIX`, `DEMO_MODE`, `FRONTEND_URL` |
| Backend sessions | `GOOGLE_APPLICATION_SESSIONS_ENABLED`, `GOOGLE_SESSION_REDIRECT_URI`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| Backend Drive | `GOOGLE_DRIVE_SCOPES`; LOGIN uses fixed OpenID/email/profile scopes; CONNECT_DRIVE additionally requests configured read-only Drive scopes |
| Backend encryption | `GOOGLE_CREDENTIAL_ENCRYPTION_KEYRING`, `GOOGLE_CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID`; accepted keyring JSON contract and active key must agree; preserve keys for restoring grants |
| Backend SQL | `DATABASE_URL` in `postgresql+asyncpg` format, private host/5432, percent-encoded credentials; `INDEXING_DATABASE_SCHEMA` |
| Backend vectors | `QDRANT_URL`, `QDRANT_COLLECTION`, `QDRANT_API_KEY` |
| Backend models | `OPENAI_API_KEY`, `EMBEDDING_MODEL`, `CHAT_MODEL`, `QDRANT_UPSERT_BATCH_SIZE` |
| Backend executor | `INDEXING_ENABLED`, `INDEXING_ACTIVATION_TARGET`, `INDEXING_POLL_SECONDS`, `INDEXING_CLASSIFIER_SECONDS`, `INDEXING_DEPENDENCY_SECONDS`, `INDEXING_DEPENDENCY_TIMEOUT`, `INDEXING_STARTUP_TIMEOUT`, `INDEXING_DRAIN_SECONDS`, `INDEXING_CLEANUP_SECONDS` |
| PostgreSQL | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `PGDATA=/var/lib/postgresql/data/pgdata`, `RAILWAY_DEPLOYMENT_DRAINING_SECONDS`; generated private credentials, not committed samples |
| Qdrant | `QDRANT__SERVICE__HOST=0.0.0.0`, `QDRANT__LOG_LEVEL=WARN`, `RAILWAY_DEPLOYMENT_DRAINING_SECONDS`; fixed image port 6333 |

The encryption keyring is a JSON object mapping approved key IDs to canonical
URL-safe base64 Fernet keys (32 decoded bytes / 44 encoded characters); the active
key ID must exist in that object. Generate/store keys through an approved secret
process, not shell output in shared logs. Keep decryption keys during rotation.

Private Qdrant uses HTTP without an API key in the isolated four-service network.
The accepted client **rejects API keys on HTTP**; do not set a plaintext private
key or weaken that check. This trusts the isolated project/environment and its
administrators. Never expose this service publicly or admit untrusted services
to this environment. If policy requires authenticated TLS inside the network,
stop and design that separate prerequisite before deployment; no silent fallback.
Use private PostgreSQL credentials; the private fabric supplies network isolation,
not per-service PostgreSQL identity. Review privilege/backup access explicitly.

## Same-origin sessions and proxy

Set `FRONTEND_URL` to the single approved public HTTPS frontend origin and
`GOOGLE_SESSION_REDIRECT_URI` to that origin plus
`/api/v1/auth/session/google/callback`. Register exactly that URI in Google's Web
OAuth client, enable Drive API, configure external test users A/B and confirm
restricted-scope eligibility/verification obligations. Testing Drive refresh
tokens may expire after seven days; test reconnect. Do not register the retired
`/auth/google/callback` flow or a private/backend callback domain.

The deployment server intercepts `/api/v1/*` **before Next's rewrite**, forwarding
the request to runtime `BACKEND_URL`. It preserves body, original Origin, CSRF,
Cookie, statuses, Location and multiple Set-Cookie headers; all API responses are
`private, no-store`. Cookie policy stays Secure/HttpOnly/Lax/host-only on the
frontend HTTPS origin. No CORS relaxation or third-party cookie workaround.
The proxy never logs request URLs/headers/bodies; Uvicorn access logs and forwarded
header trust are disabled. Do not enable SDK debug, SQL echo, settings dumps or
body/header telemetry. Railway edge logs are outside application control: verify
whether callback query strings are collected, restrict access and retention,
and require redaction before real credentials if applicable. Do not enable CDN
caching for private routes. Backend authorization remains the only authority.

A timeout/client abort closes the HTTP wait, **not proof that model/remote work
rolled back**. Reconcile durable turns with the same request key. No proxy retry
or automatic regeneration. No questions are placed in URLs.

## Fresh storage preparation — separately authorized operations only

1. Record new project/environment IDs, private endpoints, empty storage provenance
   and isolation from HarborDesk. Keep backend `INDEXING_ENABLED=false` and blank
   activation binding. Stop old/unmanaged writers; newly empty storage does not
   prove there are no writers using the same endpoint.
2. PostgreSQL must be ready with its attached volume. In an approved runtime
   container with private access, run **once**, not in replica startup/build:
   `alembic upgrade 20261015_1200`; verify `alembic current`. No migration runs in
   the packaged entrypoint or checked-in Railway configuration. For the first
   release before HTTP can start, an operator may separately authorize that exact
   command as a **one-time** Railway Pre-deploy Command, which has private network
   access; remove it after successful bootstrap and verify `alembic_version` from
   PostgreSQL. Subsequent migrations need explicit release approval, not an
   unattended replica-startup hook. See
   [pre-deploy execution](https://docs.railway.com/deployments/pre-deploy-command).
3. Provision a fresh **concrete**, uniquely named normal collection outside startup.
   With the default `text-embedding-3-small`, create unnamed 1536-dimensional
   COSINE vectors. Create `user_id` and `drive_file_id` KEYWORD (or UUID) payload
   indexes using the Qdrant collection/index API from inside the private network.
   For another model use the accepted resolver; never silently substitute models,
   dimensions, aliases or an existing collection. Verify GET collection config.
   Required API shapes (private operator connection only) are
   `PUT /collections/<approved-name>` with
   `{"vectors":{"size":1536,"distance":"Cosine"}}`, then
   `PUT /collections/<approved-name>/index?wait=true` separately for
   `{"field_name":"user_id","field_schema":"keyword"}` and
   `{"field_name":"drive_file_id","field_schema":"keyword"}`.
   These are creation steps for verified empty new storage, never recovery repair.
4. Validate HTTPS/session settings and the accepted credential keyring. Exercise
   sessions and conversations with indexing still off. Startup must not use paid
   embeddings or Google for its validation.
5. Inspect unresolved jobs, historical unknowns and recovery evidence; a fresh
   beta should have none. Do not clear flags to make readiness pass. The older
   `cutover_report` exact-revision check remains stale (`20261014_1200`); do not
   interpret it as authorization. Runtime capability validation accepts the
   conversation migration; correction of that operator report is separate work.
6. Compute the nonsecret binding offline under intended config:
   `python -c 'from app.core.config import get_settings; from app.services.indexing_runtime import activation_target; print(activation_target(get_settings()))'`.
   It binds endpoints/principal/schema/collection/model; it does not prove storage
   provenance, DNS integrity, old-writer termination or remote quiescence.
7. Obtain separate deployment/activation approval before supplying the binding
   and enabling indexing. Require supervisor handshakes and `ready/available`.
   Dependency failure closes local admission; diagnose and restart, never retry
   an uncertain BUILD automatically. No activation occurs in this milestone.

## Durability, shutdown and rollback

Stop new submissions, close indexing admission by disabling it on an approved
restart, and allow graceful drain before maintenance. Do not mistake Railway
redeploy overlap or SIGTERM for writer quiescence. Owner leases fence SQL;
uncertain Qdrant writes require externally enforced collection-wide maintenance
and the accepted operator attestation/reconciliation protocol. Keep FAILED
recovery-required jobs excluded; no autonomous release/replay.

Back up PostgreSQL using a consistent `pg_dump --format=custom` executed with
private runtime access (the PostgreSQL image includes it). Export to encrypted,
access-controlled off-platform storage without printing the DB URL/password.
Back up Qdrant through its snapshot API, download the snapshot privately and
encrypt/export it off-platform. For a cross-store recovery point, drain all
writers and record both backup identities/configuration together; arbitrary
independent live snapshots do not establish SQL/vector consistency. Back up the
credential keyring separately; restoring encrypted grants without keys loses
access. Define retention and restoration ownership before beta invitation.

[Railway volume backups](https://docs.railway.com/volumes/backups) are additional
protection; check Hobby availability/charges in the console, not assumed in this
budget. They restore within the same project/environment and wiping a volume
deletes its backups. Off-platform backups remain necessary. Restore only into
separate isolated targets first; verify migrations, conversations, owner lineage,
collection config and inventory before separately authorizing a switch. Never
restore beneath live writers or blindly downgrade populated migrations.

Rollback preserves volumes, manifests, sessions and encryption keys. Redeploy a
schema-compatible prior accepted image with indexing disabled; inspect restored
variables, since platform rollback can restore old configuration too. Never
reattach demo volumes, delete a database, clear recovery flags or switch aliases
as a rollback shortcut. Record image/source identities outside short image
retention windows. A force kill cannot guarantee graceful SQL/remote cleanup.

## Cost protection (estimates, not a $5-cap promise)

[Hobby pricing](https://docs.railway.com/pricing/plans): $5/month includes $5
resource usage; usage beyond that adds to the bill. Published container rates
are RAM $10/GB-month, CPU $20/vCPU-month, egress $0.05/GB, used volume storage
$0.15/GB-month. No third-party inference spending is covered by Railway.

Initial **limits**, not expected usage: frontend 1 GB/1 vCPU, backend 2 GB/1 vCPU,
PostgreSQL 1 GB/1 vCPU, Qdrant 1 GB/1 vCPU; one replica each. Measure before lowering
limits: downloads buffer in memory and OCR/embedding batches can spike. Builds
need separate headroom. Start with small sample files and inspect RSS/OOM/disk
growth; no fixed file capacity or total monthly bill is promised. Illustrative
average combined 1.5 GB + 0.1 vCPU + 2 GB disk is about $17.30/month before egress,
backups and OpenAI, not measured application usage. Do not assume four continuously
available services fit inside $5.

[Cost controls](https://docs.railway.com/pricing/cost-control): review Workspace
Usage and project/service metrics; set a Compute custom email alert and a human-
approved hard limit. Limits apply across workspace services, so inspect effects
on the existing demo; do not change its settings. Compute and Railway Agent limits
are separate. A hard limit takes workloads offline and can interrupt indexing;
it is a safety stop, not graceful shutdown. Maintain disk/backup capacity alerts.
No billing limits or purchases are changed by this code.

After testing, close admission/drain, then use service deployment Stop/Remove
controls without deleting volumes; disable auto-deploy/restart triggers and
confirm compute has stopped in Usage. Stop DB/vector services only after writers
finish. Retained volumes/backups continue incurring storage costs. Do not delete
data just to stop compute billing. Never stop the existing demo project.

## Local and live acceptance gates

Local: build both images; verify non-root users/Tesseract/no secret contexts;
run `node --test frontend/deploy/api-proxy.test.mjs`; test actual frontend server
against fresh migrated PostgreSQL 16/Qdrant 1.18 and default-off backend; inspect
health, cookies/Origin/errors, collection config and shutdown. Native ARM64
execution does not prove AMD64 execution; inspect multi-arch bases and verify
Railway's selected architecture before approval.

Live (requires separate authorization): effective root/config/image, runtime
private DNS, assigned PORT/domain/HTTPS, callback multi-cookie forwarding, Google
LOGIN/CONNECT identity/CSRF/logout, a response delayed beyond 120 seconds, no edge
private caching/log leakage, SIGTERM grace, restart with original volumes,
backup/restore, billed metrics/alerts and two real devices. Then separately
authorize indexing and perform two-owner sample ingestion/retrieval with source
ID swapping checks. Refresh observes durable jobs but does not automatically
continue remaining preparation stages. No live checks are claimed here.
