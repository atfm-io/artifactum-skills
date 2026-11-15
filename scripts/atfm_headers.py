"""MCP headers helper: prints {"Authorization": "Bearer <token>"} for the Artifactum MCP server.

Claude Code runs this when it connects (`headersHelper` in .mcp.json), so the key `atfm init` saved is
used without copying it anywhere. The token is only sent to the server it belongs to: if the MCP URL's
origin differs from the configured server (a self-hosted team, say), nothing is sent.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import atfm_config  # noqa: E402


def main() -> int:
    cfg = atfm_config.load()
    url = os.environ.get("CLAUDE_CODE_MCP_SERVER_URL", cfg["server"] + "/mcp")
    if not cfg["token"]:
        print("Artifactum: no API key. Run `atfm init`, or set ATFM_API_KEY.", file=sys.stderr)
        return 1
    if not atfm_config.same_origin(url, cfg["server"]):
        print(
            f"Artifactum: your key is for {cfg['server']}, not {url}. Set ATFM_SERVER_URL to your server.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"Authorization": f"Bearer {cfg['token']}"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
