# V2 Checkpoint C2: selection, review and preparation UI

## Flow and boundaries

Normal-mode Files has an ordered in-memory draft, separate from preview focus.
Native checkboxes select up to five eligible owner-scoped documents. Search,
filters, previews and metadata reloads preserve the draft and its original frames.
Changed, missing or ineligible entries remain visible and block review until removed.
Session invalidation clears the draft; no draft is stored in URLs or browser storage.

Review is inline in Files. It resolves names/types from fresh authorized metadata
and shows every selected entry. Cancel returns to the unchanged draft without a
reservation or processing POST. One deliberate **Prepare first document** click
revalidates/reserves the exact ordered batch and starts only its first document.
Rendering, selecting, previewing, loading details and reservation alone do not process
content. The original inspector link still supports legacy single-file preparation.

`QueuePreparationView` observes the approved C1 coordinator, not a second executor.
The shared Checkpoint B executor sequences targeted stages. Each completed child
hands off atomically, then the user explicitly chooses **Prepare next document**.
Ready requires backend job and indexed inventory confirmation. No overall percentage,
estimate, automatic next-file processing or owner-wide request is introduced.

## Lifecycle and compatibility

Page hiding, pagehide, explicit navigation actions and unmount pause/dispose the
coordinator. Remount and polling observe exact receipts; they never restore mutation
permission. Accepted jobs can continue on the server after leaving. UI callbacks,
metadata requests and coordinator operations are fenced to their owner/session.
Duplicate actions have a synchronous UI guard as well as the controller/storage guards.

`/prepare` inspects the canonical gate: legacy work uses the original single-file
screen; queue work uses the queue screen; malformed/unknown versions fail closed.
A new file query never replaces saved work. Files surfaces existing preparation
and disables new draft reservation while the gate is occupied or unverifiable.
C1's shared discovery gate remains present between documents.

The narrow C1 additions are reconnecting observation without reviving permission,
identity-bound confirmation for the displayed batch/cursor/child/file, and an optional
reserve-and-start action fenced to the originally reserved first child and controller
generation. Terminal closure also compares the exact queue displayed to the user,
so a stale close action cannot adopt a replacement. Existing default contracts remain.

## Results and recovery

Failed, skipped, uncertain and recovery-required outcomes stop the queue and retain
previous results. No skip/retry-next/reset shortcut exists. Fresh authorized indexed
metadata enables knowledge-wide chat; it does not promise batch-scoped retrieval.
Users can leave progress without deleting its record. Explicit closure is available
only for C1's known terminal states. A stopped queue can be ended, abandoning its
unstarted tail while preserving prepared backend documents.

Unstarted reserved queues still have no discard operation: return to progress and
explicitly prepare the first document. Unknown work must not be cleared to escape
this limitation. Use the Checkpoint B/C1 operator recovery procedure; current APIs
cannot correlate every lost acknowledgement or atomically freeze remote content.

## Verification and acceptance

Use only synthetic/local APIs. Component/transport tests cover ordered selection,
bounds, preview independence, cancel, metadata changes, targeted three-file execution,
explicit handoff, partial failure, duplicate clicks, interrupted preflight, delayed
receipts, refresh, session fencing, legacy dispatch and demo isolation. Existing C1,
Checkpoint B, discovery, transport and session regressions remain required.

Browser acceptance uses the existing isolated Chrome/CDP harness and temporary source
copies outside the repository. Check desktop, short laptop, mobile, both themes,
long names, keyboard selection/confirmation, focus, scrolling, explicit next-file
confirmation, interruption and failure without a next-file POST. Browser observations
with mocked responses do not establish live OAuth/Drive/provider acceptance.
