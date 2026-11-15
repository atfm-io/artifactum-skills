"""SessionStart hook: tell the agent Artifactum is here, and to use it for data in code it writes.

Prints one JSON object with `additionalContext` (read by Claude Code and Codex). Kept short: it is
added to every session. Set ATFM_AGENT_HOOKS=off to silence it.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import atfm_config  # noqa: E402

GUIDANCE = (
    "Artifactum (atfm) is this user's registry for data files and their lineage. "
    "When you write or edit code that reads input data or writes results (datasets, models, tables, figures), "
    "use the artifactum track-data skill: read inputs with atfm.artifact(\"ID\") and publish outputs with "
    "atfm.publish(...), so each result is recorded with what it was made from. Scratch files can stay plain paths. "
    "For questions about where data came from, who made it, or what is out of date, use the trace-provenance "
    "skill and the artifactum MCP tools (search_artifacts, get_artifact, get_lineage, registry_overview)."
)


def context() -> str:
    cfg = atfm_config.load()
    if not cfg["configured"]:
        status = (
            "atfm is not set up on this machine yet (no ~/.artifactum/config.toml). If the user wants to record "
            "data, use the setup skill; they run `atfm init` with their own API key."
        )
    else:
        status = f"atfm is set up for {cfg['server']}."
    return f"{GUIDANCE} {status}"


def main() -> int:
    if os.environ.get("ATFM_AGENT_HOOKS", "").lower() in ("off", "0", "false"):
        return 0
    try:
        sys.stdin.read()  # the event; nothing in it changes what we say
    except Exception:
        pass
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context()}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
