# DriveMind documentation

Start with the [repository README](../README.md) for the project, local run instructions, and the runtime diagram. The [interactive architecture site](https://mahad816.github.io/DriveMind_AI/) lets you play or step through the three approved system flows.

## Architecture and flows

| Guide | What it covers |
|-------|----------------|
| [Architecture](ARCHITECTURE.md) | Runtime components, PostgreSQL/Qdrant ownership, API, and boundaries |
| [Indexing](guides/INDEXING.md) | Full and incremental Drive sync, ingestion, chunking, build, and file states |
| [Retrieval](guides/RETRIEVAL.md) | Question routing, conditional retrieval, bounded context, and citations |
| [LangGraph](guides/LANGGRAPH.md) | Optional graph nodes and rewrite loop for general grounded questions |
| [Evaluation](guides/EVALUATION.md) | Implemented runners, datasets, metrics, and future work |

The first three guides contain the corresponding static diagrams and links to their interactive versions. The focused LangGraph guide retains its node-level graph.

## Setup and reference

| Guide | What it covers |
|-------|----------------|
| [Local setup](guides/SETUP.md) | Prerequisites, environment, and first run |
| [Google Drive OAuth](guides/GOOGLE_OAUTH.md) | Drive scope and callback configuration |
| [Deployment](guides/DEPLOYMENT.md) | Deployment considerations |
| [Current status](CURRENT_STATUS.md) | Progress and resume notes |
| [Limitations and roadmap](LIMITATIONS_AND_ROADMAP.md) | MVP constraints and future work |
| [Project context](PROJECT_CONTEXT.md) | Product intent and scope |

Historical phase logs and experiment decisions remain in `docs/` and `backend/evaluation/`; current implementation and the focused guides above take precedence when they differ.
