# Existing Railway beta: streaming readiness and manual rollout

Status: **Prepared for a separately approved deployment with streaming off.** Publishing and
manual deployment require separate approval. This guide authorizes no push,
variable change, migration, deployment, new environment or paid request.

## Hosted evidence — 2026-10-25

Read-only Railway CLI checks confirmed project `drivemind-v2-beta`
(`8ef4242e-709d-4044-a0bb-b1ae13636ff9`), environment `production`
(`130fa3d5-a9ae-4de8-bc6c-ee7b77fab142`). These are observations, not guarantees
that future dashboard settings remain unchanged.

| Readiness item | Verified observation |
| --- | --- |
| Backend | `DriveMind_AI`, deployment `e97ddd48-e38c-48e5-a135-3ddb9a8f2204`, commit `fcd26aee7fb57d20aa6fc067ca525639cb62ffad` |
| Backend image | `sha256:60984cd31487968ce54c0506120a7ef5c396aed6d39c0642d66ca5fae0c4f4f5` |
| Frontend | `drivemind-frontend`, deployment `0f2c867f-2e24-473b-9732-15fc10443628`, commit `bf9eaf094b0de4de5d1d25712737770e5175d308` |
| Frontend image | `sha256:1f7f3c86176b33fd914a727fda38769efb2a7b97b2a71a468cc1b7a697a93f16` |
| Rollback targets | Both deployment IDs above report `canRollback=true` and `canRedeploy=true` |
| Database | Revision `20261015_1200`; required session/conversation schema previously inspected; no release migration |
| Health | General readiness HTTP 200/database connected; indexing `ready/available`; Qdrant checks pass, collection green |
| Recovery | One separately approved backend restart recovered the latched supervisor; image/settings/storage unchanged |
| Work/data at recovery | No queued/running jobs, running turns or recovery-required jobs; 13 indexed files, 14 documents, 27 chunks/points unchanged |
| Backend runtime | Production, debug/demo off, application sessions/native agent enabled, required credentials present; values never logged |
| Streaming | New release not deployed; backend/frontend streaming variables unset; both release defaults are false |
| Auto-deploy | Both services report no repository triggers (`repoTriggers.edges=[]`); recheck before publishing |
| Build/source | Active images use Dockerfiles with `/backend` and `/frontend` roots; verify future build settings and source SHA before each manual deployment |
| Real OpenAI/browser acceptance | Not performed; paid-request approval still required |

An existing historical `INDEXING` file label dates to October 15; its associated
jobs are completed. It was preserved and is not evidence of an active job.
Authenticated browser session/saved-chat checks should be repeated after deployment;
read-only health and schema observations do not substitute for them.

## Exact dashboard checks before approval

1. Open the **existing beta project and its existing environment**. For backend
   and frontend, open **Deployments → active successful deployment**. Record the
   full source commit, deployment ID, image identity, timestamp and health state.
   Do not use the latest queued/failed deployment as the active source identity.
2. In each service's **Settings → Source**, verify branch
   `feature/v2-state-performance`, roots `/backend` and `/frontend`, Dockerfile
   builder, existing start commands, auto-deploy policy and any staged changes.
   Verify the frontend still runs `node deploy/server.mjs`, which owns its API proxy.
   Keep auto-deploy off for the manual rollout; do not push before this is verified.
3. Inspect **Variables**, including references/shared variables, without copying
   secret values. Record only the nonsecret values and presence checks below.
   Compare current values to the active deployment's effective configuration.
4. In **Deployments**, find a known-good frontend and backend deployment. Confirm
   each has a usable **Rollback** action now. Record their IDs/images and source
   identities. If an image has expired, document an executable source-based
   redeploy fallback and its compatible variable snapshot before approval.
5. Through the beta frontend HTTPS origin, inspect the existing signed-in
   session using GET `/api/v1/auth/session`, GET `/api/v1/files`, conversation list
   and an existing conversation detail. Verify correct owner and readable saved
   answers/citations. Do not copy cookies/CSRF tokens into reports. These reads do
   not prove a fresh chat generation; do not send a question yet.
6. Inspect backend health and the read-only database metadata below. If the DB is
   incompatible, **STOP**. Do not run `alembic upgrade`, pre-deploy migrations,
   credential disposal, reindexing, resets or volume replacement.

Backend values to verify:

| Setting | Required/evidence to record |
| --- | --- |
| `APP_ENV`, `DEBUG`, `DEMO_MODE` | `production`, `false`, `false` |
| `GOOGLE_APPLICATION_SESSIONS_ENABLED` | `true`; existing owner-bound session login |
| `FRONTEND_URL` | Exact beta HTTPS origin used for Origin checks |
| Google callback/client/encryption settings | Existing valid configuration; key presence only; no rotation |
| `OPENAI_API_KEY` | Configured/nonempty or sealed; never print; presence is not proof of validity/quota |
| `CHAT_MODEL`, `EMBEDDING_MODEL` | Confirm intended `gpt-4o-mini` and existing embedding model |
| `TOOL_RAG_AGENT_ENABLED` | Must be `true` before streaming activation; if currently false, stop for separate review of agent activation |
| `CHAT_STREAMING_ENABLED` | Default/initial rollout `false`; later deliberate runtime opt-in |
| `DATABASE_URL`, Qdrant config | Existing intended beta targets; presence/target identity only, no credentials |
| Indexing flags, activation target and credential keys | Record/preserve existing configuration; no changes for streaming |

Frontend values to verify:

- `BACKEND_URL`: existing private backend origin including its port, without
  credentials; same-origin `/api/v1` continues to forward cookies/Origin/CSRF.
- Build: `NEXT_PUBLIC_API_URL=/api/v1`, `NEXT_PUBLIC_DEMO_MODE=false`.
- New build flag: `NEXT_PUBLIC_CHAT_STREAMING_ENABLED=false` initially. A runtime
  variable alone cannot change an already-built browser bundle.
- Existing ports, HTTPS/domain, healthcheck, restart/drain/overlap settings remain
  intact. Healthchecks are frontend `/_deployment/health`, backend
  `/api/v1/health/ready`; `/api/v1/health/indexing` reports separate admission state.

Optional **read-only** backend terminal inspection (prints no secrets):

```sh
python -c 'from app.core.config import get_settings; import json; s=get_settings(); print(json.dumps({"app_env":s.app_env,"demo_mode":s.demo_mode,"debug":s.debug,"application_sessions":s.google_application_sessions_enabled,"tool_agent":s.tool_rag_agent_enabled,"streaming":getattr(s,"chat_streaming_enabled",False),"openai_key_present":bool(s.openai_api_key),"chat_model":s.chat_model}))'
python -m alembic current
```

### Read-only schema compatibility check

Run against the **existing beta application database**, using its actual role and
search path through an already authorized SQL console/client. Do not paste a
connection URL or secret into a report. SQL prints schema metadata, not user data:

```sql
BEGIN READ ONLY;
SHOW search_path;
SELECT current_schema();
SELECT version_num FROM alembic_version;
WITH required(name) AS (VALUES
  ('users'), ('application_sessions'), ('oauth_pending_states'),
  ('google_oauth_tokens'), ('conversations'), ('conversation_turns'),
  ('query_history'), ('drive_files'), ('documents'), ('chunks')
)
SELECT name, to_regclass(name) IS NOT NULL AS present FROM required;
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = current_schema()
  AND table_name IN ('application_sessions','conversations','conversation_turns','query_history')
ORDER BY table_name, ordinal_position;
SELECT conrelid::regclass AS relation, conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid IN (to_regclass('conversations'), to_regclass('conversation_turns'))
ORDER BY relation, conname;
ROLLBACK;
```

Expected revision for this release is `20261015_1200`. Missing revision/table,
older or unexpected revision, wrong search path or inconsistent constraints is
a blocker, not permission to migrate. Compare the columns/owner-bound foreign
keys with `backend/app/db/models/` and existing migration
`20261015_1200_conversations.py`. In particular verify session ownership and
expiry fields, conversation versions, unique logical request IDs, execution
identity/deadline, history boundary, and owner-bound query-history publication.
No data migration is needed if this existing schema is already compatible.

## Flags and code prepared

| Stage | Backend `CHAT_STREAMING_ENABLED` | Frontend build `NEXT_PUBLIC_CHAT_STREAMING_ENABLED` |
| --- | --- | --- |
| Deploy code safely | `false` | `false` |
| Enable backend endpoint | `true` | `false` |
| Controlled streaming beta | `true` | `true` |
| First rollback step | Keep `true` | Restore/rebuild `false` |

Both flags default to false. The former `LOCAL_CHAT_STREAMING_ENABLED` and
`NEXT_PUBLIC_LOCAL_CHAT_STREAMING` names are retired; they do not enable the new
code. `APP_ENV` stays `production`. The native-agent prerequisite, normal-mode,
session/Origin/CSRF checks, validation, source ownership, durable publication and
original non-streaming routes remain authoritative. The two audited P2 fixes
(session-expiry invalidation and streaming `max_retries=0`) remain intact.

The backend image explicitly defaults `CHAT_STREAMING_ENABLED=false`; the runtime
setting can be overridden separately after approval. The frontend Docker build
declares the new nonsecret flag as
`ARG NEXT_PUBLIC_CHAT_STREAMING_ENABLED=false` in the build stage. Railway exposes
service variables to Docker builds through declared ARGs; a rebuild is required.
The packaged proxy pipes SSE without buffering and preserves `no-transform` while
enforcing private/no-store caching. Application budgets stay 120s generation,
135s browser stream, 180s proxy; idle SSE comments keep the connection alive.
Hosted edge buffering and effective shutdown/drain behavior still need observation.

## Preparation verification

- Backend streaming/agent/non-streaming/conversation/security/demo compatibility:
  **345 passed, 102 skipped** (disposable database tests not configured).
- Full frontend suite, including SSE/session/controller/non-streaming and
  Files/preparation regressions: **825 passed**.
- Packaged Node API proxy: **12 passed**, including a chunk delivered before EOF,
  `no-transform`, cookies/Origin/CSRF, backend errors and disconnect transport cleanup.
- TypeScript, scoped ESLint, Ruff/format, scoped mypy and `git diff --check`: passed.
- Full `mypy app` retains one pre-existing error in unchanged
  `app/agents/tool_rag/finalization.py:76` (incompatible local-variable assignment).
- Production default-off, explicit production opt-in, native-agent prerequisite,
  demo rejection and auth/CSRF/Origin refusal are covered with mocked providers.
  The audited one-attempt SDK retry test and session-expiry regressions still pass.

These establish code/transport regressions only. No real OpenAI generation, release
Docker image build, hosted DB migration, release
deployment or variable change was performed. Hosted read-only readiness and the
separately approved recovery are recorded above; live-streaming acceptance remains
unverified.

## Deployment order — execute only after separate approval

1. **Readiness gate:** record all checks above, exact release SHA and both rollback
   IDs/images/config snapshots. Confirm no pending indexing jobs/preparation or
   active chat attempts before backend restart; let existing work drain. Preserve
   existing indexing settings. Review staged changes; deploy one service at a time.
2. **Publish the reviewed commit only after push authorization.** Record
   `git rev-parse HEAD`; `bf9eaf0` is the older Files release, not streaming.
   Once authorized, run `git push origin feature/v2-state-performance`. In
   Railway, open `drivemind-v2-beta` → `production`; verify auto-deploy remains
   off. Both services must deploy the same new reviewed release SHA. Do not use
   a restart or redeploy of an old image as a substitute for building new source.
3. **Backend first, flag off.** In the existing backend service, set/confirm
   `CHAT_STREAMING_ENABLED=false` without changing `APP_ENV`, secrets or indexing.
   In `DriveMind_AI` → Deployments, manually deploy the published release
   commit from `feature/v2-state-performance`, root `/backend`, Dockerfile build.
   Verify the resulting deployment source SHA. Wait for active healthy status.
   Check `/api/v1/health/ready`, current application session, Files, saved chats and
   citations. No pre-deploy migration command and no new generation yet.
4. **Frontend compatibility build, flag off.** Build/deploy the same release SHA
   with `NEXT_PUBLIC_CHAT_STREAMING_ENABLED=false`: open `drivemind-frontend` →
   Deployments and manually deploy that published commit, root `/frontend`,
   Dockerfile build. Verify source SHA and build-time flag; keep its private backend
   target intact. Confirm `/_deployment/health`, session and saved UI reads. This provides
   a known-good updated frontend image with streaming disabled for rollback.
5. **Backend enablement.** Only after the backend revision/schema/auth checks pass,
   explicitly set `CHAT_STREAMING_ENABLED=true` on the existing backend and let its
   resulting deployment/restart become healthy. Keep the frontend build flag false.
   Verify effective flags in the running container; do not change `APP_ENV`.
6. **Frontend enablement last.** Once the backend accepts the feature, rebuild and
   deploy that reviewed source with `NEXT_PUBLIC_CHAT_STREAMING_ENABLED=true`.
   Record the build-time variable snapshot/image. Changing only runtime variables
   or restarting the previous frontend image does not enable browser streaming.
7. **Acceptance gate:** after separate paid-request approval, execute the bounded
   browser tests below. Until then, deployment is not evidence of real streaming.

If any compatibility/health/auth step fails, stop and keep the frontend off. Do
not temporarily switch production to development or route to the local fixture.

## Real browser acceptance — paid approval required first

Before execution, propose a bounded question count, expected native tool/model
steps, embedding calls and estimated spend using verified current pricing and the
actual corpus/context size. One user question can make multiple model/tool calls;
do not count one question as one OpenAI request. No indexing/reindexing is needed
to test an existing verified Ready document.

After approval, test one beta browser/account first, against a known indexed file:

1. Ask a specific question whose answer is known from that file. In DevTools
   Network confirm **one POST** to `/api/v1/conversations/{id}/turns/stream`, status
   200, `text/event-stream`, private/no-store/no-transform, and progressive frames
   before EOF. Verify meaningful first and later deltas through the hosted edge,
   not just a final answer arriving at once. Provisional text is labelled unverified.
2. Confirm `complete` carries the committed answer; only then use verified source
   controls. Open the source and compare the relevant passage with the actual
   document. Reload to confirm canonical PostgreSQL history, without duplication.
3. Ask an unsupported question: inspect honest insufficient-evidence handling and
   absence of invented citations. Do not deliberately corrupt production evidence.
4. Stop one generation; provisional text must disappear. Reconcile the exact saved
   attempt before retrying. A commit racing Stop can correctly recover a completed
   answer. Refresh/switch conversation and verify no cross-conversation text.
5. Check session expiry/401 and reconnect behavior during an approved manual test,
   using only the current beta account's existing controls. Do not modify session
   tables, expose tokens or fabricate another owner's credentials. Automated
   mocks establish regression coverage, not hosted authentication acceptance.
6. Verify Files preview, selection/review and five-file gating through read-only
   interactions. Do not click Sync/Prepare during this chat-only acceptance.

Watch safe `conversation_attempt_failed` stage/category and turn ID, tool-agent
outcome/cycle counts, provider 401/429/503, generation timeout, `SOURCE_CHANGED`,
`SESSION_UNAVAILABLE`, request cancellation, proxy 502/truncation and stuck RUNNING
attempts. Never print raw provider bodies, prompts, document text, OAuth URLs,
cookies, CSRF tokens or environment secrets. A long 200 response/healthy process
does not establish that token streaming or citation verification succeeded.

## Rollback order

1. Pause beta chat submissions; let accepted work settle or reconcile its saved
   status. Restore the known-good **frontend flag-off image first**, or rebuild
   the reviewed frontend with the build flag false. Have beta browsers reload so
   cached streaming-enabled bundles stop calling the endpoint.
2. Keep the streaming-capable backend enabled until that frontend rollback and
   browser reload are confirmed. Then disable its streaming flag or roll back its
   image if required. This avoids leaving an enabled frontend against a rejecting
   backend. A backend emergency disable may still require immediate browser reload.
3. Railway Rollback can restore image **and custom variables**. Verify the restored
   environment, secret references, backend target and flags against recorded
   snapshots. Preserve session/encryption keys and existing storage. Use the recorded
   source-based redeploy fallback only if retained-image rollback is unavailable.
4. Repeat health, auth, saved history and Files checks. Reconcile uncertain attempts;
   never clear saved recovery state, reset storage or downgrade the DB as rollback.

Sources: [Railway Docker build variables](https://docs.railway.com/builds/dockerfiles),
[Railway deployment actions](https://docs.railway.com/deployments/deployment-actions).
These describe platform behavior, not verified settings of this beta.
