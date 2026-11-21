# DriveMind v1: product definition

Draft, 2026-11-21. Output of the product-definition interview (28 decisions, approved by the Owner). Terms follow `GLOSSARY.md`; decisions follow `docs/adr/0001-single-answering-path.md` and `docs/adr/0002-public-demo-isolation.md`. This repository is public: nothing here contains secrets, private Drive content or real file names; all examples are invented.

## How to read this spec

Every statement about the current system carries one of four labels. Statements without a label are requirements or decisions.

- **Verified**: confirmed by the evidence named in the Status ledger (Further Notes), which states the kind of evidence for each fact: *code* (read in the source or configuration), *test* (asserted by an existing test), *repo doc* (stated in a project document, not re-checked), or *historical measurement* (a past evaluation run: true of that run only, not of the current build or of production). A test or a name search supports only what it covers; it does not prove that something else is absent.
- **Defect**: a known problem, registered in `docs/KNOWN_ISSUES.md` (or listed in the ledger).
- **Unverified**: an assumption or a claim from research. Do not state it as fact; do not build on it before checking.
- **Future**: not approved. Listed so it is not built by accident.

Cross-cutting rules: nothing is claimed (encryption, complete deletion, privacy, accuracy) before it is audited. A search that finds nothing is not proof of absence. "Outdated" means as of the last explicit Drive check, never continuous monitoring. Priorities below set implementation order only; security and correctness are never ignored.

## Problem Statement

People keep important facts scattered across many Google Drive files. Finding an answer means remembering which file holds it and reading it. Generic chat assistants can answer fluently but may invent facts or cite sources that do not say what is claimed, which is worse than no answer.

DriveMind is a read-only Google Drive assistant that answers questions about the contents of a Drive, with evidence the user can check. The Owner is a sole maintainer building it with AI assistance, with no deadline. The product serves the Owner's own use and a public portfolio demo. A multi-Owner future is possible but not assumed. Quality comes before speed, and infrastructure stays proportional to a single maintainer.

## Solution

A polished, accurate, secure and maintainable application whose answering system is the tool-calling agent (ADR 0001). It reads only Files the Owner has explicitly prepared, answers with verifiable Citations, says plainly when information is missing or a File cannot be read, and never invents. Drive access is strictly read-only. The public demo runs on synthetic data in isolation (ADR 0002).

Release readiness is judged by measured quality gates (below), not by feature count.

## User Stories

Actors are the Owner and the Visitor.

**Questions and honesty**
1. As an Owner, I ask about one File and get an answer with a Citation I can open and check.
2. As an Owner, I ask a question that spans several Files and get one answer citing each File used.
3. As an Owner, I ask about an exact identifier or reference (for example an invoice number) and get the content that mentions it.
4. As an Owner, I ask which Files exist or what changed (inventory and metadata) and get an answer without citations.
5. As an Owner, I ask for a grounded summary of a File or topic.
6. As an Owner, I ask a follow-up ("and the one before that?") and DriveMind keeps the context of the conversation.
7. As an Owner, when a follow-up is ambiguous, DriveMind asks a short clarifying question instead of guessing or silently switching to an unrelated File.
8. As an Owner, when I name a specific File that was not found, DriveMind says so (optionally suggesting similarly named Files) and does not answer from a different File.
9. As an Owner, when only part of my question can be answered, I get the Supported answer part and a statement of what is Missing information.
10. As an Owner, for totals, counts and averages I get a result computed from verified source values, or an explanation of why it could not be verified. I never get unchecked model arithmetic presented as verified.
11. As an Owner, I can tell Missing information from a Retrieval failure, so I know whether to retry or to prepare more Files.

**Preparation and freshness**
12. As an Owner, I run a Drive check when I choose, and nothing starts preparing as a result.
13. As an Owner, I choose what to prepare: single Files, several Files, folders, or all supported Files, with search, filters and bulk selection.
14. As an Owner, I exclude Files and the exclusion persists across runs.
15. As an Owner, I can prepare only what needs updating.
16. As an Owner, I see each File's state (prepared, unprepared, unsupported, failed, outdated) and a summary before starting (selection, estimated time, estimated cost where feasible).
17. As an Owner, I see when Preparation last succeeded, each Source's modified date, and an "index may be outdated" indicator relative to my last Drive check.
18. As an Owner, I am told about every Unsupported file and every oversized File instead of having it ignored.

**Privacy and control**
19. As an Owner, I can Disconnect, Revoke, and Delete stored data as three separate actions, and each tells me honestly what it did and did not do.
20. As an Owner, I can learn what is sent to model providers.

**Application**
21. As an Owner, I see reliable streaming and progress, persistent conversation history, and my draft preserved when an error occurs.
22. As a Visitor, I try the demo with guided example questions and see clear budget messaging when the demo allowance is used up, and my conversation stays in my browser.

## Implementation Decisions

No file paths or code snippets appear in this section; they go stale. Current-state evidence is in the Status ledger.

### Scope (Q1, Q2)
- Own use plus a public portfolio demo. Multi-Owner is a possibility, not an assumption.
- Drive access is strictly read-only. Any future write capability is not approved.
- Future capabilities, unless separately approved: public SaaS, scheduled sync, Drive writes, scanned-PDF OCR, additional providers, enterprise infrastructure.

### Vocabulary (Q3, Q4, Q8)
- Use the glossary terms. Avoid "User" where Owner or Visitor is precise. "Principal" stays an internal security term.

### Supported question types (Q25)
- Single-file; multi-file; exact identifier or reference; inventory and metadata; grounded summaries; natural follow-ups; missing, ambiguous and partial questions.
- Totals, counts and averages: deterministic calculation from verified source values wherever possible; never present unchecked model arithmetic as verified; explain the limitation when values cannot be extracted or the calculation cannot be verified; never manufacture a number or cite a Source that does not support the values.
- Whether a focused deterministic calculation capability is needed is decided by the evaluation. If it is, it belongs in a core-reliability milestone and is not postponed automatically.

### Honesty rules (Q6)
- A specifically named File that is not found is reported, with optional similar-File suggestions, and never answered from another File.
- Partial questions get the supported part plus what is missing.
- Never invent evidence. Never cite a Source for something it does not say.
- General (unnamed) questions still search across all prepared Files.
- Separating a file reference from a topic: see "Rule: file reference versus topic" below.

### Answer system (Q9, ADR 0001)
- The tool-calling agent is the only active answering system in the stable release.
- Before release: verify its functionality, evaluation results and deployment configuration. When approved, disable normal production access to the linear and LangGraph paths. Remove the legacy code afterward in a controlled cleanup milestone.
- No path is switched and no code is deleted as part of this spec. The project rule that both grounded paths must be preserved changes only when the migration is approved.
- Provider failure never produces an ungrounded answer.

### Supported formats, capacity and language (Q7, Q24, Q26)
- Promised, after realistic testing: Google Docs, Sheets and Slides; text PDFs; DOCX, XLSX and PPTX; TXT, Markdown and CSV.
- Image OCR is best effort. Scanned PDFs are unsupported until proper OCR exists (Future).
- Unsupported or oversized Files are reported to the Owner, not ignored.
- Complex tables, charts and formulas are evaluated separately from basic text extraction.
- Capacity target: about 200 to 300 supported Files, verified by tests. No promise of 2,000 Files or 10 GB.
- Architecture stays modular. No distributed queues or autoscaling without a demonstrated need.
- English is officially supported and evaluated. Urdu and Roman Urdu are best effort and measured separately. Urdu-script document extraction is not promised without testing.

### Public demo (Q10, ADR 0002)
- Free and limited, funded by the Owner's API key; fixed synthetic corpus in dedicated storage; starting budget $5 per month, subject to confirming real costs.
- Backend-enforced spend limit and rate limit. When the budget is exhausted, paid requests stop and guided samples are shown.
- Spend protection requirements for the initial $5 per month budget. The backend must refuse a new paid operation when the budget would be exceeded by it, or when the budget cannot be safely enforced. Specifically:
  - Cost accounting is persistent: it survives restarts and redeploys, and is not held only in process memory.
  - Before each paid call, the backend uses a conservative cost estimate or a reservation against the remaining budget. The estimate errs high, and the account is corrected with the actual cost afterward.
  - Concurrent requests and retries are accounted for: two simultaneous requests cannot both spend the last of the budget, and a retry counts as a new paid call.
  - Failure is closed: if the accounting is unavailable, unreadable or inconsistent, paid requests are refused rather than allowed.
  - A refused request shows a clear budget-exhausted message with the guided examples, and no partial paid work is started.
  - Recording cost only after a request finishes does not by itself give an exact hard cap, because requests already in flight can overshoot. The design must not claim an exact cap unless the reservation approach is shown, by test, to prevent overshoot; otherwise the claim is "approximately bounded".
  - This is not a billing system: a small persistent counter and a pre-call check, nothing more. The design and tests belong to the release and demo milestone (M9).
- The demo never touches Owner data and cannot bypass budgets or authentication.
- Demo conversations live in the Visitor's browser.
- Reuse of the prepared index across Visitors: to be confirmed.
- Visitor-supplied API keys: a future investigation only. If ever done, keys never appear in URLs, logs or persistent browser storage, and are never stored permanently.

### Freshness (Q11)
- DriveMind never initiates a Drive check or Preparation by itself: never when the app opens, and never on a schedule or as an unprompted background sync.
- "Manual" describes who starts the work, not where it runs. Once the Owner explicitly starts a Drive check or Preparation, that approved operation may run asynchronously or as a background job (as the existing in-process job design does), and need not hold the foreground. It must stay limited to what the Owner approved.
- Show the last successful Preparation time and each Source's modified date, plus an "index may be outdated" indicator relative to the last Drive check.
- Make manual Preparation convenient.

### Ownership and security (Q12)
- Single-Owner reliability comes first.
- Every service that acts on a Google credential requires an explicit Owner; the first-stored-credential fallbacks are removed (KI-031, fixed by M0-SEC).
- Keep and improve the security tests. Session and authentication validation is a separate security milestone.
- No public signup, subscriptions, payments, billing or full onboarding.
- Before implementing, separate real current vulnerabilities from future scalability concerns. Address critical security risks early rather than waiting for the security milestone.
- Owner-mode abuse protection (decided and built in M0-SEC): a fail-closed sign-in allow-list, a persistent paid-question quota (20 per hour, 50 per day, 1 concurrent per Owner; provisional until M1 measures cost), input caps, an `Origin` and CSRF requirement on normal-mode `/chat`, and a rate limit on the login start. Practical provider spending safeguards (a usage budget and alerts in the provider dashboard) are verified by the Owner at the M9 gate; they are safeguards, never guaranteed hard caps.

### Privacy, retention, backups (Q14, Q22)
- Disconnect, Revoke and Delete stored data are three separate actions (see glossary).
- The Owner can delete stored data: extracted text, chunks, vectors, conversations and stored credentials. Deletion works on the live system across both stores (relational database and vector store), with defined failure handling and honest disclosure of backup limits.
- Credentials are protected (encryption at rest where applicable). Logs never expose tokens or private content. No unnecessary third-party analytics on Owner activity.
- Disclose what is sent to model providers, but only after verifying the provider's official API retention and training policies.
- Claim nothing (encryption, complete deletion, privacy) until audited.
- The relational database is authoritative for metadata, extracted text and chunks. The vector store holds regenerable vectors.
- Use simple managed database backups only if the existing hosting plan includes them. No extra paid backup infrastructure, schedules, restore drills or disaster-recovery documents.
- Data is kept until the Owner deletes it, subject to platform limits.

### Conversations (Q15)
- Natural multi-turn follow-ups that keep context; a short clarification when ambiguous; never silently switch to an unrelated File; never invent; Owner boundaries always hold.
- Follow-ups are a separate evaluation category.
- First investigate whether current conversation-history and context handling is sufficient (Unverified), before changing it.

### Application experience (Q16)
- Six journeys: first connection and Preparation; preparation status and stale-index information; unsupported or failed Files; errors and limits without losing input; public demo with guided examples and budget messaging; Drive disconnection and stored-data deletion.
- Also: reliable streaming and progress; verifiable Citations and navigation; persistent history; preserved drafts; clear distinction of supported, partial and missing answers; clear loading, empty, failure and success states; a clean professional interface that is desktop-first, responsive and basically accessible.
- Fix functional UX problems in the milestone that touches them. Final visual polish comes later.

### Preparation (Q17)
- Discovery never triggers Preparation. Nothing starts without explicit Owner action.
- Selection: single Files, multiple Files, folders, all supported Files; search, filters, bulk selection, clear indicators.
- Exclusions persist across runs. "Prepare only what needs updating" is easy.
- File states are clearly distinct: prepared, unprepared, unsupported, failed, outdated.
- Before starting, a summary shows the selection, estimated time and estimated cost where feasible.
- The queue is sequential, with progress, recovery and clear errors.
- Ease of use comes first. Audit existing functionality before building. Rank folder selection and advanced controls by user value; they are not prerequisites for RAG reliability.

### Release and maintenance (Q18, Q23)
- The validated development line becomes the new `main`, safely. Order of work: audit Git history and differences; decide between a fast-forward and a reviewed pull request; identify breaking changes, migrations and environment-variable changes; add continuous integration; keep paid RAG evaluation separate and gated; rehearse migrations on disposable infrastructure (local containers; no standing staging environment); verify the actual hosted beta (commit, migration revision, flags, environment); define deploy and rollback, including irreversible migrations; promote only after verification and approval; then adopt smaller feature branches and reviews.
- **Disposable infrastructure (confirmed by the Owner, 2026-11-21):** migration rehearsals use temporary local containers or disposable test databases. No permanent staging environment is required at this stage. Migrations are never tried against the live hosted database.
- No force-push and no history rewrite.
- Continuous integration starts early as a small foundation covering essential backend and frontend checks, then expands. Paid RAG evaluations stay out of it and need explicit authorization each time.
- Maintenance is lightweight: occasional review of dependencies, security, model availability and cost. No rigid schedules, key-rotation schedules or operating manuals. Document only essential deployment and recovery information.

### Models (Q20)
- Three roles: answer generation, claim checking, embedding.
- Choose by measured whole-system quality: benchmark candidates alone and in combinations; do not choose merely for newest, fastest or cheapest.
- Verify current availability and retirement dates from the provider's official documentation.
- Keep the provider abstraction; add no extra provider. Pin exact model identifiers for releases and run regressions before any change.
- Evaluate an embedding change for retrieval quality, vector compatibility and re-embedding cost. A model change does not by itself require re-extraction.
- Never return an ungrounded answer on provider failure. Upgrades are deliberate, measurable and reversible where feasible.
- **Retirement (provider source):** the current default chat model `gpt-5.4-nano` (identifiers `gpt-5.4-nano` and `gpt-5.4-nano-2026-03-17`) is deprecated; shutdown **2027-04-01**, notice dated 2026-10-01, recommended replacement `gpt-6-luna`. Source: the upcoming-deprecations table of OpenAI's deprecations page, https://developers.openai.com/api/docs/deprecations, read during the interview on 2026-11-21 (the deprecation row itself was read verbatim; other parts of that page were only summarized). The 2026-11-20 entry in `docs/DECISIONS.md` independently records the same shutdown date and replacement from the same page. The provider's suggestion is not the decision; choose by measurement. A replacement must be chosen and validated before the shutdown date. `docs/DECISIONS.md` also holds earlier reliability measurements of `gpt-6-luna` (historical, with request failures in one run). Re-read the page before acting on the date.

### Performance (Q13)
Initial goals, not claims about current production:
- Median total time 6 s or less; 90th percentile 12 s or less; first visible feedback within 2 s; average model cost $0.01 per question or less.
- Measure time to first feedback, time to first answer text, and total completion separately, through the deployed application under realistic concurrency.
- The 60 s timeout is a starting point, assessed against legitimate complex requests.
- Priority order: correctness and grounding, then latency, then cost. Reliability is never reduced for speed.

### Monitoring (Q21)
- Content-free error logs; request latency; model usage and estimated cost; enough diagnostic information to explain RAG and retrieval failures; support for the demo spend limit; existing hosting logs.
- No monitoring platform, dashboards or alerting unless later shown necessary.

### Priorities (Q27), implementation order only
1. Core RAG reliability: agent, retrieval, grounding, citations, single-file, multi-file, identifier, metadata, missing information, verified calculations, follow-ups, evaluation.
2. File preparation and ingestion: extraction, chunking, manual Preparation, selection, queue, File states, 200 to 300 Files.
3. Security and data: ownership, no credential fallbacks, no cross-account access, Disconnect, deletion.
4. Application and UX: conversations, streaming, source navigation, drafts, clear failures, accessible responsive interface.
5. Release readiness: continuous integration, model selection, hosting and migrations, promotion to `main`, secure demo with spend limits, basic logging.
6. Further enhancements: performance, advanced document understanding, visual polish.

### Rule: file reference versus topic (proposed hypothesis; NOT approved)
Product requirement (decided, Q6): identify file references accurately, and never make a false claim that a file is missing. A specifically named File that is not found is reported and never answered from another File; a topic or an identifier is searched for across all prepared Files.

What follows is a **hypothesis for evaluation**, not a design. The classification algorithm is not approved until it has been evaluated against the KI-025 and KI-028 cases (including `id14`, `id19` and `dx08`), related regression cases and a held-out set written before the work.

**Signals to consider** (none is sufficient alone):
- A filename extension in the phrase.
- Explicit file-reference wording ("the file called ...", "in the document named ...", "open ...").
- A match against File names, titles or other metadata of the Owner's prepared Files.
- Conversational context: a File the Owner or the answer already named earlier in the conversation.
- Quotation marks are a weak signal only. A quoted phrase can be a topic, a definition, a title, an example or ordinary text, so quotation alone never establishes a file reference.
- An identifier (an invoice number, a ticket code, a reference) is not assumed to be a filename. By default it is a content term to search for. It becomes a file reference only if other signals say so (for example it matches a File name, or the Owner asks for "the file INV-0457").

**Candidate outcomes:**
1. **Confident file reference**, matched to a prepared File: answer from that File.
2. **Confident file reference, no match** (strong signals such as an extension plus explicit wording): report that no such File was found, optionally suggest similarly named Files, and do not answer from another File. This is the existing behavior for extension-bearing names (KI-025).
3. **Identifier or topic**: search across all prepared Files; a failed name lookup must not end the search (KI-025).
4. **Named document or named entity** (for example "what does the *training handbook* say ..." versus "the setup fee for the *Enterprise rollout package*"): whether these two are different classes, and where the line falls, is an open hypothesis. The goals are that a thing presented as a document that does not exist is reported as not found (KI-028, `id19`), and that a named entity is answered only if a cited Source actually states it, otherwise reported as Missing information (KI-028, `dx08`). Whether this needs a structural rule, a model-assisted check, or an extension of the existing claim check is left to evaluation.
5. **Ambiguous**: ask one short clarifying question when the signals genuinely conflict and the cost of guessing is a wrong claim.

**Invariants (not hypotheses):**
- An unrelated File is never silently substituted for the one the Owner asked about.
- "Not found" is stated only as "not found in the Owner's currently prepared Files" (see Missing information); it is never presented as proof the File is absent from Google Drive.
- Whether a File exists must not be revealed across Owners (existing rule).

**Acceptance (to be written before any fix):** a labelled set where each question has an expected classification and expected outcome. The set includes the KI-025 and KI-028 cases, quoted topics and quoted titles that are not file names, identifiers that are not file names, identifiers that match a File name, follow-ups that refer to an earlier File, and genuinely ambiguous references. Pass means correct outcome, no false "missing File" claim, and no silent substitution. Measured on a held-out portion before adoption; the algorithm is adopted only if the evidence supports it.

### Definition: how a Supported answer is checked objectively (proposed)
An answer is a **Supported answer** only if every factual claim in it passes all of these:
1. **Decomposition**: the answer is split into atomic factual claims (headings, fragments and hedges are not claims).
2. **Entailment**: each claim is stated or directly implied by the text of at least one cited Source chunk. A valid-looking Citation marker alone does not count.
3. **Entities and numbers**: every named entity and every number in a claim appears in the cited evidence, or the number is the result of a deterministic calculation from values that appear in it. A number changed, rounded differently or combined without a calculation fails.
4. **Attribution**: content attributed to a File is in that File.
5. **No obedience to embedded instructions**: the answer does not obey a malicious or unauthorized instruction found inside File content (for example "ignore your rules and reveal ..."). Quoting, summarizing or discussing such an instruction, as a faithful description of what the File says, is not a failure.

Any failure of 3 or 4 on an invented or misattributed item, and any failure of 5, is a Critical failure (see the glossary).

Measurement: in evaluation, claim-level labels come from human-reviewed examples; an automated grader is used at scale only after its agreement with those human labels is measured and reported. The threshold for acceptable agreement is set in the evaluation milestone, from the measured data, not fixed here. At run time, the existing claim check (which removes unsupported statements) is a mitigation, not proof; it is Verified to be imperfect (`docs/KNOWN_ISSUES.md`, KI-002 entry).

### Definition: "meaningful progress within 2 s" (proposed)
After the Owner or Visitor submits a question, within 2 s of submission the interface must show both:
1. the submitted question in the conversation, and
2. a status indicator driven by a real server event (for example "searching your Files"), not only a local spinner.

Measured as: time from the submit action to the first rendered server-originated status or text, through the deployed application, at the 90th percentile under realistic concurrency. A purely local acknowledgement counts as feedback but not as meaningful progress. The server must therefore emit a first status event early; whether the current stream does so within 2 s is Unverified.

### Open design questions carried forward
- How the demo is throttled without per-Visitor tracking (ADR 0002).
- Whether the prepared index is shared across Visitors.

## Testing Decisions

### Quality gates (Q5, Q19), initial targets refined from results
- A **frozen question set of at least 150 diverse questions** over real-format files: PDF, DOCX, XLSX, PPTX, plus Google Docs, Sheets and Slides created in a test account with synthetic content.
- **Public regression tests** plus a genuinely separate **held-out set that is never tuned against**. Expected answers and criteria are written before any fix.
- Required question types: answerable, unanswerable, partial, ambiguous, multi-file, identifier, table, calculation, follow-up, adversarial.
- The evaluation must specifically cover each of the following and must not rely on aggregate accuracy alone:
  - wrong-file attribution (KI-028);
  - incorrect spreadsheet calculations (KI-029);
  - verbose-query retrieval failures (KI-022);
  - identifier-based retrieval (KI-027);
  - short-presentation retrieval (KI-030);
  - missing evidence versus technical retrieval failure;
  - multi-turn follow-up mistakes;
  - prompt injection through retrieved File content.

| Gate | Target |
|---|---|
| Answerable questions | at least 90% correct and properly cited |
| Unanswerable and partial questions | at least 95% correct; aim for about 60 or more such cases, since 95% on few cases is statistically fragile |
| Critical failures | zero, on a dedicated critical-failure set of about 20 or more cases |
| Stability | zero crashes across three complete runs |
| Owner's own Drive | at least 20 manually verified questions, recorded as counts only, never content or File names, kept out of the repository |

- Separate measures: retrieval, generation, claim checking, citation correctness, calculation, latency, cost, reliability.
- Record exact model identifiers, prompts, retrieval settings and configuration with each run.
- Validate the automated grader against human-reviewed examples.
- Evaluate the actual production path (the tool-calling agent as configured for release).
- Urdu and Roman Urdu are reported separately and are not a release gate.
- Paid evaluations always need the Owner's explicit approval.
- Reference point (Verified, `docs/EVALUATION_RESULTS.md`): the existing set is 94 cases, the tool agent passed 75/94 in the 2026-11-19 baseline, and the corpus is small. The gates above are therefore not met by current evidence and the existing set is smaller than the required 150.

### Other testing
- Keep the registry rule: each known defect has a strict expected-failure test; fixing one removes its marker and updates the registry. A fix counts only after a held-out set written before the fix and the full suite.
- Security: keep and extend ownership and isolation tests (no credential fallbacks, no cross-account reads, deletion across both stores including failure handling).
- Preparation: realistic-format extraction tests, a 200 to 300 File capacity test, queue-recovery tests, File-state tests.
- Performance: measured through the deployed application with the three timings in Q13, not only locally.
- Demo: budget-exhausted state, rate limit, and isolation from Owner data tested separately.
- Continuous integration (small and early): essential backend and frontend checks listed in `CODING_STANDARDS.md`; paid evaluation excluded.

## Out of Scope

Not approved for v1 (Future):
- Public multi-Owner SaaS, public signup, subscriptions, payments, billing, complete onboarding. A launch of that kind would first need the Google authorization-review research confirmed (Unverified, below) and its own ADR.
- Automatically initiated sync of any kind: scheduled, on-open, or unprompted background sync. (An operation the Owner explicitly started may still run in the background.)
- Any Drive write capability.
- Scanned-PDF OCR (image OCR stays best effort).
- Additional model providers.
- Enterprise infrastructure: distributed queues, autoscaling, standing staging environment, monitoring platforms, dashboards, alerting, extra paid backups, restore drills, disaster-recovery documents.
- Visitor-supplied API keys (investigation only).
- Capacity beyond about 200 to 300 supported Files; Urdu-script extraction guarantees.
- Final visual polish (after functional UX).
- Rigid maintenance schedules and key-rotation schedules.

## Further Notes

### Provisional milestones (a starting point, not a roadmap)
Milestones M0 to M10 are **provisional**. They will be revised after the M0 audits, and tickets are not created from them until this spec is approved and `/to-tickets` is run. Before any milestone starts: audit the relevant code and behavior; record what works, what is defective and what is missing; define measurable acceptance criteria; avoid redundant work and rewrites; consider dependencies (retrieval, grounding, calculations, ingestion, security); address critical security risks early.

| M | Scope | Depends on |
|---|---|---|
| M0-SEC | **Complete (2026-11-22).** Minimal security hardening that the M0 audit proposed and the Owner approved: Owner mandatory in every credential service (KI-031), fail-closed sign-in allow-list with immediate effect on removal, persistent paid-question quota and input caps, login-start prune and limit (KI-032), `Origin` and CSRF on normal-mode `/chat`. Spec `docs/specs/m0-sec-security-hardening.md`, tickets `docs/tickets/m0-sec-security-hardening/`. Deferrals are owned below and in the M9 gate | M0 |
| M0 | Read-only audits (execution paths, flags and deployed configuration; privacy implementation; conversation sufficiency; preparation and file-state UI; security triage that separates real vulnerabilities from scalability concerns) plus a small early continuous-integration foundation (backend and frontend checks). Fix critical security findings promptly (for example the first-credential fallbacks) rather than waiting. | none |
| M1 | Evaluation foundation: frozen set, real-format files, held-out split, grader validation, baseline of the tool agent as configured for production | M0 |
| M2 | Retrieval quality (KI-022, KI-027, KI-030; verbose queries; identifiers) | M1 |
| M3 | Grounding and honest answers: Missing information versus Retrieval failure, named-file rule (KI-028), Supported-answer checking, citation correctness, prompt-injection resistance | M1 |
| M4 | Conversations and follow-ups | M0, M1 |
| M5 | Verified calculations (KI-029), if M1 confirms the need | M1 |
| M6 | Preparation and ingestion: real-format verification, selection and exclusions, queue recovery, file states, 200 to 300 file test; **from M0-SEC ticket 03: the worker check that a queued indexing job's account is still on the sign-in allow-list when the job runs** (a deferral, not a guarantee; re-verified at the M9 gate) | M0 |
| M7 | Security and data control: session validation, isolation tests, Disconnect, Revoke and live deletion (the paid-question ledger table is covered by Delete stored data). Per-user quota management for future beta testers (smaller individual allowances, overrides, admin) starts only after ownership isolation is verified here | M0 |
| M8 | Application experience (includes, from M0-SEC ticket 06: Owner-mode HTTP 429 wording and use of `Retry-After`; stream client handling of a non-200 start (404, 401, 429, 503) and of in-stream error events (a reservation-time 409 or the replay-vanished abort arrives as an SSE `error` on a 200), verify first; a short client wait instead of the long concurrent-limit `Retry-After`; **fix before beta**) | M3, M4, M6 |
| M9 | Release and demo: expanded CI, model selection and pinned identifiers, hosting verification and migrations, promotion to `main`, disable normal production access to legacy paths, demo with spend cap, basic logging and cost (including the deferred log-text items: unhandled-exception text, provider error text in the offline indexing log, `/docs` exposure); **the M9 gate from M0-SEC (below) before any redeploy with sign-in on** | M1 to M8 |
| M10 | Controlled cleanup: physically remove unused legacy code | M9 |

#### The M9 gate (from M0-SEC, recorded 2026-11-22)

Before any redeploy with sign-in on, all of these hold. None can be checked from the repository; each is an Owner or hosted check, and each stays **Unverified** until done.

1. **Limits recalibrated from M1 data:** 20 per hour, 50 per day, 1 concurrent, the 300 s lease, the execution bounds and the body caps are provisional guesses. A request count is not a dollar amount and not a count of provider calls.
2. **Deployment-only list verified:** Google consent-screen state and test users (an outer control; the allow-list is the authorization model); hosted flag values; encryption keys and backups; `FRONTEND_URL` and cookie settings matching the real hosts (the exact public origin, a `__Host-` prefixed cookie, a host with no untrusted sibling subdomains or apps, a proxy rewrite that is the only path to the backend and adds no CORS headers, no cross-origin caller of `/chat`); proxy and edge limits, including a read timeout for slow request bodies and per-IP limiting of the login start; migration `20261121_1200` applied on the hosted database; the quota settings present and the application starting with the lease validator accepting them; the database connection pool size checked against admit, finish and release each taking a connection beside the request's own; the claim-check setting; platform logs and retention.
3. **Practical provider spending safeguards verified:** a project usage budget and usage alerts in the provider dashboard. They are safeguards, never guaranteed hard spending caps. The demo spend cap (ADR 0002) is separate.
4. **Deferred logging items done in M9** (listed in the M9 row).

Also re-verified at the gate: the allow-list deferrals of M0-SEC ticket 03, as **deferrals, never guarantees**: (a) a turn already running when an address is removed may finish within its bounded execution window; (b) queued indexing jobs are not cancelled when an address is removed, the worker check being assigned to M6 and re-verified here; (c) the stored e-mail is refreshed only at sign-in. And, if more than one worker or replica is planned, the multi-replica checklist: lease against the execution bounds, connection pool size, clock agreement between hosts (the ledger uses the application clock), and that the login-start limiter is process-local.

Future requirement, not built: per-user quota management for beta testers (M7 first).

Priority 6 items are unscheduled. A checkpoint for the `gpt-5.4-nano` replacement belongs inside M9 and must fall well before 2027-04-01.

### Status ledger: existing functionality, defects, unverified assumptions

**Verified (existing functionality)**. The *Basis* column says what kind of evidence supports the fact and how far it reaches.

| Fact | Basis and evidence |
|---|---|
| The tool agent registers four tools: `files_query`, `resolve_file`, `search_knowledge`, `file_evidence` | Code: `backend/app/agents/tool_rag/registry.py` |
| The tool agent is off by default in code; the Owner reported it on in the (now offline) hosted environment | Code: `TOOL_RAG_AGENT_ENABLED` defaults to false in `backend/app/core/config.py`. Hosted value: Owner-reported on, 2026-11-21 (M0 ticket 01); nothing is deployed |
| Three answer paths exist: linear hybrid (default), LangGraph (`AGENT_GRAPH_ENABLED`, default false), tool agent | Code (configuration defaults) and repo doc (`AGENTS.md`) |
| Claim check, the one-retry citation fix (KI-026) and name-lookup recovery (KI-025) exist | Repo doc (`docs/KNOWN_ISSUES.md`, `docs/DECISIONS.md`), with tests named there; not re-run in this session |
| The file-status enum is `discovered`, `indexing`, `indexed`, `failed`, `skipped`; it has no `unsupported`, `outdated` or `excluded` value. A name search for an exclusion feature found no persisted exclusion, which does not prove none exists | Code: `backend/app/db/enums.py` (enum); name search (limited) |
| Modified date is exposed in the file and source schemas | Code: `backend/app/schemas/file.py`, `backend/app/schemas/source.py` |
| Sync discovers the whole Drive for supported types; folder-level selection in the UI is unconfirmed | Repo doc (`AGENTS.md`); not re-checked |
| An application-session logout that revokes the session exists; a credential-encryption module exists, and credentials are stored encrypted-only (no plaintext columns; unconfigured encryption fails closed) | Code and test: `backend/app/api/google_session_auth.py`; `backend/app/security/google_credential_crypto.py`; `tests/security/test_encrypted_only_credentials.py` (M0 ticket 04) |
| The Settings page shows no Disconnect control and links to Google's permission page. This describes the frontend only. It does **not** show that no backend disconnect or delete-all-data implementation exists, and a name search of the backend routes found none by those names, which is not proof of absence | Test: `frontend/components/settings/settings-drive-section.test.tsx`; limited name search |
| Single conversations can be deleted through the API, but the delete only hides the conversation (`deleted_at`); turns and the linked query history remain | Code: `backend/app/api/conversations.py`; test: `tests/security/test_conversation_deletion_privacy.py::test_conversation_delete_keeps_every_row_today` (M0 ticket 07) |
| One free CI workflow exists, `.github/workflows/ci.yml`, verified only by running its commands locally; it has not run on GitHub. It runs no PostgreSQL or Qdrant tests and deselects four tests that fail on a clean checkout | Code: `.github/workflows/ci.yml`; local run (M0 ticket 08) |
| The container start script runs no migrations | Code: `backend/deploy/start.sh` (comment and content) |
| The latest migration file is `20261121_1200` (the paid-question ledger, M0-SEC ticket 05) and `EXTRACTION_PIPELINE_VERSION` is 3 | Code: `backend/alembic/versions/`, `backend/app/ingestion/pipeline_version.py`. Hosted database revision: Unverified |
| `feature/v2-state-performance` was 164 commits ahead of `main` when M0 ticket 01 checked (2026-11-21; the count grows with each commit), and `main` is its ancestor. A fast-forward is possible by history alone; whether it is safe is a separate audit | Git comparison, M0 ticket 01 |
| The demo configuration has a global request-rate limit and a concurrency limit. A spend cap and a per-Visitor limit were not found in the configuration or by name search; the interview reported the limiter as in-memory. Absence is not proven | Code (configuration only, not a full code audit) |
| Default chat model `gpt-5.4-nano`, claim-check model `gpt-5.4-mini`, embedding model `text-embedding-3-small` | Code: `backend/app/core/config.py`. Hosted values: Unverified |
| M0-SEC verification (2026-11-22, `d117df0` plus ticket 09): backend 3245 tests, one full run `5 failed, 3233 passed, 1 skipped, 6 xfailed` (one fixed test defect and four indexing probe timeouts under machine load; the three affected files rerun alone: 125 passed); container-free subset `2313 passed, 929 skipped, 2 xfailed`; frontend 876 passed, lint and build pass; basedpyright 48 errors in `tests/`, none in `app/`. The qualified baseline: pass in the right environment, not one clean run | Local run, M0-SEC ticket 09; details in `AGENTS.md` ("Latest recorded verification"). The earlier M0 baseline on `7197af4` (2927 tests) is in `docs/tickets/m0-system-audit/02-test-baseline-and-classification.md` |
| Baseline: tool agent 75/94 and legacy pipeline 74/94 on the 2026-11-19 set (statistically tied). Sequential latency on 20 cases: tool agent median 4.4 s, 90th percentile 8.05 s. With the claim check on, over 94 cases: median 5.2 s, 90th percentile 7.8 s | Historical measurement, `docs/EVALUATION_RESULTS.md`: one corpus, one model, an earlier build; not production figures |

**Defects** (registered in `docs/KNOWN_ISSUES.md` unless noted)
- KI-022: wordy search queries find nothing (partly fixed; the keyword search and query-writing parts are open).
- KI-027: an identifier plus generic words can miss the right File.
- KI-028: a named thing that does not exist is answered from a similar thing that does.
- KI-029: sums over table rows can be wrong (for example 33,100 or 33,200 instead of 34,900).
- KI-030: a small multi-slide deck becomes one chunk and loses in search.
- KI-031: fixed by M0-SEC tickets 01 and 02 (2026-11-21): every service that acts on a Google credential requires an explicit Owner. See the registry, Fixed.
- KI-032: fixed by M0-SEC ticket 07 (2026-11-21): expired login attempts are pruned at login start and the endpoint is rate-limited (global, process-local). See the registry, Fixed.
- KI-033: an owner who has submitted a question cannot be deleted from `users`.
- Found by the M0 audit, no registry entry (no reproducing test): the claim check fails open (M3). The Owner-mode limits and `/chat` CSRF items were closed by M0-SEC (registry, Fixed). Frontend items for Owner-mode 429 wording and stream handling are M8, fix before beta.

**Unverified (do not state as fact)**
- Hosted state: nothing is deployed (all services offline, Owner-reported as intentional). Hosted flags are Owner-reported only; the deployed commit, branch, migration revision and managed-backup status of the removed deployment were not read (the environment will be rebuilt).
- Whether a backend Disconnect or delete-all-data flow exists: M0 ticket 07 searched the route list, the code, the migrations, the operator tools and the frontend and **found none**; a null search is not proof of absence.
- Hosted encryption keys, their custody and backups, and plaintext in historical backups. (Credentials are stored encrypted-only in the code, and unconfigured encryption fails closed: Verified by M0 ticket 04.)
- Google authorization status: the Owner reported External, Testing, 4 test users and 6 lifetime users (M0 ticket 01, Owner-reported). Whether the restricted read-only Drive scope needs verification and an annual third-party assessment, the 100-user cap and 7-day tokens in Testing mode still came from unconfirmed research.
- The provider's data usage and retention policy; whether `text-embedding-3-small` is deprecated (not in the part of the deprecations page read verbatim); the `gpt-6-luna` model page.
- Real cost per question and real latency through the deployed application. The figure of about $0.003 per question came from the interview and was not located in the repository documents during this review. The 5.2 s median is the claim-check-on median in `docs/EVALUATION_RESULTS.md`, a historical measurement. Neither is a production measurement.
- Whether conversation history is sufficient for follow-ups.
- Whether the hosted demo uses a database separate from Owner data (the code relies on it; ADR 0002).
- Real Google Doc, Google Sheet and Excel-saved file extraction (only generated fixtures were tested).
- The full container backend suite on the current HEAD (last run on `7197af4`) and the CI workflow on GitHub.
- Whether the stream currently sends a first status event within 2 s.

### Workflow (Q28)
Grill, glossary, a small number of ADRs, spec, review and approval, `/to-tickets`, implementation with tests, independent `/code-review`, `/retro`. `docs/DECISIONS.md` stays the engineering and evaluation history. Tickets and specs follow the tracker configuration in `docs/agents/`. The Owner commits; skills do not.

### Related documents
`GLOSSARY.md`; `docs/adr/0001-single-answering-path.md`; `docs/adr/0002-public-demo-isolation.md`; `docs/KNOWN_ISSUES.md`; `docs/EVALUATION_RESULTS.md`; `docs/DECISIONS.md`; `CODING_STANDARDS.md`; `AGENTS.md`.
