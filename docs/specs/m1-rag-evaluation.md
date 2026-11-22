# M1: RAG Evaluation Foundation

Draft of 2026-11-22, for Owner approval; no ticket has started. Refines the M1 row of `docs/specs/drivemind-v1-product-definition.md` (the Quality gates and Models sections are its parents). Terms follow `GLOSSARY.md`; decisions follow `docs/adr/0001-single-answering-path.md`. Labels (Verified, Defect, Unverified, Future) and evidence types have the meaning given in the v1 spec, "How to read this spec". This repository is public: nothing here contains secrets, private Drive content or real file names; the evaluation corpus is synthetic or public and every example is invented.

## Problem Statement

DriveMind's goal is a highly accurate, reliable and efficient answering system with the simplest effective architecture. Today there is no trustworthy way to say how accurate it is, or whether a change made it better:

- The production answering path (the tool agent, ADR 0001) was last measured at 75 of 94 cases on 2026-11-19. Many changes landed afterwards (cut-off, crowding, tool wording, name-lookup recovery, citation retry), each measured on a different subset on a different day, and no single current number exists for the build as it stands.
- The question sets were written by the same process that tuned the system against them. The "test" splits were used as vetoes and two of their cases were edited after a result was seen. They no longer measure generalisation.
- Scoring checks that required facts appear and that the right *file* was cited. It cannot see an invented extra claim written beside a correct fact, a citation that points at the wrong passage of the right file, or a hallucination in a refusal. The one LLM judge sees only the reply, and was never compared with a human.
- Per-question cost, model-call count and latency are not recorded per case. The M0-SEC quota limits (20 per hour, 50 per day) are guesses until these exist.
- The corpus is small and mostly short text files: one chunk per file, five generated Office or PDF files, no Google-exported files, one document carrying an embedded instruction, no ambiguous questions.

Milestones M2 (retrieval), M3 (grounding), M4 (conversations) and M5 (calculations) each need a measuring instrument they can trust and a baseline to beat. Without M1 they would repeat the pattern recorded in `docs/DECISIONS.md`: fixes tuned and judged on the same few questions, with side effects found late.

## Solution

Measure first, change nothing. M1 builds the instrument and records the baseline; it changes no answering behaviour.

1. **Reuse the existing harness.** The isolated evaluation store, the case schema and verbatim-quote validator, the deterministic scorer with Wilson intervals, the spend meter with a hard cap, the retrieval and first-step probes and the planted-claims test stay. M1 extends them where the audit found gaps (Further Notes) and rebuilds nothing.
2. **One frozen question set, three roles.** A development pool that may be tuned against, a regression pool of the already-seen cases, and a new sealed held-out pool written before any baseline run and reported only as aggregates.
3. **A realistic corpus** across every promised format, with longer multi-chunk documents and several documents that carry embedded instructions.
4. **Layered measurement**: retrieval, answer correctness, grounding (unsupported claims), citation correctness, abstention, and performance (latency, calls, tokens, cost). Everything that can be decided by code is decided by code; one LLM grader covers only claim-level support, and it is trusted only after its agreement with Owner-labelled examples is measured.
5. **A baseline of the production path** with confidence intervals, repeat-run stability, a per-case failure-cause breakdown and real per-question cost and latency, plus a small legacy-path comparison where it informs a simplicity decision.
6. **A ranked, evidence-backed input list for M2, M3, M4 and M5**, with no redesign proposed inside M1.

## User Stories (engineering outcomes)

1. As the Owner, I can run one command and get the current accuracy of the production path with honest error bars, and know what the run cost before and after.
2. As a maintainer starting M2 or M3, I get a committed baseline with per-case outcomes, so a change is judged by a paired comparison on the same cases, not by memory of an earlier run.
3. As the Owner, I know a held-out number that nobody tuned against, and I know when it stops being clean.
4. As the Owner, a hallucinated sentence next to a correct fact, a citation to the wrong passage, and an invented value in a refusal are each counted and attributed, instead of passing quietly.
5. As the Owner, I know how many model calls, tokens, dollars and seconds a typical and a worst-case question costs, so the quota limits can be set from data (the M9 gate).
6. As the Owner, every automated verdict I rely on has a stated, measured agreement with human labels.
7. As the Owner, a failed case is traced to a cause (extraction, retrieval, agent behaviour, generation, grounding, citation, abstention), so M2 to M5 work on measured weaknesses.
8. As the Owner, no paid run starts without a stated estimate, a hard cap and my approval.
9. As a future maintainer or agent, the harness, datasets and corpus are documented and tested for free, and I can tell free tests from paid runs by their commands.

## Implementation Decisions

No file paths or code snippets in this section. Evidence pointers are in Further Notes and in the tickets.

### Boundaries

- M1 is measurement. No change to prompts, tool descriptions, retrieval settings, thresholds, the claim check, models or any file under the application package. Every ticket's acceptance includes an empty diff of the application package. A harness defect found during M1 is fixed in M1; a product defect found is registered (registry entry whose reproduction is the named evaluation cases, the precedent of KI-027 to KI-029) and handed to its milestone, never fixed in M1.
- No Railway access, push, deploy or real Google call by any ticket. Provider calls happen only in the paid steps named in the tickets, each with a stated estimate and cap, each approved by the Owner when it starts.
- No new dependency or external service is planned. Anything that turns out to need one stops the ticket for an Owner decision.
- The legacy linear and LangGraph paths are not changed. They are measured once, on a sample, as a simplicity comparison (below).
- M1 does not decide pass or fail against the v1 quality gates. It reports the distance, with intervals. The gates are judged at the end of M2/M3 and at M9.

### What is evaluated: the production path

The unit under test is the question-answering service entry shared by the plain chat endpoint, conversation turns and streaming turns, run with the tool-calling agent switched on, hybrid retrieval, the claim check on (the code default at the audited commit; whether it stays on is an M3 decision), the default models and retrieval settings of the audited commit, and persistence off. Every run records the full flag and model set, so a configuration drift is visible. A free test pins the evaluation settings to the application defaults except for an explicit allow-list (store location, demo off, tool agent on), so the harness cannot silently measure something other than what a rebuilt deployment would run.

The streaming turn path uses a different agent call (no automatic retries) from the non-streaming call the harness uses, with the same prompts and tools; the "shared entry" is shared in everything except that call. What this does not cover, stated so it is not mistaken for coverage: streaming transport and time to first status (M8, M9, measured on the deployed application), conversation-history assembly and the turn table (M4; M1 only checks that case histories respect the production bound), quotas and sessions (M0-SEC tests), Drive sync and Preparation (M6), real Google calls.

### Measurement layers

| Layer | Question | Method | Cost class |
|---|---|---|---|
| Extraction precondition | Is every fact a question needs present in the text the product extracts? | Verbatim anchor check against the product's own extractors (already enforced by the dataset validator) | free |
| Retrieval | Is the passage that holds the answer among the retrieved chunks? | Anchor-to-chunk mapping in the evaluation database; recall and rank, from (a) the question as the query (upper bound, embeddings only) and (b) the queries the agent really wrote, recorded during the answer run | embeddings only, then free |
| Answer correctness and completeness | Are all required facts present and no forbidden claim asserted? | Existing fact matching, extended with a fact-recall fraction for partial credit | free |
| Citation correctness | Does every citation resolve, to the right file, to the supporting passage? | Resolution and ownership check of every cited chunk; file-level and chunk-level match to the anchor; citation precision | free |
| Grounding | Does the answer assert anything the cited text does not support? | A cheap deterministic screen (numbers and identifiers not in the cited text, the question or the history) plus one LLM claim-support grader, validated against Owner labels | screen free, grader paid |
| Abstention | Does it say "not in your Files" when it should, and never when it should not? | Existing forbidden-value matching plus the existing refusal judge, re-validated against Owner labels; explicit false-abstention and fabrication rates | judge paid, small |
| Multi-document and hard questions | Does it find and combine several Files, tables, calculations, versions, identifiers, injections? | Same scores reported by category and format; number of searches per case from the recorded trace | free |
| Performance | Latency, calls, tokens, cost per question and per role | Per-case metering and wall time; latency from a separate sequential run | paid, small |
| Stability | Do results repeat? | Repeat runs on a stratified sample; per-case flip rate | paid |

### Headline metrics

Two pass definitions are reported side by side. The **legacy pass** equals the existing definition (facts present, none forbidden, the right file cited, judge agrees for non-answers) so that history stays comparable. The **strict pass** has two parts, reported separately. *Deterministic strict* (computable on every run and repeat): for answerable cases, every anchor chunk of the case is among the cited chunks, the number of cited files outside the expected ones is within a stated bound (so citing everything retrieved does not pass), citation integrity holds and the unseen-value screen is clean; for non-answer cases, no forbidden or unseen value and no code-detectable Critical failure. *Graded strict*: deterministic strict plus no unsupported claim by the validated grader, which is run once at the baseline, so repeats and later paired comparisons use deterministic strict only unless a grader run is paid for. Both are tracked against the v1 gates.

- Answerable questions: correct, correct and cited, strict.
- Unanswerable, partial and false-premise questions: correct abstention, false abstention on answerable questions, fabrication on unanswerable ones.
- Critical failures (glossary definition): count over the dedicated critical set and over every other case; the target is zero. Zero failures in 30 cases still leaves an upper bound near 11 percent (near 28 percent for 10 held-out cases), so M1 reports counts and bounds and does not call the target met.
- Retrieval: anchor-passage recall and rank, file recall, distinct files per result.
- Everything is reported per pool: the old development cases, the old test cases (now regression), the new development cases and the held-out total; a pooled headline overstates, because the first two were tuned against. Stability in the v1 sense (zero crashes in three complete runs) is not measured by M1's one full run and two sample repeats; M1 reports errors per run only.
- Performance: median, 90th percentile and maximum latency; calls, tokens and estimated dollars per question, per role (intent gate, agent step, claim check, embedding, grader, judge); request failures.
- Stability: errors per run, per-case flip rate across repeats.

### The frozen question set

- **Three roles.** *Development pool*: the existing development cases plus new cases written in M1; may be tuned against and inspected freely. *Regression pool*: the 81 existing "test" cases, relabelled at load time (their files are not edited). They were read and used as vetoes, so they are no longer held-out; they are run in every comparison and never presented as evidence of generalisation. *Held-out pool*: at least 100 new cases written in a separate session before any baseline run, by an author that has not seen any result. It is sealed.
- **Sealing rule (enforced by files, not only by policy).** The held-out case file lives outside the working tree, at an Owner-local path given by an environment variable; the repository holds only its checksum, its counts per gate group and the amendment log. The freeze test verifies the checksum when the file is present and skips otherwise. The default "all" selection excludes held-out; it runs only when asked for by name. Per-case held-out rows are written outside the repository and without reply text; summaries, logs and the committed baseline show the held-out pool as a total plus the gate groups, and suppress any cell under ten cases (so a small category cannot disclose a single case). The held-out pool is run only at checkpoints (M1 baseline, end of M2, end of M3, M9), and **once** per checkpoint: not in repeats, not in probes with repeats. If a held-out case must be diagnosed (which means reading it), it moves to the development pool with an amendment-log entry and stays in the denominators of earlier checkpoints; if the count then falls below its minimum, new cases are written in a later clean session. There is no reserve and no reveal switch. Held-out results are compared unpaired between checkpoints, so at 100 cases only a difference of roughly 13 points is detectable; the development-versus-held-out gap is reported with its interval as information, and a gap above 10 points is a prompt to look at development-side causes, not a verdict, because investigating it by reading held-out cases is a burn. Leakage the mechanism cannot stop: the corpus documents are visible to everyone who reads them, so tuning on development questions about shared documents can help held-out ones; this is stated as a limit, and the long invented documents are split so that some are used by held-out questions only.
- **Written before the fix.** Cases for a defect are written and frozen before the change that fixes it (existing rule, kept). A case is never edited after a result was seen except to correct a proven gold error, recorded in the amendment log with both checksums (precedent: the invoice cases).
- **Authoring.** Cases are written from the documents, with a verbatim anchor quote per supporting fact, reference answer and forbidden-claim list, never from system output. The existing validator rejects a case whose quote is not in the extracted text or whose forbidden claim is actually present. Provenance (author session, date) is recorded. The Owner reviews a sample of the held-out pool (default 30 cases).
- **Coverage minimums**, enforced by a free validator that prints the counts: at least 300 cases in total, of which at least 100 held-out; unanswerable, partial and false-premise at least 80 (30 held-out); tagged Critical-failure cases at least 30 (10 held-out); multi-file at least 25 (8); table lookup at least 25; calculation at least 20 (6); identifier at least 25 (6); follow-up at least 15 (5), each with a history inside the production bound; ambiguous (a short clarifying question is the correct reply) at least 10 (4); prompt injection at least 10, spread over at least 3 documents and 2 formats (4 held-out); at least 8 questions whose evidence lies in each of DOCX, XLSX, PPTX, text PDF, Markdown, CSV and TXT (3 each held-out). Roman Urdu is reported separately and is not gated. These minimums are derived from the v1 required question types and gates; the Owner may adjust them at approval.
- **Statistical honesty.** At about 90 percent accuracy, 100 cases give an interval of roughly plus or minus 8 points; 60 cases at 95 percent leave a lower bound near 86 percent. M1 therefore reports the gates with their intervals and does not claim a gate is met from a single pool. The held-out pool is the overfitting check: the gap between development and held-out rates is reported with its interval, and a gap above 10 points triggers an investigation, not a verdict.

### The corpus

- Keep the existing synthetic company files, the public documents (fetched and checksum-verified, never committed) and the five generated Office and PDF fixtures. Add: generated fixtures in every promised format (DOCX, XLSX, PPTX, text PDF, Markdown, CSV), several longer multi-chunk documents with invented content so a model cannot know the facts from training, near-duplicate and superseded versions, and at least three documents with embedded instructions in at least two formats. Invented facts are preferred for held-out cases because public documents may be in a model's training data.
- **Google-native files.** Google Docs, Sheets and Slides reach the product as exported DOCX, XLSX and PPTX. The v1 spec asks for real Google-created files. Default: the Owner creates three small synthetic files in a throwaway Google account, exports them through the normal menus, and the exports are committed as checksum-pinned fixtures. No agent calls Google. If the Owner declines, M1 proceeds with generated stand-ins and records "Google-exported files not covered"; the gate row stays open.
- The corpus is frozen by a manifest with a version id recorded in every run. One index holds the whole frozen corpus, so every pool is answered against the same distractors; the older results are historical, not comparable.
- Extraction fidelity as such (does a reader keep every table row) belongs to M6. M1 adds enough formats that the baseline exposes format-specific answer failures, and hands extraction defects to M6.

### Grader policy and validation

- **Deterministic first.** Fact matching, forbidden claims, citation resolution and match, the unseen-number screen, behaviour matching for chitchat and inventory, and failure-cause assignment need no model.
- **One LLM grader for claim support.** It receives the question, the reply split into numbered statements by one deterministic splitter (the same numbering is shown to the Owner), and the cited chunks keyed to the citation markers they back, so attribution is checked per marker. It returns a verdict per statement (supported, unsupported, contradicted, not a claim) and a Critical-failure flag with a reason. The primary metrics are reply-level: any unsupported statement, and Critical. It is a different run from the answering model and, by default, uses the mid-size model already used for the refusal judge. That model is also the claim checker's model, so their mistakes may correlate; the human labels are the safeguard. A stronger grader is tried only if the default fails validation, and only with separate Owner approval of the extra spend.
- **The existing refusal judge stays** and is validated by the same procedure, because it also never met a human label.
- **Calibration set.** About 80 blind items drawn from pilot replies, hand-written subtle cases and planted variants (the existing planted-claims builder: an invented sentence, a changed number, a flipped meaning, a wrong subject, a claim of absence), at least 30 of them truly unsupported, plus about 40 refusal replies if the judge is validated in the same pass. The Owner labels each item without seeing the grader's verdict. Reported: accuracy, precision and recall for the unsupported class, **specificity on the real supported replies**, precision adjusted to the realistic prevalence (real unsupported claims are rare, so precision measured on a half-planted set overstates it), **recall on the real and hand-written subtle items separately from the planted ones**, Cohen's kappa, each with an interval, and the grader's agreement with itself on a repeat. A lock-box of at least 20 further labelled items is built for any revision, and the Owner relabels 15 to 20 items after at least a week to estimate their own consistency (one human is the only reference). The refusal block includes the "clarify" behaviour.
- **Acceptance rule (default, approved by the Owner when the data exists).** Used directly at scale if, on the calibration set, recall of unsupported or Critical items is at least 0.90, precision at least 0.80 and kappa at least 0.70 (point estimates with intervals shown; with about 30 positives the interval around 0.90 recall is roughly 0.74 to 0.97, so acceptance is a judgement the Owner makes on the intervals, not an automatic pass). Otherwise it is advisory: it nominates suspects and the Owner adjudicates every flagged answer. In either case the baseline carries a blind spot-check of 20 answers by the Owner, drawn partly from answers the grader passed and partly from ones it flagged, reported as continuing agreement (it cannot estimate recall by itself). The grader, the claim checker and the refusal judge share one model family (the judge's model is fixed in code); their errors may be correlated, and this is reported as a limit. The v1 spec leaves the threshold to M1's data; these numbers are a proposal, not a fact.

### Baseline matrix

All runs use the audited commit, the frozen corpus and the frozen set. Paid steps are listed with estimates in Further Notes.

1. Full run of the production path over the whole frozen set (about 370 cases), once, with the grader on every reply that carries a citation or makes a factual claim.
2. Two more runs of a stratified sample of about 90 development and regression cases (held-out excluded, so it is seen once per checkpoint) for repeat stability and per-case flip rate.
3. A sequential latency and cost run on about 40 stratified cases, three repeats, so latency is not distorted by parallel load (earlier parallel runs showed provider stalls that did not recur alone).
4. Legacy linear path, one run on the same sample, as a simplicity comparison. The earlier comparison was a statistical tie with a higher latency for the agent; the new set decides whether the agent loop earns its extra calls. It is a comparison only; ADR 0001 stands and no legacy path is improved.
5. Optional, default yes if the budget allows: the same sample with the claim check off, to quantify its cost, latency and accuracy effect for M3.
6. Not in M1 unless the Owner asks: a second chat model column. Model selection and the chat-model shutdown checkpoint belong to M9; the harness takes the model as a parameter so that run costs one extra baseline.

### Cost controls

- Free tests never reach a provider and never need a key; a test fails if a paid code path is reachable without the key. Paid commands are separate named commands, never part of the test suite or CI.
- Every paid command requires an explicit cap (no default) and has a dry-run that prints the planned number of calls and an estimate from measured per-case cost, and refuses to start when the estimate exceeds the cap. The meter stops further calls at the cap. Each ticket states its estimate and cap and the Owner approves the spend when the ticket starts.
- Cheap probes (embeddings only, one model call per question) come before full runs; full runs are used only to answer questions the cheap probes cannot.
- The grader runs once on the full baseline run, not on every repeat.
- Spend is estimated from token counts at the recorded price table (with its date), which can differ from the bill (billing lags; client retries below the meter are invisible). A run's meter total is compared with the provider usage page when the Owner can read it, and any discrepancy is recorded, not gated.

### Statistics and comparisons

Proportions use Wilson intervals; latency and cost percentiles use a bootstrap interval; two configurations on the same cases use a paired exact test on the cases that differ; repeat runs report per-case pass rate and the share of flaky cases. A difference of one or two cases between single runs is noise (documented 50 of 94 replies differed between identical runs). M2 and M3 decisions use at least three repeats on the cases a change can move, a development-pool result, a regression-pool result and one held-out check at the end.

### Results are recorded

- Each run writes a manifest: audited commit and whether the tree was clean, every flag and model identifier, retrieval settings, prompt and tool-description digests, corpus and dataset versions and checksums, price-table date, concurrency, repeat index, library versions, cap and spend.
- A compact committed baseline file holds, per development and regression case, the outcome fields, cited files, call counts, tokens, cost and latency (no reply text). Held-out per-case rows are never committed; their aggregates are. This is what makes a paired comparison possible in M2 and M3.
- The existing evaluation results log receives the readable summary, newest first, in its existing style. The older entries stay as history.

### What M1 does not do: the M2, M3, M4, M5 boundary

| Later milestone | M1 supplies | M1 does not do |
|---|---|---|
| M2 retrieval (KI-022, KI-027, KI-030) | Anchor-passage recall and rank on the real agent queries and on the question as the query; the share of failures caused by retrieval | Change thresholds, chunking, query writing or fusion |
| M3 grounding (named-file rule KI-028, Missing information versus Retrieval failure, Supported-answer check, claim-check fail-closed, injection) | Unsupported-claim, wrong-subject, absence-claim and Critical-failure rates; claim-check cost, latency and effect; the validated grader | Redesign the claim checker or the named-file rule |
| M4 conversations | A follow-up and ambiguous slice with histories inside the production bound; baseline per category | Change history handling or test the turn table |
| M5 calculations (KI-029) | The calculation slice's failure rate and its cause (extraction, retrieval, arithmetic); the evidence for M5's yes or no | Build a calculation capability |
| M6 preparation | Format-specific failures that trace to extraction | Verify extraction or capacity |
| M9 release and quota gate | Per-question cost and call distribution by role, latency distribution, and the numbers behind a recalibration of the quota limits | Set the limits, choose the production model, measure the deployed latency |

### Owner decisions

Genuine decisions, with defaults. None blocks tickets 01 to 06, which are free and need no Owner time. Decision 3 (Google exports) and the held-out review in decision 2 involve Owner time in tickets 04 and 07 but never block them from resolving. Only decision 1 must be answered before the first paid step (ticket 08).

1. **Paid budget for M1.** Default: expected spend about 4.5 USD, cap 6.0 USD (a 30 percent contingency on the uncertain steps) across tickets 08, 09, 11 and 12, plus up to 1.3 USD for a stronger grader only if the default grader fails validation and the Owner approves it then. A lean variant (one full run with the grader, no repeats, no legacy comparison, no ablation) is about 3.3 USD. The Owner must read the real balance on the provider dashboard before ticket 08 and before ticket 11; the assistant does not know it. The earlier credit rule (never go negative, stop at 3.5 USD since the 2026-11-20 top-up, about 1.7 USD already used by 2026-11-20) was written for the retrieval work and does not cover M1; this decision replaces it for M1, and a top-up is likely.
2. **Owner time for human labels.** Default: about 80 calibration items (about 3 to 4 hours, two sittings, blind to the grader), a review of about 30 held-out cases (about 1 hour, ticket 07; ticket 11 waits for it), and a 20-answer spot check per baseline run (about 30 minutes). Fewer labels means wider intervals and a grader that stays advisory.
3. **Google-exported fixtures.** Default: the Owner makes and exports three synthetic Google files (about 1 hour, ticket 04), nothing else touching Google. Declining leaves the Google-file gate row open and says so.
4. **Held-out sealing policy.** Default: as written above (the held-out file kept outside the repository at an Owner-local path, which the Owner must back up because the repository will not hold it; checkpoint runs once each; totals and gate groups only; burn by moving to development). It changes how future sessions behave, so it needs approval.
5. **Optional baseline items.** Default: legacy comparison yes, claim-check ablation yes, second chat model no.
6. **Grader thresholds.** Decided at ticket 10 on the calibration data; the default above is the proposal.

## Testing Decisions

- **Free local tests** (no key, no network, no container where avoidable): scoring functions on hand-built rows; the meter and its role classification against a stub client; the manifest contents; the recording retriever; the dataset and corpus validators and the coverage counts; the freeze check; the production-equivalence pin; agreement statistics on a fabricated labelled fixture; the dry-run estimator. They live beside the existing evaluation tests and run in the container-free subset. New and changed harness modules are checked with the linter and strict type checker for the files touched (the evaluation package is not covered by CI today).
- **Container tests**: the anchor-to-chunk mapping and the recording retriever against the disposable PostgreSQL and Qdrant, using the existing conventions and no provider.
- **Paid runs** (separate commands, approved each time): retrieval probe with agent-written queries, pilot replies and grader trials, the baseline matrix, the latency run. Never in CI, never in the pytest run.
- **Verification before M1 closes**: the evaluation tests and the changed modules' checks pass; the application package diff is empty for the whole milestone; the full backend container suite is **not** re-run unless a ticket changed application or shared test code (it is not planned to); two independent reviews of the final documents and code.

## Out of Scope

- Any change to answering behaviour, prompts, tools, retrieval, chunking, claim check or models (M2 to M5, M9).
- Choosing the production chat or claim-check model, or the replacement for the retiring chat model (M9 checkpoint before 2027-04-01).
- Deployed-application latency, first-status time, concurrency and streaming behaviour (M8, M9).
- The Owner's own Drive questions (at least 20, counts only, outside the repository): an M9 gate item. The recording format is defined there, not here.
- Extraction and capacity verification (M6), the conversation turn table and history handling (M4), real Google API calls, scanned-PDF OCR, Urdu-script documents, image OCR (Future or best effort).
- Setting the quota limits (M9 gate; M1 supplies the data).
- Removing or consolidating the older harnesses (M10).
- A hosted or paid evaluation service, a dashboard, or CI for paid runs.

## Further Notes

### Audit of the existing M1 plan against the code (2026-11-22, HEAD `2b4cea8`)

There was no M1 specification or ticket. The plan consisted of the M1 row in the v1 spec, the M0 audit's section 8 additions (evaluate with the tool agent on and state every flag; record cost per question on both paths) and pointers in the M0-SEC spec (M1 measures cost, latency and call overhead; M1 may start non-application work early). Everything below was checked against the code in this session, by reading files and counting dataset entries; no provider was called.

| # | Finding | Label | Evidence |
|---|---|---|---|
| A1 | The v1 spec's reference point ("the existing set is 94 cases") is stale. Four case files hold **201 distinct cases** (120 development, 81 test; 135 answer, 40 not found, 10 partial, 5 decline, 5 chitchat, 4 inventory, 2 false premise); the CLI default loads only the 94-case file | Defect (documentation) | Local count over the four `rag_v2_*` dataset files |
| A2 | The "test" splits are not held-out. `docs/EVALUATION_RESULTS.md` records the test split used as a veto for a threshold choice, as a regression check after several changes, a test-split question replaced after its result was seen (`vi06` to `vi08`) and a gold answer corrected (`id10`) | Verified | repo doc, `docs/EVALUATION_RESULTS.md` |
| A3 | The harness runs the shared question-answering entry directly. It bypasses conversation-history assembly, streaming, quotas and the turn table. Follow-up cases pass a pre-built history | Verified | code: `evaluation/rag_eval/runner.py` |
| A4 | A result row keeps cited **file names** only. No chunk identifiers or snippets, no tool-call trace, no retrieved set, no tokens or calls per case. The meter attributes spend to a pipeline or "judge" label and a model, not to a case | Verified | code: `runner.py` (row fields), `meter.py` (label key) |
| A5 | The meter wraps the SDK's non-streaming create calls and records only successful responses. Failed requests are not counted, the SDK's automatic retries (default 2) happen below the wrapper, and a streamed request would not carry usage. Whether a retried failed request is billed is unknown | Verified (code); Unverified (billing) | code: `meter.py`; `docs/tickets/m0-sec-security-hardening/04-...` section 2 |
| A6 | Scoring is string matching of required facts and forbidden claims plus file-level citation match. A right file cited beside an invented sentence passes unless the sentence matches a forbidden string. Nothing checks that the cited *passage* supports the claim | Verified | code: `score.py`, `text.py` |
| A7 | The refusal judge sees only the reply (never the documents), is the same model family as the claim checker, and was never compared with a human label (the results log says so) | Verified | code: `judge.py`; repo doc |
| A8 | Run-to-run variation is large and documented (50 of 94 replies differed between two identical-code runs; one first tool choice was a coin flip at temperature 0), but the command line has no repeat option and no flip statistics; repeats were done by hand | Verified | repo doc; code: `cli.py` |
| A9 | Result files are git-ignored and only prose is committed, so no per-case baseline exists for a paired comparison | Verified | `evaluation/results/.gitignore`; `docs/EVALUATION_RESULTS.md` |
| A10 | A run's file records the chat model, datasets and two retrieval thresholds; not the commit, the claim-check flag and model, the embedding model, prompts, corpus or price-table version. The settings helper defaults the tool agent on (consistent with audit decision D5-2) but nothing pins it to the application defaults | Verified | code: `cli.py`, `target.py` |
| A11 | The evaluation package is outside CI's ruff, mypy and basedpyright scope (`app` and `tests` only); its tests are inside the container-free pytest run | Verified | code: `.github/workflows/ci.yml`, `backend/pyproject.toml` |
| A12 | The corpus: 22 short synthetic text files (mostly one chunk each), 33 public PDFs (git-ignored, fetched and checksum-verified), 5 generated files (DOCX, PPTX, XLSX, two PDFs). No Markdown, CSV, Google-exported, image or long multi-chunk invented document. Only one synthetic document carries an embedded instruction (three cases use it) | Verified | code and corpus listing |
| A13 | Coverage against the v1 required types: unanswerable plus partial plus false-premise 52 (target about 60 or more); no tagged Critical set; **no ambiguous cases and no behaviour for them**; follow-up 6 cases with a history (another 28 live in a separate provider-free harness); injection 4; calculation 13; multi-file about 16 | Verified | local count |
| A14 | The tool agent's adapter accepts an injected retriever, the agent's context accepts any subclass of the hybrid retriever, and the executor calls one `retrieve` method per search. A recording subclass can therefore capture every query the agent wrote and every chunk returned, with no change to the application. The agent's step count, tool names and outcome are already logged as one JSON line per question | Verified (code); to be confirmed by ticket 02 | code: `app/services/tool_agent_service.py`, `app/agents/tool_rag/agent_service.py`, `execution/executor.py` |
| A15 | The tool agent's result exposes only the answer, the citations and a retrieval count; the retrieved-but-uncited evidence is not exposed. Cited chunk text is recoverable from the evaluation database by chunk identifier | Verified | code |
| A16 | Older numbers predate several changes (cut-off, crowding, tool wording, KI-025, KI-026) and a larger corpus; the newest measurements are on subsets (88 dev cases 79, messy 39 cases 36, identifier 19 cases 16). No whole-set number exists for the current build | Verified | repo doc |
| A17 | The M0-SEC call-count tests give the minimum and maximum number of paid calls per path (tool agent: one to nine chat calls and up to forty embeddings per question). M1's measured counts should fall inside them; a count outside is a finding | Verified | test: `tests/test_paid_call_counts.py` (read in the M0-SEC ticket 04 findings) |
| A18 | Other harnesses exist and are separate generations: the 24-case Gold v1 runner with its trace, the 16-case agent smoke, the provider-free conversation runner (28 cases), the 83-case intent evaluation. They do not measure the production path end to end | Verified | code |

### Reuse map

| Existing piece | Decision |
|---|---|
| Isolated store setup, safety assertions, ingest through the real index build | Keep; extend for the new corpus |
| Case schema and verbatim-quote validator | Keep; add fields (Critical tag, format tags, provenance, ambiguous behaviour, held-out split) and the coverage report |
| Deterministic scorer, Wilson intervals, rate summaries | Keep; add fact recall, chunk-level citation, unseen-number screen, strict pass, paired and repeat statistics |
| Spend meter and price table | Keep; add per-case and per-role attribution, failed-call counts, per-request-shape role classification, dry-run estimate |
| Refusal judge | Keep; validate against humans before relying on it more |
| Retrieval probe and first-step probe | Keep; extend to anchor-chunk recall and the new corpus |
| Planted-claims builder | Reuse to create guaranteed-positive calibration items |
| Generated-fixture builder and corpus manifests | Keep; extend |
| Claim checker's own number-extraction step | Do not use to grade the checker (circular); a small independent screen is written for the harness |
| Gold v1 runner, agent smoke, conversation runner, intent evaluation | Leave untouched (M10 may consolidate) |
| Execution trace collector used on the legacy paths | Not used for the tool agent, which it does not instrument; the recording retriever and executor wrapping replace it there |

### Tickets and execution order

One ticket per fresh implementation session, numbered in dependency order, in `docs/tickets/m1-rag-evaluation/`. "Free" tickets need no key and no provider.

| # | Ticket | Blocked by | Cost | What it achieves |
|---|---|---|---|---|
| 01 | Run manifest, production-equivalence pin and CLI safety | none | free | Every run says what was measured; settings pinned to the application defaults; paid commands need a cap and a dry run |
| 02 | Per-case metering and trace capture | 01 | free | Calls, tokens, dollars by case and role; the agent's real queries and retrieved and cited chunks recorded |
| 03 | Deterministic scoring and failure attribution | 02 | free | Chunk-level citation, fact recall, unseen-value screen, strict pass, failure causes, paired and repeat statistics |
| 04 | Realistic corpus v1 | none (parallel to 01 to 03) | free | Every promised format, longer documents, injection documents, frozen manifest; Google exports as a non-blocking Owner action |
| 05 | Question set: loader, schema, coverage, freeze, sealing | 04 | free | Pools, coverage report, freeze and amendment log, aggregate-only held-out reporting |
| 06 | New development cases | 05 | free | Coverage gaps filled, Critical, ambiguous and follow-up cases, from documents only |
| 07 | Sealed held-out set | 06 | free (Owner review about 1 h) | At least 100 unseen cases, reviewed, sealed |
| 08 | Retrieval measurement on the new corpus | 02 to 07 (including the held-out review) | about 0.25 USD (cap 0.40) | The evaluation index for every later paid ticket; passage-level retrieval baseline from the question and from the agent's queries |
| 09 | Claim-support grader and calibration kit | 03, 06, 08 | about 0.80 USD (cap 1.00) | A grader, planted-positive calibration items, an Owner labelling kit; ends with an Owner action |
| 10 | Grader and judge acceptance | 09 and the Owner's labels | free (a second grader only with approval, up to 1.3 USD) | Measured agreement with humans; direct or advisory use decided |
| 11 | Quality baseline of the production path | 01 to 08, 10 | about 3.0 USD (cap 4.0) | Whole-set numbers with intervals, held-out aggregate, stability, legacy comparison, failure-cause table, committed baseline |
| 12 | Performance and cost baseline | 11 | about 0.4 USD (cap 0.6) | Latency, calls, tokens and cost distributions by role, quota inputs, claim-check effect |
| 13 | Closeout: documents, input list and reviews | 12 | free | Documents reconciled, ranked evidence list for M2 to M5, two independent reviews |

Tickets 01 and 04 have no dependency and could run in parallel; the numbering is a valid sequential order. Ticket 07 must precede every paid run (08 onwards) so the held-out set is written before anything is measured.

### Cost estimates (estimates, not measurements)

The unit is the measured cost of the earlier tool-agent runs: about 0.0025 USD per question with the claim check on (0.22 USD for 88 cases, `docs/EVALUATION_RESULTS.md`), legacy about 0.001. Ticket 02 and ticket 12 replace these with per-case measurements, and ticket 11 starts from a dry run built on them. Longer documents may raise the per-question unit by a third (the messy-document run cost 0.0028 per question), so caps carry about 30 percent contingency and are re-set after the pilot in ticket 09. The frozen set is about 370 cases (201 existing, about 70 new development, at least 100 held-out), so a full run costs about 0.93 USD. The grader costs about 0.004 USD per graded answer on the mid-size model (cited text of about 3,000 tokens; price table in the repository dated 2026-11-19), applied to about 250 answers in the full run (replies with a citation or a factual claim) and about 70 in the legacy sample; the price table must be re-read from the provider's pricing page before the first paid run, which this planning session did not do.

| Step | Estimate | Cap |
|---|---|---|
| Index rebuild and retrieval probes, 340 cases x 2 repeats on development and regression, held-out once (08) | 0.25 | 0.40 |
| Pilot replies, grader trial with a repeat (160 calls), judge on about 40 refusals, lock-box (09) | 0.80 | 1.00 |
| Full run, about 370 cases, claim check on (11) | 0.93 | |
| Two repeats of the 90-case sample (11) | 0.45 | |
| Legacy run on the sample (11) | 0.08 | |
| Grader on about 260 full-run answers and about 80 legacy answers (11) | 1.40 | |
| Refusal judge on those runs (11) | 0.14 | 4.00 for 11 |
| Sequential latency run, 40 cases x 3 (12) | 0.30 | |
| Claim-check ablation on the sample (12) | 0.10 | 0.60 for 12 |
| **Expected total** | **about 4.5** | **6.0** |
| Conditional: stronger grader trial on the calibration set (10) | up to 1.3 | needs approval |
### Unverified (do not state as fact)

- The current provider balance and whether the pricing in the repository's price table is current. Ticket 08 re-reads it before spending.
- Whether the frozen corpus changes per-case cost enough to break the 0.0025 USD unit (longer documents mean more input tokens).
- Whether a recording retriever captures every retrieval of the agent without the application changing (A14 reads as yes; ticket 02 confirms or records the limit).
- Whether SDK retries inflate the real bill beyond the meter, and whether billing matches the meter within about 5 to 15 percent (the earlier match was about 5 percent on one day).
- Whether the default grader can reach the proposed agreement thresholds. The claim checker's own accuracy on a general benchmark was modest (precision about 0.5), which is a warning, not a prediction.
- How many cases are flaky. Until the repeats run, any single-run difference below about 8 points on 100 cases is noise.
- That the Owner's labelling time estimate holds.
- Whether generated fixtures behave like files saved by Word, Excel or PowerPoint. The generators produce cleaner files than those programs (AGENTS.md already lists real Excel-saved and Google files as not covered). Google exports reduce, but do not remove, this gap; the baseline must not claim real-world format coverage beyond what was tested.
- Whether public documents can be answered from a model's memory without retrieval. Cases on them can pass for the wrong reason on the answer check; the cited-passage check and the invented-content documents are the countermeasure.

### Related documents

`docs/specs/drivemind-v1-product-definition.md` (Quality gates, Models, M1 row, M9 gate); `docs/audits/m0-system-audit.md` (D5-2, section 8); `docs/specs/m0-sec-security-hardening.md` and ticket 04 findings (call counts, counters list); `docs/EVALUATION_RESULTS.md`; `docs/DECISIONS.md`; `docs/KNOWN_ISSUES.md`; `docs/IMPROVEMENT_PLAN.md` (M2 and M3 background, not adopted here); `CODING_STANDARDS.md`; `AGENTS.md`.
