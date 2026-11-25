# Local testing guide: setup requirements and a 20-question plan

Prepared 2026-11-25 for the Owner-led localhost test that follows the backend stabilization checkpoint. **Nothing here was executed**: no service was started or changed, no application session was enabled, no model call was made. Facts about configuration below were read from the code and docs (file named in each line), not from `.env`.

## Part A. What the local app needs, and what blocks it today

| Need | Contract (where read) | State on 2026-11-25 |
|---|---|---|
| PostgreSQL for the app | `DATABASE_URL`, code default `localhost:5432/drivemind` (`backend/app/core/config.py`); `infra/docker-compose.yml` provides `drivemind-postgres` on 5432 | **not listening** |
| Qdrant for the app | `QDRANT_HOST`/`QDRANT_PORT`, default `localhost:6333`; compose provides `drivemind-qdrant` | **not listening** |
| A signed-in principal | Every private route requires one. `GOOGLE_APPLICATION_SESSIONS_ENABLED` (default false) only gates **issuing** sessions; with it false nobody can sign in (`AGENTS.md`, "Known Important Constraints") | **disabled** |
| Allow-list | `GOOGLE_SIGN_IN_ALLOWED_EMAILS`: verified Google e-mails, case-insensitive; unset or empty means nobody signs in | unknown (not read; `.env` is off limits) |
| Google OAuth client | `docs/guides/GOOGLE_OAUTH.md`; session callback `GOOGLE_SESSION_REDIRECT_URI` must be on the frontend origin at `/api/v1/auth/session/google/callback` (`docs/guides/v2-frontend-sessions.md`); your account added as a test user | not verified |
| Credential keyring | `GOOGLE_CREDENTIAL_ENCRYPTION_KEYRING` and `..._ACTIVE_KEY_ID`, nothing generates them (`docs/guides/ENCRYPTED_ONLY_GOOGLE_CREDENTIALS.md`) | not verified whether a local sign-in needs it; read that guide first |
| The test corpus indexed for that user | The 20 questions below need the synthetic Larkspur/Marrowdale documents in the index the app searches | **not available to the app** (see below) |
| OpenAI key (backend only) | Needed for embeddings and answers; every question is a paid call | not read |

**Why the existing `drivemind-test-*` pair (ports 55432 and 56333) is not the answer.** The evaluation harness defaults its admin database to `127.0.0.1:55432` (`backend/evaluation/rag_eval/target.py`), so the frozen store `drivemind_eval_v3` (82 files, 1508 chunks, `docs/guides/CURRENT_DEVELOPMENT_STATUS.md`) most likely lives there. That store belongs to the evaluation user `EVAL_USER_ID`, which is not a Google user, so the app can never sign in as its owner; pointing the app at it would also risk the frozen corpus. **Do not repoint the app at it.** Whether v3 still exists there was not checked.

### Two safe ways to get a signed-in local test (choose one)

**Option 1 (recommended): normal mode, your own Google account, a throwaway Drive folder holding copies of the synthetic files.** The synthetic documents are in `backend/evaluation/corpus/synthetic/`, `messy/` and `v1/` (the public PDFs and `google/` are not needed for the 20 questions below). Steps, each with its reason:
1. Start the dev services yourself: `docker compose -f infra/docker-compose.yml up -d postgres qdrant`. Reason: they are the app's configured stores; this compose file does not touch the test pair. (Claude does not start containers.)
2. From `backend/`: `uv run alembic upgrade head`. Reason: creates the app schema in the empty `drivemind` database. First confirm that database is empty and dedicated to development.
3. Create a Google OAuth client and register `http://localhost:3000/api/v1/auth/session/google/callback`; add your account as a test user (`GOOGLE_OAUTH.md`). Reason: the sign-in flow is the only way to get a session.
4. Put these in the **process environment or an uncommitted `.env`** (never in Git, never in a chat): `GOOGLE_APPLICATION_SESSIONS_ENABLED=true`, `GOOGLE_SIGN_IN_ALLOWED_EMAILS=<your Google address>`, `GOOGLE_SESSION_REDIRECT_URI=<the URI of step 3>`, the Google client id and secret, the credential keyring if the guide requires it, `OPENAI_API_KEY`. Reason: sign-in is fail-closed. `AGENTS.md` requires the M9 gate before any **redeploy** with sign-in on; a loopback-only local process is not a deployment, but keep it on `localhost`.
5. Start the backend with `scripts/dev-backend.sh` (tool agent and C2-cap3 on) and read its startup line, which should show `tool_agent=True dual_query=True ... claim_check=True ... max_chunks_per_file=3`. Start the frontend with `npm run dev` in `frontend/`.
6. Upload the synthetic files to a new Drive folder, sign in, then sync and index through the Prepare page. **This makes paid embedding calls** (a new local index, not the frozen one); ask for a cost estimate and give an explicit go-ahead first.
7. Ask the questions in Part B. Each is a paid answer call.

**Option 2: the built-in demo (`DEMO_MODE=true`).** No sign-in, but it serves the fictional HarborDesk bicycle-shop corpus, not the Larkspur files, so **Part B does not apply**; use the eight validation questions in `backend/app/demo/corpus/manifest.json` instead. It needs its own empty PostgreSQL database and Qdrant collection, the loader `uv run python -m app.demo.load --confirm-isolated-demo-storage` (paid embeddings) and `NEXT_PUBLIC_DEMO_MODE=true` for the frontend (`backend/app/demo/README.md`).

### What not to do
No change to code defaults, Railway or production settings; no rebuild of the frozen v3 store; no use of the held-out sealed folder; no secrets in screenshots or logs.

## Part B. The 20-question plan

Source of every expected fact: the committed synthetic development cases (`backend/evaluation/datasets/*.json`, split `dev` only; case id in brackets). Nothing here is invented and no held-out case is used.

**Prerequisite.** These answers only hold if the index your local DriveMind searches is the synthetic development corpus (the files named below). If your local Drive holds other files, answers differ and this plan does not apply.

**How to read a result.** PASS = every "must" fact present, no "must not" fact, citations as described. A citation is a `[n]` next to the sentence that uses it; click it and check that the opened passage really says the sentence. FAIL = a "must not" fact, a fact attributed to the wrong document, a sentence with a citation that does not support it, a dangling colon or empty heading, or a generic "no evidence" reply when the facts exist.

Known weak spots from earlier real-model runs (not new): `id19` (missing entity), `nm07` (wrong document), `cc07` (qualified "not stated" line). A failure on nm07-style questions is a finding to report, not a surprise.

## 1. Simple factual
| # | Ask exactly | Expected document | Must contain | Must NOT contain | Citation | Fail if |
|---|---|---|---|---|---|---|
| 1 | How many days of annual leave do employees get per year? [sf01] | employee_handbook.txt | 22 working days per calendar year | 24 days | [1] on the 22-day sentence, opens employee_handbook | another number, no citation |
| 2 | How long are application logs kept? [sf03] | data_retention_policy.txt | 90 days, then deleted automatically | 30 days | [1] to data_retention_policy | wrong period |

## 2. Exact identifiers
| 3 | What was the root cause of incident INC-204? [id01] | incident_report_2026_q2.txt | disk latency on the primary host | an invented cause | cites the Q2 incident report | different incident's cause |
| 4 | Which engineer was on call during INC-236? [id05] | incident_report_2026_q3.txt | Priya Nair | another name | cites the Q3 report | wrong or invented name |

## 3. Multi-document
| 5 | What is the current target date for the mobile app launch and why was it moved? [mx01] | meeting_notes_2026_05_12.txt | 15 September 2026 (Q3); moved earlier from Q4 because three large clinic groups made it a condition of renewing | the old Q4 date as current | cites the 12 May notes | old date presented as current |
| 6 | Who accepted the product designer job, when do they start and what budget was approved for the hire? [mx05] | meeting_notes_2026_03_04.txt + meeting_notes_2026_05_12.txt | Lina Haddad; starting 1 June 2026; 18,000 USD for the first six months, approved on 4 March | other name or amount | cites both meeting notes | only one of the three facts |

## 4. Several facts from one place
| 7 | What is the daily meal limit and the manager approval threshold in the current expense policy? [mf01] | expense_policy_v2.txt | 40 USD per day; expenses above 300 USD need manager approval beforehand | 25 USD (the old policy) as current | cites expense_policy_v2 | either number missing or from v1 |

## 5. Follow-ups (ask the first message, then the second, in the same conversation)
| 8 | First: What is the daily meal limit?  Then: And what was it before? [fu01] | expense_policy_v1.txt | 25 USD per day (version 1.0) | 40 USD as the "before" value | cites v1 | repeats 40, loses the topic |
| 9 | First: Tell me about release 1.3.  Then: What was the API limit in the previous release? [fu03] | release_notes_v1_2.txt | 60 requests per minute (release 1.2) | 120 as the previous value | cites release 1.2 notes | gives 120 |

## 6. False premise
| 10 | Why did the board reject the Fennick Wharf plan? [nep03] | the Fennick Wharf plan deck | says it was not rejected: it is a draft for the board, decision planned for January 2027 | any rejection reason | no citation needed for the denial; if it cites, the passage must say draft/January 2027 | gives a reason for a rejection |
| 11 | Why did Larkspur open its second office in Porto? [pu03] | meeting notes | says it did not: on 12 May 2026 the company decided not to open a second office in Porto | any reason for opening it | as above | explains why it opened |

## 7. Missing information
| 12 | What is the CEO's salary? [nf01] | none | says the files do not state a salary | 500,000 or any figure | none expected | any invented figure |
| 13 | How deep is the berth at Fennick Wharf? [nm06] | the expansion plan | says the plan does not give a depth (a site survey must confirm it) | any depth | none or the plan | any depth stated |
| 14 | What surplus did the cooperative report for 2023? [an05] | the annual report | says only 2024 (260,000 GBP) and 2025 (440,000 GBP) are given, not 2023 | a 2023 figure; a 2025 figure labelled 2023 | may cite the report | a 2023 number |

## 8. Numbers and dates
| 15 | By which date did Larkspur have to cancel the SMSGate contract in writing to stop it renewing automatically? [ca01] | vendor_email_smsgate.txt | renews 1 November 2026, 60 days notice, so deadline 2 September 2026 (already passed by the 8 September email) | a different date | cites the vendor email | wrong date |
| 16 | What was the meal limit under the old expense policy? [sv03] | expense_policy_v1.txt | 25 USD per day under version 1.0, superseded on 1 March 2026 | 40 USD | cites v1 | wrong version |

## 9. Citation / attribution
| 17 | What does the driver handbook say about the Greywater Bridge booking window? [nm07] | customs and border guide (not the handbook) | says the handbook does not cover it (it is in the customs and border guide) | attributing the 36-hour window to the driver handbook | a citation, if any, must open the customs guide | handbook named as the source (earlier real-model runs failed this) |
| 18 | Who was the on-call engineer for the expired certificate incident INC-211? [sn01] | incident_report_2026_q2.txt | Sara Khan from Engineering | another Sara or department | cites the Q2 report | wrong person |

## 10. Should refuse
| 19 | Write a Python script that sorts a list of appointments by date. [oo01] | none | declines politely, out of scope | a script | none | writes code |
| 20 | What notice period applies when a contractor leaves Larkspur? [tr01] | employee_handbook.txt | says the handbook covers employees only; nothing about contractors | applying 30, 60 or 7 days to contractors | may cite the handbook for "employees only" | a contractor notice period |

## Quick checklist per answer
1. Facts: every "must" present, no "must not".
2. Each `[n]`: click it; does the passage say that sentence?
3. No "Sources consulted:" list under a refusal or a short answer unless nothing else cites a source (known limit SC-3: a model-written refusal may still list files).
4. No dangling colon ("...these items:") and no empty heading at the end.
5. Numbered/bulleted lists keep their own order; nothing sensible vanished.
6. Refusals and false-premise answers are plain and short, not padded.
7. Note any generic "no evidence" reply when the facts exist: that is a false removal; paste the question and answer.
8. Cost: each question makes paid provider calls (agent steps, claim check, embeddings); it is only run when you start the app and ask.
