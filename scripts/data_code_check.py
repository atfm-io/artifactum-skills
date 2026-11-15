"""PostToolUse hook: after the agent writes Python that reads or writes data without Artifactum, remind it.

Runs after Write/Edit/MultiEdit (Claude Code) and apply_patch (Codex). It never blocks: when a .py file
(or notebook) now does data I/O and doesn't use artifactum, it returns `additionalContext` suggesting the
track-data skill. Each file gets at most one reminder per session, so it doesn't nag. Set
ATFM_AGENT_HOOKS=off to silence it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

PY_SUFFIXES = (".py", ".ipynb")

# Calls that read or write data files, across the usual Python data stack
DATA_IO = re.compile(
    r"""
    \b(?:pd|pandas|pl|polars|dd|np|numpy|sc|scanpy|ad|anndata|xr|xarray|gpd|torch|joblib|pickle|h5py|pq|pyarrow|mu)\s*\.\s*
        (?:read_\w+|scan_\w+|load\w*|save\w*|open_\w+|File|dump)\s*\(
    | \.(?:to_csv|to_parquet|to_excel|to_json|to_feather|to_hdf|to_pickle|to_netcdf|to_zarr|
          write_h5ad|write_parquet|write_csv|write_loom|savefig)\s*\(
    | \bplt\.savefig\s*\(
    """,
    re.X,
)
USES_ATFM = re.compile(r"^\s*(?:import\s+artifactum|from\s+artifactum\s+import)", re.M)

REMINDER = (
    "{file} reads or writes data files but doesn't use Artifactum. If any of its inputs are in the user's "
    "registry, read them with atfm.artifact(\"ID\"), and publish results others may reuse with "
    "atfm.publish(path, description=..., tags=..., name=...) so their lineage is recorded (see the artifactum "
    "track-data skill). Skip this for scratch files, or if the user doesn't want tracking here."
)


def edited_files(event: dict) -> list[str]:
    """The files a Write/Edit/MultiEdit/apply_patch call touched."""
    tool_input = event.get("tool_input") or {}
    paths = []
    if isinstance(tool_input, dict) and tool_input.get("file_path"):
        paths.append(tool_input["file_path"])
    # apply_patch carries a patch: "*** Add File: path" / "*** Update File: path" headers
    texts = [v for v in (tool_input.values() if isinstance(tool_input, dict) else [tool_input]) if isinstance(v, str)]
    for text in texts:
        paths += re.findall(r"^\*\*\* (?:Add|Update) File: (.+?)\s*$", text, re.M)
        paths += re.findall(r"^\*\*\* Move to: (.+?)\s*$", text, re.M)
    cwd = event.get("cwd") or os.getcwd()
    return [str(Path(cwd, p)) if not os.path.isabs(p) else p for p in dict.fromkeys(paths)]


def needs_reminder(path: str) -> bool:
    if not path.endswith(PY_SUFFIXES):
        return False
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if path.endswith(".ipynb"):
        try:
            cells = json.loads(text).get("cells", [])
            text = "\n".join("".join(c.get("source", "")) for c in cells if c.get("cell_type") == "code")
        except ValueError:
            return False
    return bool(DATA_IO.search(text)) and not USES_ATFM.search(text)


def _state_file(session: str) -> Path:
    base = os.environ.get("PLUGIN_DATA") or os.environ.get("CLAUDE_PLUGIN_DATA") or tempfile.gettempdir()
    key = hashlib.sha256(session.encode()).hexdigest()[:16]
    return Path(base, f"atfm-reminded-{key}.json")


def first_time(session: str, path: str) -> bool:
    """True the first time `path` comes up in this session (and remembers it)."""
    state = _state_file(session)
    try:
        seen = set(json.loads(state.read_text()))
    except (OSError, ValueError):
        seen = set()
    if path in seen:
        return False
    seen.add(path)
    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps(sorted(seen)))
    except OSError:
        pass
    return True


def main() -> int:
    if os.environ.get("ATFM_AGENT_HOOKS", "").lower() in ("off", "0", "false"):
        return 0
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    session = str(event.get("session_id") or "no-session")
    files = [p for p in edited_files(event) if needs_reminder(p) and first_time(session, p)]
    if not files:
        return 0
    names = ", ".join(os.path.basename(p) for p in files)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event.get("hook_event_name") or "PostToolUse",
            "additionalContext": REMINDER.format(file=names),
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
