"""Tests for the plugin's hook and MCP-headers scripts. Standard library only: python -m unittest."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
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
    def context(self, **env: str) -> str:
        r = run("session_start.py", {"hook_event_name": "SessionStart", "source": "startup"}, **self.env, **env)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "SessionStart")
        return out["additionalContext"]

    def test_says_to_use_atfm_for_data(self) -> None:
        self.config()
        text = self.context()
        self.assertIn("atfm.artifact", text)
        self.assertIn("track-data", text)
        self.assertIn("set up for https://atfm.io", text)
        self.assertNotIn("atfm_secret", text)  # the key never reaches the model

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
