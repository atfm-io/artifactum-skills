"""PostToolUse hook: two checks on code the agent just wrote, both as `additionalContext` (never blocking).

Runs after Write/Edit/MultiEdit (Claude Code) and apply_patch (Codex).

1. Untracked data code: a .py file (or notebook) that does data I/O without artifactum gets a reminder
   to use the track-data skill, at most once per file per session.
2. Outdated inputs: IDs the code reads (`atfm.artifact("ID")`, `atfm get ID`) are checked with the
   registry; an old version or a stale artifact gets a note, at most once per ID per session. This sends
   only the IDs, to the server the user's key belongs to, and stays quiet if it can't reach it.

Set ATFM_AGENT_HOOKS=off to silence both.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import atfm_config  # noqa: E402

PY_SUFFIXES = (".py", ".ipynb")
# Files whose artifact IDs are checked: Python, plus the shell, R and workflow files the CLI is used from
ID_SUFFIXES = PY_SUFFIXES + (".sh", ".bash", ".R", ".r", ".Rmd", ".qmd", ".smk", ".nf", "Snakefile")
# atfm.artifact("ID") / artifactum.artifact('ID') / artifact(id="ID"), and `atfm get ID` / `atfm describe ID`
ID_REFS = re.compile(
    r"""\bartifact\(\s*(?:id\s*=\s*)?["']([A-Za-z0-9]{8})["']
      | \batfm\s+(?:get|describe|log|code)\s+([A-Za-z0-9]{8})\b""",
    re.X,
)
STATUS_TIMEOUT = 4  # seconds; the hook's own limit is 10

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


def read_code(path: str) -> str | None:
    """A file's code (a notebook's code cells), or None if it can't be read."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if path.endswith(".ipynb"):
        try:
            cells = json.loads(text).get("cells", [])
            text = "\n".join("".join(c.get("source", "")) for c in cells if c.get("cell_type") == "code")
        except (ValueError, AttributeError):
            return None
    return text


def needs_reminder(path: str, text: str | None = None) -> bool:
    if not path.endswith(PY_SUFFIXES):
        return False
    text = read_code(path) if text is None else text
    return bool(text) and bool(DATA_IO.search(text)) and not USES_ATFM.search(text)


def artifact_ids(path: str, text: str | None) -> list[str]:
    if not text or not path.endswith(ID_SUFFIXES):
        return []
    return list(dict.fromkeys((a or b).upper() for a, b in ID_REFS.findall(text)))


def fetch_status(ids: list[str]) -> dict | None:
    """{id: status} from the user's registry, or None if there's no key or it can't be reached."""
    cfg = atfm_config.load()
    if not cfg["token"] or not ids:
        return None
    url = f"{cfg['server']}/artifacts/status?" + urllib.parse.urlencode({"ids": ",".join(ids)})
    if not atfm_config.same_origin(url, cfg["server"]):
        return None
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {cfg['token']}",
                                               "User-Agent": "artifactum-agent-plugin"})
    try:
        with urllib.request.urlopen(req, timeout=STATUS_TIMEOUT) as r:
            return json.load(r).get("artifacts") or {}
    except Exception:  # offline, old server, bad key: say nothing rather than get in the way
        return None


def describe(a: dict) -> str:
    label = f"{a['id']} ({a['filename']})" if a.get("filename") else a["id"]
    if a.get("superseded_by"):
        return f"{label} is an older version; the newest is {a['superseded_by']}."
    inputs = ", ".join(f"{i['id']} (newer: {i['newer_version']})" for i in a.get("outdated_inputs") or [])
    return f"{label} is stale: it was built from inputs that have newer versions since" + (
        f": {inputs}." if inputs else ".")


OUTDATED = (
    "Artifactum: {file} reads artifacts that have newer data. {details} If the old version is intended (for "
    "example to reproduce a published result), keep it. Otherwise tell the user and offer to switch to the "
    "newer ID; don't switch silently. For a stale artifact, the rerun_plan MCP tool says what to rebuild."
)


def _state_file(session: str) -> Path:
    base = os.environ.get("PLUGIN_DATA") or os.environ.get("CLAUDE_PLUGIN_DATA") or tempfile.gettempdir()
    key = hashlib.sha256(session.encode()).hexdigest()[:16]
    return Path(base, f"atfm-reminded-{key}.json")


def _load_seen(session: str) -> set[str]:
    try:
        return set(json.loads(_state_file(session).read_text()))
    except (OSError, ValueError, TypeError):
        return set()


def _save_seen(session: str, seen: set[str]) -> None:
    state = _state_file(session)
    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps(sorted(seen)))
    except OSError:
        pass


def first_time(session: str, key: str) -> bool:
    """True the first time `key` comes up in this session (and remembers it)."""
    seen = _load_seen(session)
    if key in seen:
        return False
    _save_seen(session, seen | {key})
    return True


def main() -> int:
    if os.environ.get("ATFM_AGENT_HOOKS", "").lower() in ("off", "0", "false"):
        return 0
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    session = str(event.get("session_id") or "no-session")
    messages: list[str] = []

    texts = {p: read_code(p) for p in edited_files(event) if p.endswith(ID_SUFFIXES)}
    untracked = [p for p, t in texts.items() if needs_reminder(p, t) and first_time(session, p)]
    if untracked:
        messages.append(REMINDER.format(file=", ".join(os.path.basename(p) for p in untracked)))

    # Outdated inputs: check each ID once per session, and only note the ones worth a word
    seen = _load_seen(session)
    to_check = {p: [i for i in artifact_ids(p, t) if f"id:{i}" not in seen] for p, t in texts.items()}
    pending = list(dict.fromkeys(i for ids in to_check.values() for i in ids))
    status = fetch_status(pending) if pending else None
    if status is not None:
        _save_seen(session, _load_seen(session) | {f"id:{i}" for i in pending})
        for p, ids in to_check.items():
            notes = [describe(status[i]) for i in ids
                     if status.get(i, {}).get("found") and (status[i].get("superseded_by") or status[i].get("stale"))]
            if notes:
                messages.append(OUTDATED.format(file=os.path.basename(p), details=" ".join(notes)))

    if messages:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": event.get("hook_event_name") or "PostToolUse",
                "additionalContext": "\n\n".join(messages),
            }
        }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
