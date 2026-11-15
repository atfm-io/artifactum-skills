"""SessionStart hook: tell the agent Artifactum is here, and to use it for data in code it writes.

Prints one JSON object with `additionalContext` (read by Claude Code and Codex). Kept short: it is
added to every session. Set ATFM_AGENT_HOOKS=off to silence it.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

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


# Project environments the client is often installed in, relative to the project directory
_PROJECT_ENVS = (".venv/bin", "venv/bin", ".venv/Scripts", ".pixi/envs/default/bin")


def client_installed(cwd: str | None) -> bool:
    """Whether the atfm client is reachable: on PATH, importable here, or in the project's own environment."""
    if shutil.which("atfm") or importlib.util.find_spec("artifactum") is not None:
        return True
    root = Path(cwd or os.getcwd())
    return any((root / env / exe).exists() for env in _PROJECT_ENVS for exe in ("atfm", "atfm.exe"))


def context(cwd: str | None = None) -> str:
    cfg = atfm_config.load()
    if not cfg["configured"]:
        status = (
            "atfm is not set up on this machine yet (no ~/.artifactum/config.toml). If the user wants to record "
            "data, use the setup skill; they run `atfm init` with their own API key."
        )
    elif not client_installed(cwd):
        status = (
            f"atfm is configured for {cfg['server']} (the MCP tools work), but the atfm client was not found in "
            "this environment: no `atfm` command on PATH and `import artifactum` fails. Before running code that "
            "uses it, install it into the project's environment (`pip install artifactum`; see the setup skill)."
        )
    else:
        status = f"atfm is set up for {cfg['server']}."
    return f"{GUIDANCE} {status}"


def main() -> int:
    if os.environ.get("ATFM_AGENT_HOOKS", "").lower() in ("off", "0", "false"):
        return 0
    try:
        event = json.loads(sys.stdin.read() or "{}")
        cwd = event.get("cwd") if isinstance(event, dict) else None
    except Exception:
        cwd = None
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context(cwd)}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
