# Tool-agent local demo validation

The local HarborDesk stack was exercised through the real Next.js UI and Chrome,
with isolated demo PostgreSQL/Qdrant, `DEMO_MODE=true`,
`TOOL_RAG_AGENT_ENABLED=true`, `DEBUG=false`, and backend-only OpenAI credentials.
Frontend configuration used `NEXT_PUBLIC_DEMO_MODE=true`, the unchanged same-origin
`/api/v1` API base and `BACKEND_URL` pointing to the demo backend. No private Drive
content, schema changes, prompt tuning, deployment, or push was involved.
The global application default for the tool-agent flag remains false.

| User flow | Observed result |
| --- | --- |
| Hello | Direct answer, no citation |
| List files | Seven HarborDesk filenames, readable list |
| Count files | Seven |
| General knowledge | Grounded answer and working source UI |
| Explicit file summary | Useful exact-file summary and citation |
| Latest file summary | Actual latest selected file summarized with citation |
| File-specific deadline question | Focused retrieval returned no evidence; honest insufficient-evidence answer after the safety fix below |
| Missing file | Not-found explanation, no corpus fallback |
| Confidential tag filter | Unsupported explanation, no widened count |
| Prior list → first one | Filename clarification, no inferred execution |
| Explicit filename follow-up | Fresh exact resolution and simpler explanation |
| Normal knowledge follow-up | Bounded conversational continuation with sources |

Same-run LIST → first handle → file evidence was also checked through the UI.
Citation clicks opened three correct source panels without 404s. Markdown, long
answer wrapping, loading indicator and disabled-send behavior worked. Refresh
preserved conversation history; intentional repeated requests and error recovery
created no duplicate turns. No runtime handles, UUID prose or raw JSON appeared.

Two concrete defects were fixed, without changing the frozen agent/retrieval:

- Empty-chat navigation consumed a deferred `?ask=` before backend readiness
  arrived. It now waits until the new conversation can send, then sends once.
- An empty successful evidence read could produce an unsupported factual-absence
  claim. Service response mapping now uses the existing insufficient-evidence
  answer when there is no retained evidence; no retrieval retry/fallback is added.

A browser-intercepted 503 produced a safe error message. The real UI's “Try again”
recovered in place. There is no chat Stop/cancel control today; none was added.
Backend async cancellation behavior remains the previously tested behavior.

Approximate user-visible development latencies: greeting 3.2s (warm repeat
1.4–2.0s), inventory 4.4–5.4s, grounded knowledge 6.6s, same-run dependent summary
6.3s. A longer summary took about 10s. These are small local observations, not a
performance benchmark. Thinking feedback remained visible throughout.

Verification: 188 frontend tests, frontend lint/type checks and production build;
683 focused backend/service tests, Ruff/format, mypy and basedpyright. Follow-up
browser checks confirmed the safe no-evidence answer and the production build's
first-send/citation behavior. Temporary browser tooling and synthetic response
records remain outside Git. The current limitations are bounded file reads,
unsupported folder/label/time filters, no stable vague cross-turn file memory,
and no UI cancellation control.
