# 02: C2-cap3 and the tool agent active in local development only

**Spec:** docs/specs/backend-stabilization.md (Owner-approved exception: docs/DECISIONS.md, "Backend stabilization checkpoint")
**What to build:** a documented local launch that turns on the tool agent and C2-cap3, a startup log line proving the effective flags, and free tests that a request really runs both searches and hands the agent the merged list.
**Blocked by:** None (can start immediately)
**Status:** ready-for-agent
**Progress:** claimed
**Risk:** standard (configuration only; no default, remote setting or authorization code changed)

- [ ] `scripts/dev-backend.sh` sets `TOOL_RAG_AGENT_ENABLED` and `RETRIEVAL_DUAL_QUERY_ENABLED` for the local process; each can be set to `false`; `backend/.env` is never read or edited.
- [ ] The startup log prints `effective_config` with booleans and the integer `max_chunks_per_file` only (the cap of C2-cap3), no secret.
- [ ] HTTP-level test: flag on runs the question and the model query, evidence has each chunk once, citations in merged order; flag off runs the model query only.
- [ ] Code defaults, Railway and demo configuration are unchanged; the evaluation harness still pins its strategy.

## Audit of the improvements on the normal local path

| Item | State |
|---|---|
| Hybrid retrieval | Active by default (`HYBRID_RETRIEVAL_ENABLED` true) |
| Dual-query retrieval, original question first, soft cap 3, first-eligible-search allowance | Active through the launcher's flag, on the tool-agent path only; single-turn runs only; cap not applied for an exact-file scope or a file named in either query (conditional by design) |
| KI-034 first-step search note | Active by default on the tool-agent path; conditional (first step, no tool, no history, not a social phrase, at least two cycles left) |
| Managed Qdrant client lifecycle | Active by default on every path (`main.py` shutdown) |
| False-premise instructions, claim checker, material-assertion instructions, KI-035 removal, citation finalization | Active by default on the tool-agent path; the claim check runs only when evidence exists and fails open |
| Claim-check trace, `--retrieval-strategy`, `--trace-claim-check` | Evaluation-only; not forced into requests |
| Tool agent itself | Default **off**; it was off in the Owner's local settings; on only through the launcher |
| Streaming | `CHAT_STREAMING_ENABLED` off, not changed (separate backend and frontend rollout) |

## Comments

- 2026-11-24: claimed. The real server was **not** started by this session: its startup runs a job-cleanup `UPDATE` against the database named in the secret `.env`, which was not inspected. Instead the real `Settings` class was loaded under the launcher's variables (booleans printed): launcher gives `tool_agent True, dual_query True`; with `RETRIEVAL_DUAL_QUERY_ENABLED=false` it gives `dual_query False`. Expected log line on start: `effective_config tool_agent=True dual_query=True hybrid=True claim_check=True streaming=False demo=False max_chunks_per_file=3`. Rollback: `RETRIEVAL_DUAL_QUERY_ENABLED=false scripts/dev-backend.sh`, or start uvicorn directly as before.
