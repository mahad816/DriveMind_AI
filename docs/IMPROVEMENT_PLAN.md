# Improvement plan (written 2026-11-20, from measurements, not guesses)

Scope: the **tool agent** only (the old pipeline is evaluation baseline code and is not improved).
Everything below is backed by numbers in `docs/EVALUATION_RESULTS.md` and by the diagnostics described here.
Nothing in this file is implemented yet.

## 1. Where the answer goes wrong today

Tool agent on the 94 baseline cases: right file found 50 of 62 (81 %), answer correct 55 of 67 (82 %),
refusal correct 27 of 28. On the 18 invention traps: 11 of 18.

In the first baseline run 12 cases did not find the right file (plus `sf01` in the second run, the same
search failure). Nine of them, and four trap cases, fall into these five causes; the other three
(`ru03`, `sf07`, `pb05`) are different: a second expected source was not cited, a role was named without
the person's name, and a harness rule that was already corrected. Causes A, B, D were confirmed by running
the searches; C and E by reading the replies.

| # | Cause | Cases | Evidence |
|---|---|---|---|
| A | Search returns **nothing** | sf01, mf02, sn02, tr12, tr14 | Both searches came back empty (see 2.1 and 2.2) |
| B | The agent **never searched** | ru02, ca04, ca05 | No search call logged; the model judged tools unnecessary |
| C | **Follow-up** loses the topic | fu02, fu04 | "And who was on call for INC-211?", "Can I carry those days over?" |
| D | **Old or wrong version / wrong source** preferred | sv06 (answers with the old 200 USD limit), mx07 | v1 ranked just above v2; general NIST documents ranked above company ones |
| E | Found the file but **made things up** | tr01, tr04, tr09, tr11, tr13 | Claims about the wrong subject, or "no fee" stated as fact |

## 2. What the diagnostics showed

### 2.1 The relevance cut-off throws away correct answers
`retrieval_score_threshold = 0.35` drops every vector hit below 0.35. With the cut-off removed, the
correct file for these questions is at the top:

| Question | Score of the right file | Rank without the cut-off |
|---|---|---|
| annual leave per year (sf01) | 0.347 | 1 |
| sick leave + medical certificate (mf02) | 0.305 | 2 |
| "Sara Khan role" (sn02) | 0.309 | 1 |

All three fall just under 0.35. This embedding model gives modest numbers even for good matches, so a
fixed line at 0.35 is too high, and the files are short, so a whole file is one chunk, which pulls the
score down further.

### 2.2 Keyword search needs every word
The keyword query is `websearch_to_tsquery`, which means ALL words must match. "get", "many", "per",
"role" are not in the files, so the search returns zero. A rewritten query with "any word, ranked" finds the
handbook at rank 1 for sf01 and mf02. It does not rescue "Sara Khan role" on its own (the common word
"role" outranks the rare name), so it must work together with the vector search, which does find that one.

### 2.3 The agent skips the search
The tool-agent prompt says "reply without tools when document access is unnecessary", and the model
believes that of Roman Urdu questions and "I want 3 nights at 200 USD" questions. The tool call is
`tool_choice="auto"`.

### 2.4 Old and new versions
For the 250 USD approval question both expense policies are retrieved; v1 (200 USD threshold) ranks just
above v2 (300 USD). The model has no rule for preferring the newer one.

### 2.5 The claim check does not see these errors
It asks "is this fact in the evidence?". The invention traps are different: the text supports the sentence
but the sentence is about the wrong subject (CloudHost vs Larkspur, contractor vs employee), or it claims
something is absent ("no cancellation fee") while the evidence is merely silent.

## 3. The changes, in the order we should do them

Each change gets its **own branch**, its **own test**, and is kept only if it improves the numbers.
Tune on the dev cases, report on the held-out test cases.

### Step 0 - A free retrieval test (no AI model, cost about 0)
A script that, for every answerable case, runs the real search with the agent's query and reports
"is the right file in the top 8, and at what rank?". Same for the "not found" cases: "did we retrieve
anything that looks like an answer?". It is deterministic and free, so we can try ten settings for the
price of none. Everything in steps 1-2 is tuned with it first, then confirmed with one paid run.

### Step 1 - Search that finds the document (fixes cause A)
1. **Relevance line**: replace the fixed 0.35 with "keep the best N results above a low floor (about 0.2)
   and drop results far below the best one". Risk: more weak results reach the model on unanswerable
   questions. Guard: measure refusals (28 baseline cases + 9 not-found traps) before and after; keep the
   change only if refusals stay at or above 95 %.
2. **Keyword search**: if the strict version returns fewer than 3 results, run an "any word" version,
   with filler words ("how", "many", "get", "what") removed. Risk: popular words in long public documents
   crowd out company files; guard: it only runs as a fallback and is weighted below the vector search.
3. **Query writing**: tell the agent to search with short keyword queries (names, numbers, IDs, the topic)
   and to run a second differently-worded search if the first returns nothing.
   Expected: sf01, mf02, sn02, tr12, tr14 recover. Target: right file found 81 % -> at least 90 %.

### Step 2 - Make the agent search (fixes cause B and part of C)
- When the intent gate already says "document question", force the first model step to call a tool
  (`tool_choice="required"`). The model can still answer afterwards.
- For follow-up questions, tell the agent to include the topic from earlier turns in its search.
  Expected: ru02, ca04, ca05, fu04 recover. Risk: a question that really needs no document
  (a pure calculation) triggers a pointless search; the cost is one search, not a wrong answer.

### Step 3 - Prefer the current version (fixes cause D, part)
Show the file's modified date and any "supersedes / replaced by" note next to each piece of evidence, and
add one rule: "when sources disagree, use the newest and mention the older value". Tested on the 7
`superseded_version` cases and sv06.

### Step 4 - Catch the errors the claim check cannot see (fixes cause E)
Extend the claim check, with the traps as the test set:
- give it the question and ask whether each statement is about the **same subject and scope** as the
  evidence it relies on;
- treat "no X exists / there is no fee" as a claim that needs the evidence to say so; silence is not support.
Also add one agent-prompt rule: answer a value only if the text states it for that exact subject,
otherwise say what the text does state and what it does not.
Risk: more correct sentences removed; guard: the planted-claims test (false removals must stay at 0 of 41)
and the 94-case run.

### Step 5 - Experiment: a larger chat model (cheap, may be the biggest single gain)
Run the traps and the 94 cases with `gpt-5.4-mini` as the answering model instead of `gpt-5.4-nano`.
If invention drops a lot, the best fix for cause E may be the model, not more checking code. Cost is
about 3-4x per question (still cents); we decide with data.

### Step 6 - Later, only if still needed: smaller, section-aware chunks
Today a chunk is up to 3,500 characters, and a short file is one chunk. Splitting by headings makes a
"sick leave" question match the sick-leave section instead of the whole handbook. It needs re-indexing and
its own evaluation, and mostly matters for long real documents (the public PDFs in the corpus), so it
comes after steps 1-4.

## 4. How we will know it worked (targets, before/after, same cases)

| Measure | Now | Target |
|---|---|---|
| Right file found (62 answerable cases) | 81 % | 90 % or more |
| Answer correct (67 cases) | 82 % | 90 % or more |
| Refusal correct (28 cases) | 96 % | stay at 95 % or more |
| Invention traps passed (18 cases) | 61 % | 80 % or more |
| Wrongly removed true sentences (planted test) | 0 of 41 | stay 0 |
| Median answer time | about 4-5 s | no more than +1 s |

## 5. What this plan does not claim
- It does not claim real users will see these numbers; the cases are synthetic and short, written by us.
- 94 + 18 cases give wide error bars (about +/- 8 points); differences of 2-3 cases are noise, so each step
  is judged on its dev result **and** its held-out test result.
- The real-world test (your own Drive, real questions) comes after all steps, as agreed.

## 6. Budget
The retrieval test (step 0) is free. Each paid confirmation run of the 94 cases costs about 0.10-0.25 USD
and the traps about 0.06 USD. The remaining experiment budget under the 3 USD cap is almost used, so the
steps above need a new allowance (about 2 USD would cover all of them with repeats). Ask before spending.
