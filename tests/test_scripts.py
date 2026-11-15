"""Tests for the plugin's hook and MCP-headers scripts. Standard library only: python -m unittest."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def run(script: str, stdin: dict | str = "", **env: str) -> subprocess.CompletedProcess:
    data = stdin if isinstance(stdin, str) else json.dumps(stdin)
    full_env = {k: v for k, v in os.environ.items() if not k.startswith(("ATFM_", "CLAUDE_", "PLUGIN_"))}
    full_env.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script)], input=data, capture_output=True, text=True, env=full_env, timeout=20
    )


def _client_visible_to_test_python() -> bool:
    import importlib.util

    return importlib.util.find_spec("artifactum") is not None


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        # Never read the real ~/.artifactum: every test points at its own config and state
        self.env = {"ATFM_CONFIG": str(self.tmp / "config.toml"), "PLUGIN_DATA": str(self.tmp / "data")}

    def config(self, token: str = "atfm_secret", server: str | None = None) -> None:
        lines = ["[default]", f'api_token = "{token}"', 'storage = "/groups/lab/atfm"']
        if server:
            lines.append(f'server_url = "{server}"')
        (self.tmp / "config.toml").write_text("\n".join(lines) + "\n")


class HeadersHelper(Base):
    def test_sends_the_saved_key_to_its_own_server(self) -> None:
        self.config()
        r = run("atfm_headers.py", **self.env, CLAUDE_CODE_MCP_SERVER_URL="https://atfm.io/mcp")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"Authorization": "Bearer atfm_secret"})

    def test_never_sends_a_key_to_another_server(self) -> None:
        self.config(server="https://atfm.mylab.org")
        r = run("atfm_headers.py", **self.env, CLAUDE_CODE_MCP_SERVER_URL="https://atfm.io/mcp")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")
        self.assertIn("ATFM_SERVER_URL", r.stderr)
        # Pointed at its own server, it works
        r = run("atfm_headers.py", **self.env, CLAUDE_CODE_MCP_SERVER_URL="https://atfm.mylab.org/mcp")
        self.assertEqual(json.loads(r.stdout)["Authorization"], "Bearer atfm_secret")

    def test_the_environment_key_wins(self) -> None:
        self.config()
        r = run("atfm_headers.py", **self.env, ATFM_API_KEY="atfm_env", CLAUDE_CODE_MCP_SERVER_URL="https://atfm.io/mcp")
        self.assertEqual(json.loads(r.stdout)["Authorization"], "Bearer atfm_env")

    def test_no_key_explains_what_to_do(self) -> None:
        r = run("atfm_headers.py", **self.env, CLAUDE_CODE_MCP_SERVER_URL="https://atfm.io/mcp")
        self.assertEqual(r.returncode, 1)
        self.assertIn("atfm init", r.stderr)


class SessionStart(Base):
    def context(self, cwd: str | None = None, **env: str) -> str:
        event = {"hook_event_name": "SessionStart", "source": "startup", "cwd": cwd or str(self.tmp)}
        r = run("session_start.py", event, **self.env, **env)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "SessionStart")
        return out["additionalContext"]

    def test_says_to_use_atfm_for_data(self) -> None:
        self.config()
        (self.tmp / ".venv" / "bin").mkdir(parents=True)
        (self.tmp / ".venv" / "bin" / "atfm").write_text("")  # the client, installed in the project
        text = self.context()
        self.assertIn("atfm.artifact", text)
        self.assertIn("track-data", text)
        self.assertIn("set up for https://atfm.io", text)
        self.assertNotIn("atfm_secret", text)  # the key never reaches the model

    def test_says_when_the_client_is_not_installed(self) -> None:
        self.config()
        # No atfm on PATH and none importable
        bare = {"PATH": str(self.tmp / "nothing"), "PYTHONNOUSERSITE": "1"}
        if _client_visible_to_test_python():
            self.skipTest("artifactum is importable from the test's Python")
        text = self.context(**bare)
        self.assertIn("client was not found", text)
        self.assertIn("pip install artifactum", text)
        # Installed in the project's own venv counts
        exe = self.tmp / ".venv" / "bin" / "atfm"
        exe.parent.mkdir(parents=True)
        exe.write_text("")
        self.assertIn("set up for https://atfm.io", self.context(**bare))

    def test_points_to_setup_when_not_configured(self) -> None:
        self.assertIn("setup skill", self.context())

    def test_can_be_turned_off(self) -> None:
        r = run("session_start.py", "{}", **self.env, ATFM_AGENT_HOOKS="off")
        self.assertEqual(r.stdout, "")


class DataCodeCheck(Base):
    def write(self, name: str, code: str) -> Path:
        path = self.tmp / name
        path.write_text(textwrap.dedent(code))
        return path

    def hook(self, tool_input: dict, session: str = "s1", **env: str) -> str:
        event = {"hook_event_name": "PostToolUse", "session_id": session, "cwd": str(self.tmp),
                 "tool_name": "Write", "tool_input": tool_input}
        r = run("data_code_check.py", event, **self.env, **env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_reminds_once_about_python_that_does_data_io_without_atfm(self) -> None:
        f = self.write("analysis.py", """
            import pandas as pd
            df = pd.read_csv("counts.csv")
            df.to_parquet("clean.parquet")
        """)
        out = self.hook({"file_path": str(f)})
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("analysis.py", ctx)
        self.assertIn("atfm.publish", ctx)
        self.assertEqual(self.hook({"file_path": str(f)}), "")  # once per file per session
        self.assertNotEqual(self.hook({"file_path": str(f)}, session="s2"), "")  # a new session asks again

    def test_quiet_when_the_file_already_uses_atfm(self) -> None:
        f = self.write("tracked.py", """
            import artifactum as atfm
            import pandas as pd
            df = pd.read_parquet(atfm.artifact("CNTS4M8B"))
        """)
        self.assertEqual(self.hook({"file_path": str(f)}), "")

    def test_quiet_for_code_without_data_and_other_files(self) -> None:
        f = self.write("utils.py", "def add(a, b):\n    return a + b\n")
        self.assertEqual(self.hook({"file_path": str(f)}), "")
        r = self.write("notes.md", "pd.read_csv('x')")
        self.assertEqual(self.hook({"file_path": str(r)}), "")

    def test_reads_codex_apply_patch_and_notebooks(self) -> None:
        self.write("plot.py", "import matplotlib.pyplot as plt\nplt.savefig('fig.png')\n")
        nb = {"cells": [{"cell_type": "code", "source": ["import scanpy as sc\n", "adata = sc.read_h5ad('x.h5ad')\n"]}]}
        (self.tmp / "explore.ipynb").write_text(json.dumps(nb))
        patch = "*** Begin Patch\n*** Update File: plot.py\n@@\n-x\n+y\n*** Add File: explore.ipynb\n+...\n*** End Patch\n"
        out = self.hook({"command": patch})
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("plot.py", ctx)
        self.assertIn("explore.ipynb", ctx)

    def test_can_be_turned_off(self) -> None:
        f = self.write("a.py", "import pandas as pd\npd.read_csv('x')\n")
        self.assertEqual(self.hook({"file_path": str(f)}, ATFM_AGENT_HOOKS="off"), "")

    def test_bad_input_never_breaks_the_agent(self) -> None:
        r = run("data_code_check.py", "not json", **self.env)
        self.assertEqual((r.returncode, r.stdout), (0, ""))


class FakeRegistry:
    """A local stand-in for the server's /artifacts/status route, recording what it was sent."""

    STATUS = {
        "NORM0001": {"id": "NORM0001", "found": True, "filename": "norm.parquet", "superseded_by": "NORM0002",
                     "stale": False, "outdated_inputs": []},
        "MODL0001": {"id": "MODL0001", "found": True, "filename": "model.pkl", "superseded_by": None, "stale": True,
                     "outdated_inputs": [{"id": "NORM0001", "newer_version": "NORM0002"}]},
        "GOOD0001": {"id": "GOOD0001", "found": True, "filename": "ok.csv", "superseded_by": None, "stale": False,
                     "outdated_inputs": []},
    }

    def __init__(self) -> None:
        self.requests: list[dict] = []
        registry = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                url = urlsplit(self.path)
                ids = parse_qs(url.query).get("ids", [""])[0].split(",")
                registry.requests.append({"path": url.path, "ids": ids, "auth": self.headers.get("Authorization")})
                body = json.dumps({"artifacts": {i: registry.STATUS.get(i, {"id": i, "found": False}) for i in ids}})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body.encode())

            def log_message(self, *args) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class OutdatedInputs(DataCodeCheck):
    def setUp(self) -> None:
        super().setUp()
        self.registry = FakeRegistry()
        self.addCleanup(self.registry.close)
        self.config(server=self.registry.url)

    def test_notes_old_versions_and_stale_inputs_once_per_session(self) -> None:
        f = self.write("train.py", """
            import artifactum as atfm
            import pandas as pd
            norm = pd.read_parquet(atfm.artifact("NORM0001"))
            model = atfm.artifact(id='modl0001')
            ok = atfm.artifact("GOOD0001")
        """)
        out = self.hook({"file_path": str(f)})
        ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("train.py", ctx)
        self.assertIn("NORM0001 (norm.parquet) is an older version; the newest is NORM0002", ctx)
        self.assertIn("MODL0001 (model.pkl) is stale", ctx)
        self.assertNotIn("GOOD0001", ctx)
        self.assertIn("don't switch silently", ctx)
        [req] = self.registry.requests
        self.assertEqual(req["path"], "/artifacts/status")
        self.assertEqual(req["ids"], ["NORM0001", "MODL0001", "GOOD0001"])
        self.assertEqual(req["auth"], "Bearer atfm_secret")
        # Edited again in the same session: IDs already checked aren't sent or noted again
        self.assertEqual(self.hook({"file_path": str(f)}), "")
        self.assertEqual(len(self.registry.requests), 1)

    def test_checks_shell_and_workflow_files_too(self) -> None:
        f = self.write("Snakefile", "rule fetch:\n    shell: 'atfm get NORM0001 > norm.parquet'\n")
        self.assertIn("NORM0001", self.hook({"file_path": str(f)}))

    def test_quiet_when_every_id_is_current_or_unknown(self) -> None:
        f = self.write("ok.py", 'import artifactum as atfm\natfm.artifact("GOOD0001")\natfm.artifact("ZZZZ9999")\n')
        self.assertEqual(self.hook({"file_path": str(f)}), "")

    def test_quiet_and_retries_later_when_the_registry_is_unreachable(self) -> None:
        self.registry.close()
        f = self.write("t.py", 'import artifactum as atfm\natfm.artifact("NORM0001")\n')
        self.assertEqual(self.hook({"file_path": str(f)}), "")
        # Back online: the ID wasn't marked as checked, so it's checked now
        self.registry = FakeRegistry()
        self.addCleanup(self.registry.close)
        self.config(server=self.registry.url)
        self.assertIn("NORM0001", self.hook({"file_path": str(f)}))

    def test_sends_nothing_without_a_key(self) -> None:
        (self.tmp / "config.toml").unlink()
        f = self.write("t.py", 'import artifactum as atfm\natfm.artifact("NORM0001")\n')
        self.assertEqual(self.hook({"file_path": str(f)}), "")
        self.assertEqual(self.registry.requests, [])

    def test_both_notes_can_come_together(self) -> None:
        a = self.write("untracked.py", "import pandas as pd\npd.read_csv('x.csv')\n")
        b = self.write("tracked.py", 'import artifactum as atfm\natfm.artifact("NORM0001")\n')
        patch = "*** Begin Patch\n*** Update File: untracked.py\n*** Update File: tracked.py\n*** End Patch\n"
        ctx = json.loads(self.hook({"command": patch}))["hookSpecificOutput"]["additionalContext"]
        self.assertIn("untracked.py reads or writes data files", ctx)
        self.assertIn("tracked.py reads artifacts that have newer data", ctx)
        del a, b


class Manifests(unittest.TestCase):
    def test_every_manifest_is_valid_json_and_agrees(self) -> None:
        files = [".claude-plugin/plugin.json", ".claude-plugin/marketplace.json", ".codex-plugin/plugin.json",
                 "plugin.json", "mcp.json", ".agents/plugins/marketplace.json", "hooks/hooks.json"]
        data = {f: json.loads((ROOT / f).read_text()) for f in files}
        versions = {data[f]["version"] for f in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json", "plugin.json")}
        self.assertEqual(len(versions), 1, versions)
        self.assertEqual(data[".claude-plugin/marketplace.json"]["plugins"][0]["name"], "artifactum")
        self.assertEqual(data[".agents/plugins/marketplace.json"]["plugins"][0]["name"], "artifactum")
        # Every hook command names a script that exists
        for groups in data["hooks/hooks.json"]["hooks"].values():
            for g in groups:
                for h in g["hooks"]:
                    script = h["command"].split("/scripts/")[1].rstrip('"')
                    self.assertTrue((SCRIPTS / script).exists(), script)

    def test_every_skill_has_a_name_and_description(self) -> None:
        skills = sorted((ROOT / "skills").glob("*/SKILL.md"))
        self.assertEqual([s.parent.name for s in skills], ["setup", "trace-provenance", "track-data"])
        for s in skills:
            head = s.read_text().split("---")[1]
            self.assertIn(f"name: {s.parent.name}\n", head)
            self.assertIn("description: ", head)


if __name__ == "__main__":
    unittest.main()
