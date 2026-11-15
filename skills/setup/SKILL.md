---
name: setup
description: Set up Artifactum (atfm) on this machine and connect it to the agent — install the Python package, run `atfm init`, check the MCP connection, and fix "no config", authentication or connection errors. Use when atfm isn't installed or configured, or the artifactum MCP tools aren't working.
---

# Set up Artifactum

## 1. Install the client

```bash
pip install artifactum                 # shared directory storage
pip install 'artifactum[gcs]'          # Google Cloud Storage
```

Install it into the environment the project's code runs in (the project's venv, conda env or pixi
environment), not just the system Python. Check with `python -c "import artifactum"` and `atfm --version`.

## 2. Configure it: the user runs `atfm init`

`atfm init` asks for the user's **API key** (from Settings at https://atfm.io) and **where files are stored**
(a shared directory like `/groups/lab/atfm`, or `gs://bucket/path`). It saves them in
`~/.artifactum/config.toml`.

The API key is the user's secret. Ask the user to run `atfm init` themselves in their own terminal. Never
ask them to paste the key into the chat, never write it into code, a notebook or a committed file, and
never print the config file.

If their team uses shared storage, use the same location as everyone else: files are recorded by path, so
teammates must reach it at the same path. Their team admin or the Getting started page at atfm.io says
which.

## 3. The agent's connection (MCP)

**Claude Code**: the plugin connects to `https://atfm.io/mcp` using the key `atfm init` saved, so there is
nothing else to set up. Run `/mcp` to check that `artifactum` is connected. If it isn't:

- "no API key": `atfm init` hasn't been run, or set `ATFM_API_KEY` in the environment Claude Code starts in.
- A self-hosted Artifactum server: set `ATFM_SERVER_URL` (e.g. `https://atfm.mylab.org`) before starting
  Claude Code. The key is only sent to the server it was saved for.
- A 401 error: the key was revoked; make a new one in Settings and run `atfm init` again.

**Codex**: the plugin declares the server with API-key authentication, so Codex asks for the key when the
plugin is installed or first used. Alternatively, add the server to `~/.codex/config.toml` yourself:

```toml
[mcp_servers.artifactum]
url = "https://atfm.io/mcp"
bearer_token_env_var = "ATFM_API_KEY"
```

and export `ATFM_API_KEY` before starting Codex.

A read-only API key (made in Settings) is enough for the MCP tools; publishing from code needs a
full-access key in `atfm init`.

## 4. Try it

```bash
atfm describe <ID>       # an artifact the user knows, or:
python -c "import artifactum as atfm; print(atfm.search('')[:3])"
```

Then publish something small to see it end to end: `atfm publish results.csv -d "Test"` prints its new ID.
