# Authenticated conversation cutover (4F2-S3C)

The root layout mounts one `ServerConversationsProvider` under the verified
`ApplicationSessionProvider`. Desktop/mobile sidebars and normal chat share that
controller. Demo rendering constructs no normal controller; `DemoChatInterface`
and the demo sidebar retain the existing browser-local storage keys and corpus.

Normal mounted conversation operations use the accepted conversation API adapter:
create/list/detail/rename/tombstone, submit/replay, status and explicit expired-turn
interruption. PostgreSQL supplies canonical IDs, titles, ordered turns, answers
and citation snapshots. Memory holds only drafts, source previews and request
bookkeeping. Legacy normal storage helpers remain for quarantined records and
existing tests, but no mounted normal conversation path invokes them. Records are
not imported, reassigned or deleted. There is no browser-history fallback.

History and sidebar pagination are explicit, bounded actions. Refresh retains
confirmed content on transient failure. Metadata conflicts reload canonical
state; generic generation conflicts remain uncertain rather than guessing their
cause. Failed/interrupted attempts may be retried as new append-only questions;
regeneration is not offered. A lost acknowledgement is reconciled with the same
frozen request identity. RUNNING history exposes bounded progress checking and,
only after the backend reports expiry, explicit interruption. Stop waiting/checking
cancels the browser wait, not the server turn. Refresh recovers durable history,
not unacknowledged memory bookkeeping or resumed model execution.

The session provider unmounts private children on verification/expiry/account
changes. The accepted controller additionally fences owner, session revision,
selection and request generations. Local draft/source state is keyed by verified
owner/revision. Late creation cannot redirect or submit into a newer selection.
Chat routes bypass Drive onboarding so saved/indexed history remains readable
when reconnect is required. Backend session and resource authorization remain
mandatory; indexing admission is unchanged and closed.

Normal file/source navigation no longer embeds questions in `?ask=`. Incoming
normal ask parameters are removed without adoption or automatic submission.
Citation SQL file IDs are never used as Google provider IDs: citation panels link
to `/sources/{chunk_id}`, whose live content still uses the authorized source API.
File-list provider links retain actual provider IDs. Demo ask links are unchanged.

Mounted React integration tests use synthetic cookie sessions, the real S3A
adapter/controller/provider and an in-memory fake HTTP server matching accepted
backend DTOs. They do not replace independent backend PostgreSQL acceptance.
Reload/second-context tests simulate independent mounts/storage; real browser
HTTPS/cookie and two-device verification remain deployment acceptance work.
