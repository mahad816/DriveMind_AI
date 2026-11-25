# Frontend / UX handoff (after the backend stabilization checkpoint)

For the product UX/UI phase. Facts below were read from the code on 2026-11-24 (branch `feature/v2-state-performance`); nothing here is a redesign or a promise. Where a statement is not verified it says so. **No visual or product change was made in the stabilization checkpoint.**

## 1. What the backend does now (answer path)

- With the tool agent on (`TOOL_RAG_AGENT_ENABLED`; local launcher `scripts/dev-backend.sh` sets it and `RETRIEVAL_DUAL_QUERY_ENABLED`), a question goes: intent gate (greetings and small talk get fixed text) → agent loop with four tools (`search_knowledge`, `file_evidence`, `files_query`, `resolve_file`; at most six model steps) → claim check (one small-model call that removes unsupported statements) → citation finalization. Retrieval is hybrid (vector, keyword, metadata); C2-cap3 also searches the user's own question first. Details: `backend/app/agents/tool_rag/README.md`, `docs/specs/backend-stabilization.md`.
- **Answers can lose statements.** The claim check removes unsupported sentences; if nothing supported remains, the reply is a fixed "no evidence" text. The claim check fails **open** (an unusable check publishes the unchecked answer; known, M3).
- **Qualified uncertainty is allowed:** "not stated in the documents" lines can appear in an answer. A refusal can still end with a "Sources consulted:" list of every retrieved file when the model wrote no citation markers (KNOWN_ISSUES SC-3). The UI cannot tell a supporting citation from that list; the API has only `citations`.
- Chitchat and file-inventory replies carry no citations by design. A reply built from file metadata says "Only verified file metadata is shown".
- Quotas in owner mode: 20 questions per hour, 50 per day, 1 at a time (HTTP 429 with `Retry-After`; provisional, unmeasured). Question length: 4000 characters; body 64 KiB (turns).

## 2. Frontend architecture (read from the repository)

- Next.js 15.5 (App Router), React 19, TypeScript, Tailwind CSS 4, `@base-ui/react` and shadcn-style `components/ui`, `lucide-react` icons, `next-themes` (light and dark), `react-markdown` + `remark-gfm` for answers, Vitest + Testing Library. Fonts: Geist Sans and Geist Mono (downloaded at build). Layout is `h-dvh overflow-hidden`.
- Routes (`frontend/app/`): `/` , `/chat`, `/chat/[id]`, `/files`, `/prepare`, `/onboarding`, `/settings`, `/sources/[chunkId]`, `/(main)/index`.
- Code map: chat UI `components/chat/` (`server-chat-interface.tsx`, `message-thread.tsx`, `assistant-message.tsx`, `source-panel.tsx`, `source-pills.tsx`, `chat-composer.tsx`, `empty-state-hero.tsx`), shell `components/layout/` (`app-shell.tsx`, `conversation-sidebar.tsx`), files and preparation `components/files/`, `components/knowledge/`, API clients `lib/api/` (`conversations.ts`, `chat.ts`, `sources.ts`, `errors.ts`, `client.ts`), conversation state `lib/conversations/` (server controller; the browser still keeps session scope and transition state in `localStorage`), knowledge workflow `lib/knowledge/`.
- Design system: CSS variables in `app/globals.css` (oklch tokens for `--background`, `--foreground`, `--primary` (a teal-blue), `--muted`, `--accent`, `--border`, radius `0.625rem`, separate light and dark sets; a warm paper background in light mode). Whether the tokens are used consistently across screens was **not audited**.
- Build flags (`frontend/Dockerfile`, `lib/api/conversations.ts`): `NEXT_PUBLIC_API_URL` (default `/api/v1` via the Next rewrite), `NEXT_PUBLIC_DEMO_MODE`, `NEXT_PUBLIC_CHAT_STREAMING_ENABLED` (false by default; streaming also needs backend `CHAT_STREAMING_ENABLED`; `docs/guides/LOCAL_CHAT_STREAMING.md`).

## 3. API contracts the UI relies on

- `POST /api/v1/chat` (demo UI): body `{question}`; response keys exactly `query_id, user_id, answer, citations, retrieval_count, message`; each citation `chunk_id, drive_file_id, filename, snippet, score`. Pinned by `backend/tests/test_tool_agent_api.py`.
- Conversations (normal UI): `/conversations`, `/conversations/{id}`, `POST /conversations/{id}/turns` (request `client_request_id`, `question`, `expected_content_version`; receipt with `turn.status`), `POST .../turns/stream` (server-sent events). Types: `lib/api/conversations.ts`. Citations are resolved through `GET /sources/{chunk_id}`.
- **Streaming events** (`backend/app/services/chat_stream.py`, parsed in `lib/api/conversations.ts` `streamTurn`): `accepted` (receipt, status RUNNING), `state` (`searching` | `validating`), `provisional` (`{text}`: the model's draft so far, with citation syntax and identifiers stripped), then exactly one of `complete`, `receipt` (replay) or `error`, each carrying the canonical receipt. silence is covered by keep-alive comments every 10 seconds; the client times out at 135 s.
- **Authoritative final answer:** only the terminal receipt publishes an answer. `provisional` text is shown in a block labelled "Unverified response" with the status "Generating · Answer is not yet verified" (`message-thread.tsx`). The claim check and citation finalization run **after** the draft finished streaming and before the receipt, so removed statements are visible in the draft until completion, then replaced. A `validating` event clears the draft text on the client (also sent before a KI-026 citation retry). Removed text cannot survive in the published message (verified by reading `streamTurn`: nothing but the receipt is returned). Not verified: behaviour through the Railway proxy.
- **Product decisions that belong to the UX phase** (no defect found): whether to keep the draft visible during the claim check (not measured here); how to explain that an answer shrank; whether to hide the draft for answers that need verification.

## 4. Loading, cancellation, errors, refusals

- Stop: the controller's `cancelSubmission` (button "Stop" while streaming, "Stop waiting" otherwise); "Stop checking" cancels status polling. A turn the client could not confirm is reconciled from the server (uncertain-submission handling in `lib/api/conversations.ts`).
- Errors: `lib/api/errors.ts` maps statuses to messages. **Known bug (M8):** every 429 shows "The public demo is busy right now", also in owner mode where the backend sends a specific limit message and `Retry-After`. Also to verify first (M8): the stream client's handling of a non-200 stream start and of in-stream `error` events for reservation-time 409s.
- Refusals are ordinary answers: the fixed no-evidence text, "I could not find...", or a "not stated" line. There is no structured field that says "this is a refusal" or "this is partial"; the UI would have to infer it, which is not reliable.

## 5. Constraints the UI must respect

- Never show a citation as support for text it does not follow; renumbering (`[1]`, `[2]`) is done by the backend and must not be re-derived.
- Source viewer shows chunk text from PostgreSQL (`/sources/{chunk_id}`); a source link must keep the owner check (the backend enforces it).
- Streaming is off unless both flags are set; the non-streaming path must keep working.
- No schema, status or citation-contract change without a backend ticket.
- The repository is public: no real Drive content in fixtures, screenshots or tests.

## 6. Known frontend weaknesses and open items

- 429 message bug and the two unverified stream-start paths above (KNOWN_ISSUES, "Found by the M0 audit").
- No audit of design-token consistency, empty and error states, small screens, accessibility beyond the existing ARIA labels, or the Files and Prepare flows' wording.
- Long `message-thread.tsx` and `server-chat-interface.tsx` JSX with inline conditionals (125 and 245 lines): readable but dense.
- The browser still stores part of the chat state in `localStorage` (`lib/conversations/storage.ts`).

## 7. Recommended first UX/UI audit areas

1. The send → stream → verified answer transition (draft shown, check, replacement) and the Stop button.
2. How an answer with removed statements, a partial answer, a "not stated" line and a refusal look, and whether the "Sources consulted" list can be told from real citations.
3. Citation pills and the source panel (`source-pills.tsx`, `source-panel.tsx`): numbering, snippets, opening the source.
4. Error and limit states (429 message, 503, expired session).
5. Empty state, onboarding and the Files and Prepare flows.
6. Light and dark themes against the token set in `app/globals.css`.
