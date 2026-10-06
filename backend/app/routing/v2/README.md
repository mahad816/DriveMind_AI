# Semantic routing v2 domain

This isolated package contains immutable Pydantic schemas, deterministic
resolution through a metadata protocol, pure bounded state transitions, and an
evaluation-only staged provider adapter. Core domain/resolver/state modules do
not import providers, v1 models, database services, retrievers, executors, or
RagService. Import semantic schemas from `domain`; the separate provider adapter
reuses existing settings and probability-validation utilities.

## Boundaries

- `RequestedOperations.requests` is an ordered tuple of one to three requests.
  Cardinality is a derived property; callers cannot supply it. Repeated equal
  requests are retained. Semantic ambiguity and unsupported requests are
  separate interpretation variants, not executable bundles.
- Requests are discriminated by capability. File-target actions have a nested
  operation discriminator: summarization has one target; answering a question
  additionally requires its original question span. All models forbid extras.
- File references contain candidate handles, selectors, or contextual reference
  semantics, never arbitrary filename strings or database IDs.
- `PreparedInput` must be created from application-owned input. Its immutable
  candidate registry has unique request-local IDs, at most 32 entries, and
  bounded source spans or enumerated context handles. Candidate representations
  expose only kinds, offsets, handles, and finite semantic labels. The original
  question remains the source for literal text. No display text is generated.
- `BoundInterpretation` checks span bounds, candidate existence, candidate kind,
  and selector/reference agreement. It does not query metadata or establish
  file existence. Python validates a provider's selection against an existing
  trusted registry; accepting a provider-created input envelope would defeat
  this boundary. Candidate generation is not implemented here.
- Source spans are nonempty half-open Unicode character offsets in the current
  question, with an 8,000-character input limit. Input may not be blank.
- Inventory ordering is allowed only for LIST. Collection scope is fixed to
  the indexed collection. Relative message position is 1–6 within the selected
  role; completeness and actual availability are later resolution concerns.
- No result/dependency reference is supported. Such intent may be represented
  as `UnsupportedRequest(reason=DEPENDENCY)`; it cannot become an executable
  request through an extra dependency field.

## Readiness and conversation

Readiness has typed READY, NEEDS_CLARIFICATION, UNSUPPORTED, and FAILED variants.
READY is only a future resolver-issued status marker. It is not proof of
resolution, an execution payload, or an authorization mechanism. Phase 3 supplies concrete resolution arguments and per-request readiness in
`resolved.py`; these are inputs for future adapters, not executor calls.

Conversation state stores bounded messages, a bounded active topic, up to
three unique resolved file UUIDs, and previous request envelopes. Saving the
input registry with a prior request preserves the meaning of request-local
candidate IDs and offsets. A successful prior bundle must contain requested
operations, not ambiguity or unsupported intent. There is no persistence. Pure updates are implemented in `state.py`. Resolver implementation must define uniqueness,
completeness, and how collection answers affect this bounded state.

## Provider separation

Probabilities, confidence, raw answer IDs, provider/model names, latency, usage,
and transport errors belong in future provider observations. They are not
fields of these semantic schemas. Provider-reported cardinality will be
validated separately against the domain tuple and must never repair it.

Use ordinary constructors, `model_validate`, or `model_validate_json` at trust
boundaries. Pydantic's unchecked `model_construct` and `model_copy(update=...)`
are not validation entry points and must not be used for provider data.

## Phase 3 resolution

`resolver.resolve` requires the application-owned `trusted_input` separately
from `BoundInterpretation`. It revalidates both, compares the complete question
and candidate registry, and never dereferences a bare candidate ID. This detects
stale/mismatched input; origin itself is a caller trust boundary, not a claim
that a hash authenticates provider input. The caller supplies prior-turn state,
excluding the current incoming user message.

`FileMetadataProvider.list_visible_indexed_files(user_id)` returns one complete
eligible snapshot, reused for all operations. The protocol adapter must attest
visibility and `indexed` status. The resolver additionally checks ownership,
unique UUIDs, nonblank names, and timezone-aware timestamps. There is no SQL
adapter or duplicate production query logic in this phase.

Actual `DriveFile` fields: `id` is the internal UUID, `drive_file_id` is the Drive
identifier, `name` is the canonical stored name, `modified_at` is the nonnullable
Drive modification timestamp, `indexed_at` is nullable, and inherited
`created_at`/`updated_at` record database bookkeeping. Existing collection
retrieval scopes to user ID and `DriveFileStatus.INDEXED`. V2 uses internal UUID,
name, and modified_at; it does not use indexing time as file recency.

Sync currently substitutes the current UTC time when Drive omits modifiedTime.
The stored schema does not expose that provenance. The resolver cannot determine
whether a stored timestamp came from this fallback. This limitation requires
review before relying on recency in production; no schema or sync changes were
made here.

- Literal candidate spans exclude quote delimiters. Matching first uses raw exact names, then NFC + casefold exact equivalence.
  Punctuation, whitespace, extensions and spelling are preserved. No fuzzy matching.
  Zero matches yields FILE_NOT_FOUND, one resolves, duplicates clarify.
- Recency examines the complete eligible snapshot. Any missing timestamp makes
  the extremum unknown. Equal extreme timestamps clarify rather than select a
  UUID winner. Options are sorted by canonical name and UUID; secondary ordering
  stabilizes display, never pretends uniqueness. Defensive null handling applies
  even though the production column is nonnullable.
- Default inventory and collection-summary scopes are complete and valid even
  when empty. An empty inventory LIST/COUNT is ready. LATEST/OLDEST requires an
  actual unique file, including for inventory metadata operations.
- Context-file kinds refer to the last established content focus. PREVIOUS_DOCUMENT
  does not imply the last element of a compound result. One active visible file
  resolves; multiple clarify; missing/deleted/nonvisible files fail resolution.
- Topic continuations use only active topic context, never file context as a
  substitute. Multiple active topics clarify. Explicit typed file/topic bindings
  remain distinct even when a successful compound established both kinds.
- History is chronological storage, filtered by role, then indexed backwards:
  relative_position=1 is the latest prior message of that role. A truncated or
  unavailable target produces HISTORY_UNAVAILABLE; no older message is invented.
- Structured clarification requirements contain request index, typed reason,
  factual detail, up to three safe file options, and total match count. They are
  not generated clarification prose.

Resolution reports preserve one outcome per operation. FAILED outranks
UNSUPPORTED, which outranks NEEDS_CLARIFICATION. Only all-READY reports expose a
`ReadyBundle`; successful siblings remain visible for diagnosis but cannot be
partially executed through that bundle. Lookup failures are sanitized and
attributed to affected requests. Invalid input/provenance fails before lookup.

## Phase 3 state transitions

`SuccessfulExecution` is a trusted executor attestation that all resolved
operations succeeded. Grounded operations require one ordered, bounded answer
summary each. Resolution readiness alone is not enough to update success state.

`apply_success` derives file IDs from resolved arguments and topic questions
from resolved query context. `RoutingConversationState` preserves the complete
last resolved bundle and up to three separate active topics. `active_topic` is
populated only when exactly one topic exists. A file or topic content operation
replaces stale focus; file+topic compounds preserve both. Collection summaries
clear prior individual focus instead of choosing an arbitrary document.
Inventory/history alone preserve existing content focus. Pure chitchat leaves
all substantive fields unchanged.

`apply_not_ready` rejects READY outcomes and preserves substantive context for
clarification, unsupported requests, and failures. `preserve_context` also serves
later execution failures. New messages are appended, then whole oldest messages
are dropped to satisfy six-message/6,000-character bounds. No messages are
invented, no persistence is performed, and no final answers/citations are built.

## Final pre-smoke atomic contract

The contract is frozen in `CONTRACT_LOCK.json`. `contracts.manifest()` reproduces
versions, code fingerprints, schema fingerprints, and the Stage-1 question hash.
The adapter refuses calls if the lock does not match. Per-input registry and
Stage-2 question hashes are recorded separately because options are dynamic.

Versions:

| Layer | Version |
| --- | --- |
| Preparation | v2-preparation-2.0 |
| Semantic domain | v2-domain-2.1 |
| Stage 1 | v2-structure-1.1 |
| Atomic Stage 2 | v2-atomic-requests-2.0 |
| Option generation | v2-option-generation-1.0 |
| Resolver | v2-resolver-2.0 |
| Probability validation | typesafe-probabilities-2.0 |

Stage 1 retains ONE/TWO/THREE/OVER_LIMIT/UNINTERPRETABLE. No deterministic
cardinality corrections or confidence thresholds exist. Stage 2 asks exactly
REQUEST_1…REQUEST_N. Each answer chooses one complete application-generated
atomic option, not independently generated operations or arguments. Required
positions have no NONE. Canonical non-executable outcomes are
SEMANTICALLY_AMBIGUOUS and UNSUPPORTED_OPERATION.

`options.py` contains capability-specific immutable options. Inventory list has
collection/source/order; count/latest/oldest have no ordering. File summary has
source and target; file question additionally has question provenance. Grounded
query has query provenance; topic continuation has a context handle. History
has role/ordinal reference. Collection summary has indexed scope; chitchat has
source only. Option IDs contain no free-text filenames or database identity.
All options are generated from structurally compatible templates, never semantic
likelihood scores. Translation validates the entire registry against current
preparation before trusting a selected ID.

Source offsets are half-open Python Unicode character indices in the original,
unmodified question. S001 always covers [0, len(question)). Additional bounded
spans expose sentences, semicolons, conjunctions/sequential separators, and
explicit reference occurrences. These spans do not declare semantic tasks.
File question/query arguments retain selected clause substrings without any
rewrite. Unicode filename matching never modifies offsets.

Distinct non-overlapping selected source ranges must agree with request order;
reversed ranges produce REQUEST_ORDER_REVERSED. Overlap/shared full sentences
are permitted and recorded. Selecting the exact same atomic ID twice produces
DUPLICATE_OPTION_SELECTION; no deduplication/repair occurs. Distinct occurrences
and references permit legitimate repeated operations, even on the same file.
Different IDs that translate to identical complete semantic provenance (such as
DEFAULT/NAME_ASC aliases on the same source) are also rejected, never merged.

Inventory ordering is bounded: DEFAULT, NEWEST_FIRST, OLDEST_FIRST, NAME_ASC,
NAME_DESC. DEFAULT translates to NAME_ASC. Its future executor policy is raw
stored-name ascending (Python Unicode ordering) with stable internal UUID
secondary order; no sorting criterion is required from the user. NEWEST_FIRST
and OLDEST_FIRST translate to the existing MODIFIED_AT_DESC/ASC argument types.
No executor was implemented or modified. Null handling in actual list execution
must remain explicit; selector resolution already fails closed on unknown recency.

Literal resolution precedence is raw exact name, otherwise Unicode NFC +
casefold + final NFC equivalence. No whitespace/punctuation/extension/spelling
normalization occurs. Unique canonical equivalence resolves; collisions clarify;
raw exact always wins. The returned filename is canonical metadata, never text
invented by the provider.

Runtime-result dependencies (first result, second result, linked documents) and
joint multi-file comparison have no capability contract. Criteria require
UNSUPPORTED_OPERATION rather than arbitrary targets or independent summaries.
No result-reference options or comparison capability exist. A model can still
misclassify the user's meaning as a supported independent action: bounded types
cannot prove semantic correctness. This is an explicit future evaluation risk,
not a reason to add regex interpretation or a third model stage.

Privacy: provider context uses ACTIVE_FILE_CONTEXT, MULTIPLE_ACTIVE_FILES,
ACTIVE_TOPIC, LAST_USER_MESSAGE, LAST_ASSISTANT_ANSWER, LAST_SUBSTANTIVE_REQUEST,
counts and capability summaries. Historical message/topic text and filenames
are withheld. A historical name becomes a literal candidate only when exactly
present in the current question. A private state fingerprint detects snapshot
changes without sending IDs. File existence/ownership/visibility/index status
remain resolver responsibilities, not conversation-state assertions.

Limits: question 8,000 characters; source spans 8; candidates 32; bindings 64;
executable atomic options 220 (+ two special outcomes); serialized Stage-2
questions 40,000 UTF-8 JSON bytes; total request 48,000 bytes; state + longest
question 24,000 bytes. The byte guards are conservative local safety policies,
not exact tokenizer measurements. No registry is silently truncated or ranked.
Preparation errors report safe counts (and generated lower-level size when
available); complete runs record span/candidate/binding/option counts and
Stage-2 serialized size. Not-yet-built schemas have size zero, not a fabricated
estimate. Option overflow reports the total bounded template count.

All current-question, filename, span, and context content is DATA TO CLASSIFY,
not router instructions. Schema validation accepts only known supplied IDs,
not provider-written source text, arguments, tool names or database IDs. This
bounds execution input; it does not prove immunity to semantic prompt injection.

Stage checkpoints: `interpret(..., checkpoint_path=...)` writes a sanitized
successful Stage-1 checkpoint before Stage 2. `read_checkpoint` plus
`interpret(..., resume=checkpoint)` revalidates the retained response and all
identities before reusing it. Identity includes prepared input/private context
hash, registry hash, both question schemas/configs, versions, provider/model,
and source code fingerprints. Response hash protects accidental modification.
No timestamps determine eligibility, no automatic retry occurs, and no provider
idempotency behavior is assumed. Mismatch returns an error without reposting.
Old checkpoint files are never overwritten. A crash/unknown outcome before a
Stage-1 response is persisted cannot be recovered by this local checkpoint;
it requires explicit review, not an automatic resubmission.

Provider telemetry preserves separate stage latency/usage/probabilities/models.
Stage-1 replay preserves original measurement; `reused_stage1` and
`new_post_attempts` distinguish old observations from new HTTP attempts.
`telemetry_record()` excludes raw domain input by default and records cardinality
selection/probability/margin. Synthetic evaluation may explicitly include its
synthetic domain text. Keys, Authorization headers, exception text and arbitrary
raw error bodies are never retained. Exact model-alias and rounding policies
are shared with v1 unchanged.

Explicit semantic ambiguity produces a typed non-executable signal; this
contract does not invent competing alternative bundles from probabilities.
Unsupported output blocks the bundle. Neither outcome is a low-confidence
fallback or repaired provider contradiction. All production routing remains v1.

### Post-smoke current-bundle dependency safety

`RuntimeResultCandidate` records only bounded explicit result-relative occurrences:
“the first/second one/result”, “the file you just listed”, and “the result you just
found”. Quoted text and filename occurrences remain protected. Bare ordinals and
chapter/section/policy ordinals are not result references. No new clause parsing,
span ranking, or pruning is performed.

`RuntimeResultReference` cannot resolve through conversation state or metadata.
Its atomic option translates to `UnsupportedRequest` with
`RESULT_DEPENDENCY_UNSUPPORTED`. The resolver also rejects manually bound runtime
references and contextual substitutions in an input containing an explicit runtime
candidate, irrespective of provider-selected source spans. This intentionally fails
closed when result-relative wording could alternatively mean a prior result.

For implicit pronouns, a small output-context map establishes potential FILE_CONTEXT
for inventory LATEST/OLDEST and both file-target operations, and TOPIC_CONTEXT for
GROUNDED_RAG:ANSWER. A later compatible contextual reference is unsupported, even if
previous conversation state has a unique target. This does not assert coreference.
LIST/COUNT, collection summary, history recall, and chitchat establish no context kind
for this guard. Single contextual requests without explicit runtime candidates and
independent literal targets retain their previous behavior. Every request is still
resolved before bundle readiness; an unsupported member prevents execution.

Contract versions are domain 2.2, preparation 2.1, atomic Stage 2 2.1, option generation
1.1, resolver 2.1. Stage 1 and semantic criteria are unchanged. Previous smoke artifacts
remain historical evidence; exact-identity checkpoints from the earlier contract must
not be replayed under this contract.
