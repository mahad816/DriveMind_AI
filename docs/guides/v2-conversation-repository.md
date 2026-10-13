# Conversation database foundation (4F2-S1)

Normal-account conversation and turn tables are provisioned by additive revision
`20261015_1200`, following `20261014_1200`. No HTTP route, frontend cutover or
indexing activation is added. Existing QueryHistory rows remain unchanged and
unassociated; no browser history is imported. Anonymous demo remains browser-local.

`ConversationRepository` receives a trusted, verified owner UUID from server code.
It is not an authentication boundary and must not receive owner identity from a
request payload. All methods require a caller-owned transaction; they may issue
SQL or flush pending changes but never commit or roll back that transaction.
Callers must roll back on exceptions. No returned record implies durable acceptance
until the caller commits. Do not edit repository-managed ORM objects directly.

Creation hashes normalized title in a versioned canonical JSON document. A matching
owner/create-request UUID replays the same record; different payload conflicts.
Turn hashes include conversation, normalized original question, operation, source
turn and base content version. Exact repeats replay before version/busy checks;
changed input conflicts. UUIDs are generated server-side. The owner/request key is
unique across that owner's conversations, independently of other owners.

Reservations lock only the owned conversation, allocate its next sequence and
capture the history boundary. One RUNNING turn per conversation is enforced by
PostgreSQL. Different conversations can reserve independently. Conversation
content version advances at reservation and terminal publication; metadata version
advances only on rename/delete. Turn pages return the newest bounded page in
ascending sequence order, with `before_sequence` for older pages. Metadata lists
use activity/UUID keyset ordering; concurrent activity may reorder listings.

Completion/failure locks conversation then turn, validates the exact execution UUID
and RUNNING state, and checks fresh database time AFTER both locks. The locks remain
until caller commit/rollback; physical commit need not finish before the deadline.
Pending result writes flush only after this authorization. QueryHistory is the sole
successful answer/citation record; composite foreign keys enforce result and source
ownership. PostgreSQL protects original questions and request/execution identities
against updates. No raw provider error text is stored: errors are bounded categories.

Not-found covers foreign, missing and tombstoned resources. Separate exceptions
represent payload conflict, stale version, generating/busy and lost execution.
Unexpected integrity errors propagate to the transaction owner, not a guessed
conflict response. The repository does not translate these outcomes into HTTP.

Tombstoning excludes ordinary reads, blocks reservation, interrupts active turns
and fences subsequent completion through the conversation lock. It does not remove
successful results. Source references and initiating sessions are retained by normal
foreign keys; session/result cleanup must respect these associations. Empty downgrade
is supported; populated downgrade refuses destruction, including tombstoned records.
Permanent purge and retention (including linked QueryHistory/session policy) require
explicit approval before beta deployment. No purge worker is introduced.

S2A must add normal-mode route guards, existing session/CSRF dependencies, version
preconditions, pagination and private/no-store responses. S2B must own admission and
result transactions, revalidate initiating-session freshness/revocation at meaningful
boundaries, bound generation, and classify expired turns without automatic replay.
S1 only validates initiating-session owner/kind association; it does not claim that
that session remains live during future model work. S2B must also enforce source-turn
retry eligibility and response-size limits; S1 establishes their identity constraints.
