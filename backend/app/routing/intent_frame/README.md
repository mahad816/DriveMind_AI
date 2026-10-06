# IntentFrame contracts

Semantic interpretation != deterministic resolution != execution plan != retrieval
!= evidence != generation. This package has no providers, database, graph or
service dependencies. No runtime uses it yet.

Semantic constraints may become UNSUPPORTED, but they may never silently disappear.
`IntentFrame` is a discriminated union of requested, unsupported and uninterpretable
forms. Requested cardinality derives from the ordered tuple; there is no action count.
Application-owned candidate IDs/spans must later be checked against the exact
prepared envelope. Hashes alone do not authenticate provenance. Source offsets
are half-open Python Unicode code-point offsets in unmodified input.

Semantic scopes are mandatory. Folder, label and modification-time restrictions
remain semantic handles. Bounded conjunctive restrictions are also representable.
They cannot construct an executable plan yet: stable folder identity, Drive labels,
and trustworthy strict filtering where source modification time is unknown are
unsupported. `ResolvedFileScope(file_ids=())` means zero files, never the collection.

ExecutionPlan retains one semantic frame and validates one execution record per
step. Operations/provenance are not copied to execution records. Concrete file
arguments attest resolution; this model cannot prove existence or ownership.
Resolver/executor adapters must check current eligibility later. An unspecified
single-file target cannot become an execution plan.

LIST output is ORDERED_FILE_LIST. DEFAULT means filename Unicode casefold ascending,
then stable internal file identity ascending. ITEM_AT_INDEX is zero-based into
that actual producer result, never a new metadata query. UNIQUE_FILE selects the
FILE output of LATEST/OLDEST. Producer compatibility is checked on ExecutionPlan;
semantic frames only enforce preceding positions. File summaries/questions and
other answers produce TEXT_ANSWER, not invented FILE results. EVIDENCE_SET and
NO_VALUE are reserved output kinds; no current operation declares them as its
public output. File context retained by an answer is distinct from answer output.

Evidence sections derive combined text and output mappings solely from validated
member substrings plus bounded whitespace separators. Input source-text authenticity
is an application trust boundary; generated summaries must never be supplied as
EvidenceChunk text. JSON round trips use validated Pydantic entry points. Frozen
models and tuples prevent ordinary mutation; unchecked model_construct/copy updates
are not validation entry points.
