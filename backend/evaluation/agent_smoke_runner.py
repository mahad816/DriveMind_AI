"""D3 development-only graph smoke. Freeze first; never repeat pending cases."""

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from time import perf_counter
from typing import cast, Any
from collections.abc import Sequence
import subprocess
from uuid import UUID

from pydantic_settings import BaseSettings
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.agents.tool_rag.agent_models import (
    AgentChatService,
    AgentMessage,
    ToolDefinition,
    AgentStepResult,
)
from app.agents.tool_rag.agent_service import ToolRagAgentService
from app.agents.tool_rag.registry import ToolRegistry
from app.agents.tool_rag.prompts import AGENT_SYSTEM_PROMPT
from app.core.config import Settings
from app.db.enums import DriveFileStatus
from app.demo.service import DemoCorpusService
from app.llm.openai_agent_service import OpenAIAgentChatService
from app.retrieval.hybrid import HybridRetriever

ROOT = Path(__file__).parents[1]
DATA = Path(__file__).parent / "datasets"
BASE = "8eb48e32a821e6781500075d6a9d7e8dc3142346"


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def save(path: Path, value: object) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as f:
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    temporary.replace(path)


def identities() -> dict[str, Any]:
    paths = (
        list((ROOT / "app/agents/tool_rag").rglob("*.py"))
        + list((ROOT / "app/routing/intent_frame").glob("*.py"))
        + list((ROOT / "app/retrieval").glob("*.py"))
    )
    paths += [
        ROOT / "app/llm/openai_agent_service.py",
        ROOT / "app/llm/openai_service.py",
        ROOT / "app/core/config.py",
        ROOT / "app/embeddings/vector_store.py",
    ]
    sources = {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)
    }
    return {
        "sources": sources,
        "graph_tool_identity": digest({"sources": sources, "tools": ToolRegistry().definitions()}),
        "system_prompt_sha256": hashlib.sha256(AGENT_SYSTEM_PROMPT.encode()).hexdigest(),
    }


def cases(latest: str) -> list[dict[str, Any]]:
    rows = [
        ("DIRECT", "Hello", [], False, None, False, "DIRECT_REPLY", []),
        ("DIRECT", "What can you do?", [], False, None, False, "CAPABILITY_EXPLANATION", []),
        ("DIRECT", "Thanks for your help today!", [], False, None, False, "DIRECT_REPLY", []),
        (
            "INVENTORY",
            "Please list the indexed document filenames.",
            ["files_query"],
            False,
            None,
            False,
            "FILE_LIST",
            [],
        ),
        (
            "INVENTORY",
            "How many documents are indexed?",
            ["files_query"],
            False,
            None,
            False,
            "COUNT_SEVEN",
            [],
        ),
        (
            "INVENTORY",
            "Which indexed file is the newest?",
            ["files_query"],
            False,
            None,
            False,
            "LATEST_METADATA",
            [latest],
        ),
        (
            "KNOWLEDGE",
            "Who is the HarborDesk pilot intended for, and how many staff will it serve?",
            ["search_knowledge"],
            False,
            None,
            True,
            "GROUNDED_ANSWER",
            ["project_overview.txt"],
        ),
        (
            "KNOWLEDGE",
            "How does HarborDesk avoid losing or duplicating assignment notifications?",
            ["search_knowledge"],
            False,
            None,
            True,
            "GROUNDED_ANSWER",
            ["architecture_notes.txt", "engineering_decisions.txt"],
        ),
        (
            "KNOWLEDGE",
            "When is the pilot launch planned, and what gates must be completed first?",
            ["search_knowledge"],
            False,
            None,
            True,
            "GROUNDED_ANSWER",
            ["launch_plan.txt"],
        ),
        (
            "DEPENDENT",
            "List the files and summarize the first one.",
            ["files_query", "file_evidence"],
            True,
            0,
            True,
            "SUMMARIZE_ACTUAL_RESULT",
            ["architecture_notes.txt"],
        ),
        (
            "DEPENDENT",
            "Summarize the latest file.",
            ["files_query", "file_evidence"],
            True,
            None,
            True,
            "SUMMARIZE_ACTUAL_RESULT",
            [latest],
        ),
        (
            "DEPENDENT",
            "Please resolve engineering_decisions.txt and summarize that file.",
            ["resolve_file", "file_evidence"],
            True,
            None,
            True,
            "SUMMARIZE_ACTUAL_RESULT",
            ["engineering_decisions.txt"],
        ),
        (
            "DEPENDENT",
            "Show the indexed files, then give a brief overview of the second listed file.",
            ["files_query", "file_evidence"],
            True,
            1,
            True,
            "SUMMARIZE_ACTUAL_RESULT",
            ["customer_feedback.txt"],
        ),
        (
            "RESOLUTION",
            "Resolve architecture_notes.txt and confirm its exact filename.",
            ["resolve_file"],
            False,
            None,
            False,
            "RESOLVED_FILENAME",
            ["architecture_notes.txt"],
        ),
        (
            "RESOLUTION",
            "Find missing_training_handbook.txt and summarize it.",
            ["resolve_file"],
            False,
            None,
            False,
            "NOT_FOUND_EXPLANATION",
            [],
        ),
        (
            "UNSUPPORTED_SCOPE",
            "Count only the documents tagged confidential.",
            [],
            False,
            None,
            False,
            "UNSUPPORTED_SCOPE_EXPLANATION",
            [],
        ),
    ]
    result = []
    for i, (category, q, sequence, dependent, index, evidence, behavior, files) in enumerate(
        rows, 1
    ):
        operation = (
            "LIST"
            if i in (4, 10, 13)
            else "COUNT"
            if i == 5
            else "LATEST"
            if i in (6, 11)
            else None
        )
        result.append(
            {
                "case_id": f"agent-dev-{i:02d}",
                "category": category,
                "question": q,
                "expected_initial_tool": sequence[0] if sequence else "NO_TOOL",
                "acceptable_initial_alternates": [],
                "expected_tool_sequence": sequence,
                "expected_tool_count": len(sequence),
                "expected_inventory_operation": operation,
                "handle_dependency": dependent,
                "expected_handle_source_step": 1 if dependent else None,
                "expected_result_item_index": index,
                "evidence_required": evidence,
                "broadening_forbidden": dependent or i in (14, 15, 16),
                "expected_final_behavior": behavior,
                "expected_evidence_files": files,
                "grounding_policy": "Review every substantive final claim against returned authoritative evidence; corpus truth alone is insufficient. No exact prose gold.",
            }
        )
    assert len(result) == 16
    return result


async def demo_snapshot(db: AsyncSession, settings: Settings) -> tuple[dict[str, Any], str]:
    service = DemoCorpusService(db, settings)
    files, documents, chunks = await service.inspect_database(UUID(settings.demo_user_id))
    assert len(files) == len(documents) == 7 and len(chunks) == 7
    assert all(f.status == DriveFileStatus.INDEXED for f in files)
    assert await service.inspect_vectors(chunks=chunks)
    # Stored modification timestamps define recency. Never infer recency from text.
    snapshot = [
        {
            "id": str(f.id),
            "filename": f.name,
            "modified_at": f.modified_at.isoformat(),
            "status": f.status.value,
        }
        for f in sorted(files, key=lambda f: f.id.int)
    ]
    latest = min(files, key=lambda f: (-f.modified_at.timestamp(), f.id.int)).name
    return {
        "version": service.manifest.version,
        "files": snapshot,
        "content_hashes": {f.filename: f.sha256 for f in service.manifest.files},
    }, latest


def validate(dataset: dict[str, Any]) -> None:
    assert dataset["schema"] == "agent-smoke-gold-1.0" and dataset["split"] == "development"
    rows = dataset["cases"]
    assert len(rows) == len({c["case_id"] for c in rows}) == 16
    expected = {
        "DIRECT": 3,
        "INVENTORY": 3,
        "KNOWLEDGE": 3,
        "DEPENDENT": 4,
        "RESOLUTION": 2,
        "UNSUPPORTED_SCOPE": 1,
    }
    assert {k: sum(c["category"] == k for c in rows) for k in expected} == expected
    names = {cast(str, d["name"]) for d in ToolRegistry().definitions()}
    for case in rows:
        assert 0 < len(case["question"]) <= 8000
        assert set(case["expected_tool_sequence"]) <= names
        assert case["expected_tool_count"] == len(case["expected_tool_sequence"])
        assert case["expected_initial_tool"] == (
            case["expected_tool_sequence"][0] if case["expected_tool_sequence"] else "NO_TOOL"
        )
        if case["handle_dependency"]:
            assert (
                case["expected_handle_source_step"] == 1
                and case["expected_tool_sequence"][-1] == "file_evidence"
            )
        if case["expected_inventory_operation"]:
            ToolRegistry().get("files_query").validate_arguments(
                json.dumps(
                    {
                        "operation": case["expected_inventory_operation"],
                        "scope": {"kind": "ALL_ELIGIBLE_INDEXED_FILES"},
                    }
                )
            )


class RecordingChat:
    def __init__(self, delegate: AgentChatService, path: Path, record: dict[str, Any]) -> None:
        self.delegate = delegate
        self.path = path
        self.record = record

    async def step(
        self, *, messages: Sequence[AgentMessage], tools: Sequence[ToolDefinition]
    ) -> AgentStepResult:
        entry = {
            "status": "PENDING",
            "messages": [m.model_dump(mode="json") for m in messages],
            "tool_count": len(tools),
        }
        self.record["llm_steps"].append(entry)
        save(self.path, self.record)
        started = perf_counter()
        try:
            response = await self.delegate.step(messages=messages, tools=tools)
        except Exception:
            entry.update(status="UNKNOWN", latency_ms=(perf_counter() - started) * 1000)
            save(self.path, self.record)
            raise
        entry.update(
            status="SUCCESS",
            latency_ms=(perf_counter() - started) * 1000,
            response=response.model_dump(mode="json"),
        )
        save(self.path, self.record)
        return response


async def main() -> None:
    assert (
        subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
        == "refactor/tool-orchestrated-rag"
    )
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--revision",
        action="store_true",
        help="Same immutable cases, separate revision identity/results",
    )
    parser.add_argument("--env-file", action="append", default=[])
    args = parser.parse_args()
    assert not (args.freeze and args.execute)
    assert args.revision or head == BASE
    if args.revision:
        assert not subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        ).strip()
    factory = cast(type[BaseSettings], Settings)
    settings = cast(Settings, factory(_env_file=tuple(args.env_file)))
    assert settings.demo_mode and settings.demo_user_id and settings.openai_api_key
    engine = create_async_engine(settings.database_url)
    try:
        async with async_sessionmaker(engine)() as db:
            snapshot, latest = await demo_snapshot(db, settings)
            dataset_path = DATA / "agent_smoke_v1.json"
            freeze_path = DATA / "agent_smoke_v1_freeze.json"
            if args.freeze and not args.revision:
                assert not dataset_path.exists() and not freeze_path.exists()
                dataset = {
                    "schema": "agent-smoke-gold-1.0",
                    "split": "development",
                    "cases": cases(latest),
                }
                validate(dataset)
                save(dataset_path, dataset)
                save(DATA / "agent_smoke_v1_corpus.json", snapshot)
                freeze = {
                    "version": "agent-smoke-freeze-1.0",
                    "base_commit": BASE,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
                    "fixture_sha256": digest(snapshot),
                    **identities(),
                    "model_requested": settings.chat_model,
                    "gates": {
                        "initial_tool_min": 14,
                        "dependent_reuse": 4,
                        "invented_handles": 0,
                        "unsafe_scope_broadening": 0,
                        "corpus_fallback": 0,
                        "cycle_overrun": 0,
                        "private_id_leak": 0,
                        "direct_no_tool_min": 2,
                        "grounded_success_fraction": 1.0,
                    },
                }
                save(freeze_path, freeze)
                print(json.dumps({k: v for k, v in freeze.items() if k != "sources"}), flush=True)
                return
            dataset = json.loads(dataset_path.read_text())
            freeze = json.loads(freeze_path.read_text())
            validate(dataset)
            assert hashlib.sha256(dataset_path.read_bytes()).hexdigest() == freeze["dataset_sha256"]
            assert digest(snapshot) == freeze["fixture_sha256"]
            assert settings.chat_model == freeze["model_requested"]
            if args.revision:
                # Original dataset, corpus, prompt and observations are never overwritten.
                output = Path(__file__).parent / "results/agent_smoke_v1_revision"
                revision_path = output / "freeze.json"
                if args.freeze:
                    assert not revision_path.exists()
                    output.mkdir(parents=True, exist_ok=True)
                    revised = {
                        **freeze,
                        **identities(),
                        "version": "agent-smoke-revision-1.0",
                        "base_commit": head,
                        "first_run_commit": BASE,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                    save(revision_path, revised)
                    print(
                        json.dumps({k: v for k, v in revised.items() if k != "sources"}), flush=True
                    )
                    return
                freeze = json.loads(revision_path.read_text())
                assert freeze["base_commit"] == head
                assert (
                    freeze["dataset_sha256"]
                    == hashlib.sha256(dataset_path.read_bytes()).hexdigest()
                )
                assert freeze["fixture_sha256"] == digest(snapshot)
            assert identities()["graph_tool_identity"] == freeze["graph_tool_identity"]
            assert identities()["system_prompt_sha256"] == freeze["system_prompt_sha256"]
            print(
                json.dumps(
                    {
                        "preflight": "PASS",
                        "cases": 16,
                        "dataset": freeze["dataset_sha256"],
                        "model": settings.chat_model,
                        "live_steps": 0,
                    }
                ),
                flush=True,
            )
            if not args.execute:
                return
            output = Path(__file__).parent / (
                "results/agent_smoke_v1_revision" if args.revision else "results/agent_smoke_v1"
            )
            output.mkdir(parents=True, exist_ok=True)
            for case in dataset["cases"]:
                assert identities()["graph_tool_identity"] == freeze["graph_tool_identity"]
                assert (
                    hashlib.sha256(dataset_path.read_bytes()).hexdigest()
                    == freeze["dataset_sha256"]
                )
                path = output / (case["case_id"] + ".json")
                if path.exists():
                    retained = json.loads(path.read_text())
                    assert (
                        retained["dataset_identity"] == freeze["dataset_sha256"]
                        and retained["graph_tool_identity"] == freeze["graph_tool_identity"]
                    )
                    print(
                        json.dumps(
                            {
                                "case_id": case["case_id"],
                                "retained": True,
                                "status": retained["status"],
                            }
                        ),
                        flush=True,
                    )
                    continue  # Never repost completed OR unknown/pending paid cases.
                record = {
                    "case_id": case["case_id"],
                    "dataset_identity": freeze["dataset_sha256"],
                    "graph_tool_identity": freeze["graph_tool_identity"],
                    "status": "PENDING",
                    "model_requested": settings.chat_model,
                    "llm_steps": [],
                }
                save(path, record)
                chat = RecordingChat(OpenAIAgentChatService(settings), path, record)
                retriever = HybridRetriever(db, settings)
                started = perf_counter()
                state = await ToolRagAgentService(chat).run(
                    case["question"],
                    user_id=UUID(settings.demo_user_id),
                    db=db,
                    retriever=retriever,
                )
                record.update(
                    status="UNKNOWN"
                    if any(s["status"] != "SUCCESS" for s in record["llm_steps"])
                    else "COMPLETED",
                    latency_ms=(perf_counter() - started) * 1000,
                    failure=state["failure"],
                    cycle_count=state["cycle_count"],
                    final_answer=state["final_answer"],
                    tools=[
                        {
                            "call": h.call.model_dump(mode="json"),
                            "error_code": h.result.error.code.value if h.result.error else None,
                            "public_result": h.result.llm_result.model_dump(mode="json"),
                        }
                        for h in state["tool_history"]
                    ],
                    evidence=[s.model_dump(mode="json") for s in state["evidence"]],
                    citation_handles=[h.value for h in state["citation_handles"]],
                    citations=[c.model_dump(mode="json") for c in state["citations"]],
                    messages=[m.model_dump(mode="json") for m in state["messages"]],
                )
                save(path, record)
                print(
                    json.dumps(
                        {
                            "case_id": case["case_id"],
                            "status": record["status"],
                            "llm_steps": len(record["llm_steps"]),
                            "tools": [h.call.tool_name for h in state["tool_history"]],
                            "failure": state["failure"],
                        }
                    ),
                    flush=True,
                )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
