# 05: RAG execution paths and feature flags (A1)

**Spec:** docs/specs/m0-system-audit.md
**What to build:** The Owner knows which code answers each top-level route (chitchat, file inventory, file target, grounded) under the local defaults and under the hosted flags, for both chat entry points, and what happens when the model provider fails.
**Blocked by:** None (can start immediately). Ticket 01's hosted flag values are a soft input: any flag not read stays `Unverified`.
**Status:** ready-for-agent
**Progress:** open

## Scope

- Trace `RagService.ask` routing and the flags that matter: `TOOL_RAG_AGENT_ENABLED`, `AGENT_GRAPH_ENABLED`, `HYBRID_RETRIEVAL_ENABLED`, `CLAIM_CHECK_ENABLED`, `CHAT_STREAMING_ENABLED`, and demo mode. Produce, per top-level route, the code path selected under local defaults and (once known) hosted flags, naming entry points.
- Cover both entry points: the single `/chat` request and conversation turns (including streaming). State whether they reach the same path.
- Record behavior on provider failure in the path production would reach: confirm or refute the v1 spec requirement that it never produces an ungrounded answer. Where a focused deterministic test with a faked provider is possible, add it (strict expected failure if it reveals a defect, passing if it protects correct behavior).
- Note anything that contradicts `AGENTS.md`, `docs/ARCHITECTURE.md` or `docs/TOOL_RAG_ARCHITECTURE.md`.

## Out of scope

Switching, disabling or deleting any path (ADR 0001 steps 2 and 3); measuring answer quality or follow-up quality (M1, M4); any model call; fixing defects.

## Inspect

`backend/app/services/rag_service.py`, `backend/app/agents/tool_rag/`, `backend/app/agents/drive_graph/`, `backend/app/retrieval/` (router), `backend/app/api/chat.py`, `backend/app/api/conversations.py`, `backend/app/core/config.py`, `docs/adr/0001-single-answering-path.md`, `docs/TOOL_RAG_ARCHITECTURE.md`.

## Deliverables

`## Findings` in this ticket: route-by-flag path table (local defaults / hosted), entry-point comparison, provider-failure behavior, documentation contradictions. Tests only if meaningful and deterministic.

## Needs

No paid APIs (faked providers only). No live infrastructure. Docker only if a chosen test needs the database fixtures.

- [ ] For each of the four top-level routes, the answering code path is named under local defaults and under hosted flags (or `Unverified` per unread flag).
- [ ] `/chat` and conversation turns (including streaming) are each traced, with entry points named, and stated to reach the same path or not.
- [ ] Provider-failure behavior in the production-reached path is described with evidence, and the "never ungrounded" requirement is marked Verified, Defect or Unverified.
- [ ] Contradictions with existing documentation are listed.
- [ ] Any added test is deterministic and paid-API-free; a defect test fails today for its stated reason.
- [ ] No application code changed.

## Comments
