# DriveMind Public Demo

## Goal

This branch prepares the existing single-user Google Drive RAG application for a safe, polished public/client demo. Visitors should open a public URL, understand DriveMind quickly, query a controlled sample corpus, receive real grounded RAG answers, inspect citations/source evidence, and browse sample files where supported.

The audience includes portfolio viewers, recruiters, Fiverr clients, Upwork clients, friends, and family.

## Baseline

- Baseline commit: `a87c4ff52f81c9e1fd25dbaff1578ebbaaf0c31e`
- Baseline commit message: `fix: refine DriveMind scrolling and file browsing`
- Baseline tag: `pre-public-demo` (annotated)
- Original branch: `main`
- Demo branch: `demo/public-demo`

`main` remains the normal DriveMind implementation. Demo-specific work belongs on `demo/public-demo`. The tag identifies the source-code baseline; it does not certify public deployment safety or demo quality.

## Core Architecture To Preserve

Preserve the Next.js frontend, FastAPI backend, PostgreSQL metadata/document/chunk storage, Qdrant embeddings, and OpenAI embeddings/chat dependency. Keep the real hybrid RAG pipeline: keyword/vector/metadata retrieval, reciprocal rank fusion (RRF), reranking, evidence grading, and grounded generation.

Preserve citations and the source viewer, named-file and inventory routing, and both linear and optional LangGraph grounded execution. PostgreSQL chunk text stays authoritative, with matching chunk UUIDs in Qdrant. The demo must use real RAG rather than a fake/static chatbot.

## Public Demo Data Strategy

Use a dedicated demo PostgreSQL database/data environment and a dedicated demo Qdrant collection/datastore containing only approved public-safe sample content. Merely creating a different demo User inside the owner's existing DriveMind database is not sufficient isolation. Begin with approximately 5–10 controlled, safe sample documents.

Maintain approved sample document contents, a versioned corpus manifest, and representative demo questions together so the corpus and its validation are reproducible.

The corpus should demonstrate single-file questions, named-file retrieval, cross-file retrieval, inventory questions, citations, source inspection, and no-evidence/abstention behavior. No private DriveMind or Google Drive corpus may be copied into the demo.

## Google Drive / OAuth Boundary

The public runtime must neither require nor expose Mahad's Google OAuth credentials, Google Drive tokens, or Drive corpus. It must not require visitor Google OAuth or permit Drive synchronization or public indexing/build mutations.

Keep the real Google Drive integration in normal DriveMind. Isolate demo behavior so normal mode remains intact; do not delete or unnecessarily rewrite the integration.

## Frontend Direction

Adjust the existing frontend specifically for demo use as needed:

- Bypass Google Drive onboarding in demo mode.
- Clearly identify the sample/demo corpus and provide representative suggested questions.
- Preserve the chat and citation experience.
- Keep sample-file/source previews usable without Google Drive.
- Hide or remove Drive controls that are inappropriate for the demo.

Do not perform a broad redesign unless later explicitly approved.

## Safety Rules

- Never expose private Drive data or commit secrets or `.env` files.
- Use isolated demo storage.
- Enforce disabled operations on the backend; frontend hiding alone is insufficient.
- Do not use fake OAuth tokens or fall back to the owner account.
- If required demo configuration, identity, or storage is unavailable or invalid, demo mode must fail safely as unavailable. Never silently fall back to normal DriveMind configuration, the owner's OAuth-linked user, or the owner's PostgreSQL or Qdrant data.
- Demo readiness must reflect actual availability of the controlled sample index without pretending Google Drive is connected.
- Public users must not be able to trigger Drive sync or index mutations.
- Do not commit or push without explicit approval; inspect full diffs before commits.
- Preserve normal DriveMind behavior.

## Out Of Scope

Multi-user SaaS conversion, signup/account systems, organizations, billing/payments, enterprise permissions, a new RAG architecture, distributed job queues, expanded OCR, broad retrieval experiments, DeepEval or other evaluation-framework migration, broad UI redesign, and unrelated refactors.

## Development Workflow

Read-only inspection → agree scope → smallest implementation → focused tests → verification → full diff review → commit/push only after approval.

Future Codex work should address one coherent concern at a time. Inspect actual implementation and relevant instructions before each change; this plan does not replace repository evidence.

## Evaluation Requirements

Before public release, test representative sample questions, retrieval correctness, named-file behavior, cross-file behavior, citations, source previews, abstention/no-evidence behavior, latency, and obvious public failure modes, including blocked operations and unavailable dependencies.

Validate normal mode with demo behavior disabled and demo mode with it enabled, both existing grounded execution paths where applicable, existing citation/status contracts, and direct backend attempts to invoke operations blocked in public demo mode. Demo-specific changes must not silently damage normal DriveMind behavior.

Existing evaluation tooling can support separate validation without becoming a production runtime dependency. Do not claim demo quality merely because tooling exists; quality claims require actual demo-corpus results and source review.

The current evaluation runner expects an OAuth-linked user. Any adaptation for the OAuth-free public demo must be separately scoped, preserve existing evaluation integrity, and never introduce fake OAuth tokens merely to satisfy the runner. Do not design or implement that adaptation as part of these clarifications.

## Deployment Direction

The architecture requires a Next.js frontend, FastAPI backend, PostgreSQL, Qdrant, and OpenAI at runtime. Hosting providers have not been finalized. Vercel, Render, Railway, or other providers are not architectural requirements.

## Caching

The initial demo does not intentionally depend on Redis or semantic response caching. Semantic caching may later be evaluated to reduce latency/API cost, but is outside the initial scope.

Any future semantic cache must account for corpus/index versioning, invalidation, citation correctness, and user/data isolation. Correctness comes before caching.

## Initial Implementation Direction

Subject to repository-specific implementation planning, the expected direction is:

- Explicit, bounded demo behavior.
- Designated demo user/data resolution without Google OAuth.
- Controlled offline sample corpus loading.
- A pre-built demo index, rather than indexing on every startup.
- Server-side blocking of OAuth and index mutation routes in public demo mode.
- Sample previews independent of Google Drive.
- Limited anonymous-use protection.
- Deployment only after local verification.

These are architectural boundaries, not permission to implement all of them at once. Each implementation concern needs its own agreed scope.
