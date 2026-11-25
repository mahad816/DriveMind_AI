#!/usr/bin/env bash
# Local development launcher for the backend. Sets NON-SECRET feature overrides only; secrets stay in
# backend/.env, which this script never reads. Remote and Railway settings are not affected.
#
#   scripts/dev-backend.sh                              # tool agent + C2-cap3 dual-query retrieval ON
#   RETRIEVAL_DUAL_QUERY_ENABLED=false scripts/dev-backend.sh   # C2 off (single-query retrieval)
#   TOOL_RAG_AGENT_ENABLED=false scripts/dev-backend.sh         # legacy answer path (C2 does not apply)
#
# The startup log prints one "effective_config" line with the flags this process really uses.
set -euo pipefail
cd "$(dirname "$0")/../backend"
export TOOL_RAG_AGENT_ENABLED="${TOOL_RAG_AGENT_ENABLED:-true}"
export RETRIEVAL_DUAL_QUERY_ENABLED="${RETRIEVAL_DUAL_QUERY_ENABLED:-true}"
exec uv run uvicorn app.main:app --reload --port "${PORT:-8000}" "$@"
