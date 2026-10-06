"""Offline frozen D3 dataset validation; no datastore or provider calls."""

import hashlib
import json
import subprocess
from evaluation.agent_smoke_runner import DATA, ROOT, BASE, digest, validate
from app.demo.manifest import load_manifest


def test_frozen_sixteen_case_gold_and_identities():
    dataset = json.loads((DATA / "agent_smoke_v1.json").read_text())
    freeze = json.loads((DATA / "agent_smoke_v1_freeze.json").read_text())
    validate(dataset)
    assert (
        hashlib.sha256((DATA / "agent_smoke_v1.json").read_bytes()).hexdigest()
        == freeze["dataset_sha256"]
    )
    assert (
        freeze["dataset_sha256"]
        == "76e507c694d449f346a879852ac8fef11c28cea99139c2470c81f34d77e87336"
    )
    assert (
        freeze["graph_tool_identity"]
        == "3f20bbab9e60903a7d02ce36c4ae74af5b270e6449f631249acf86987f6d9677"
    )
    assert (
        freeze["system_prompt_sha256"]
        == "b3fea837ec8087e94b877d57d8a093b6a6637386b17dc73727f328b8216f6164"
    )
    # Verify historical identities against immutable first-run Git objects. The
    # revised implementation has a separate identity, not rewritten first gold.
    for path, expected in freeze["sources"].items():
        original = subprocess.check_output(["git", "show", f"{BASE}:backend/{path}"], cwd=ROOT)
        assert hashlib.sha256(original).hexdigest() == expected
    snapshot = json.loads((DATA / "agent_smoke_v1_corpus.json").read_text())
    assert digest(snapshot) == freeze["fixture_sha256"]
    manifest = load_manifest()
    assert set(snapshot["content_hashes"]) == {entry.filename for entry in manifest.files}
    for entry in manifest.files:
        manifest.read_sample(entry.filename)
        assert snapshot["content_hashes"][entry.filename] == entry.sha256
    assert sum(case["handle_dependency"] for case in dataset["cases"]) == 4
    assert sum(case["category"] == "DIRECT" for case in dataset["cases"]) == 3
    assert freeze["gates"]["initial_tool_min"] == 14
