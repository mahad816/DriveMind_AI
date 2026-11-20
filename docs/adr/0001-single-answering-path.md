---
status: accepted
---

# One answering path in the stable release: the tool-calling agent

After validation, the tool-calling agent is the only production answering system. Today three paths exist (linear hybrid pipeline, LangGraph workflow, tool-calling agent), and only the agent is the target of the evaluation harness; measuring, hardening and explaining three paths splits a sole maintainer's effort. The decision is accepted in principle; **no path is switched and no code is deleted until the steps below are approved.**

## Sequence

1. Verify the agent's functionality, its evaluation results and the deployed configuration (flags, commit, migration revision). The deployed state is currently unverified.
2. Once approved, disable normal production access to the linear and LangGraph paths.
3. Physically remove the unused legacy code afterward, in a separate, controlled cleanup milestone. Disabling and deleting are different steps so that a rollback stays cheap until the cleanup.

## Considered options

- **Keep all three paths indefinitely.** Rejected: ongoing maintenance and test burden for paths that would not be measured or improved, and the product's quality target (grounding, citations, honest answers) is being built in the agent.

## Consequences

- `AGENTS.md` currently says to preserve both grounded paths (linear and LangGraph) and to keep the tool-agent path. That rule changes **only when the migration is approved**, not by this ADR alone. Until then it stands.
- "Verify its evaluation results" in step 1 means the spec's quality gates. Known agent defects (wrong-file attribution KI-028, wrong sums KI-029) are tracked in `docs/KNOWN_ISSUES.md`. In the 2026-11-19 baseline the legacy pipeline scored higher on perturbed-unanswerable cases (7/7 against 4/7; `docs/EVALUATION_RESULTS.md`), so that comparison matters at step 1.
- Reliability work targets one path, and the evaluation measures the path users actually reach.
