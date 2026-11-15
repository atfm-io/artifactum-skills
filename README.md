<p align="center"><img src="assets/icon.png" width="96" alt="Artifactum"></p>

# Artifactum for coding agents

Plugins for **Claude Code** and **Codex** that make your agent work with [Artifactum](https://atfm.io)
(`atfm`), the registry and lineage tracker for the files your team's code produces.

- **Agents write the tracking.** When your agent writes Python that reads or writes data, it reads inputs
  by ID with `atfm.artifact()` and publishes results with `atfm.publish()`, so every result is recorded
  with what it was made from.
- **Agents read the record.** The plugin connects your agent to your team's registry over MCP, so you can
  ask "what is Figure 2 built from?", "what's out of date?" or "where are the CRISPR screen hits?" and get
  answers from the record, not guesses.

## What's in it

| | |
| --- | --- |
| **Skills** | `track-data`: read inputs and publish outputs with lineage, from Python, shell, R, Snakemake or Nextflow. `trace-provenance`: answer lineage, staleness and "where did this come from" questions. `setup`: install, `atfm init`, and fixing the connection. |
| **MCP server** | `https://atfm.io/mcp`: search the registry, read an artifact's record and data card, walk lineage, list stale artifacts and collections, check IDs for newer versions, and plan what to rerun when an input changes. Read-only. |
| **Hooks** | At session start, a short note that Artifactum is available and when to use it. After the agent writes or edits code: a one-time reminder when a `.py` file or notebook loads or saves data without Artifactum, and a note when the code reads an artifact ID that has a newer version or is stale (only the IDs are sent, to your own server). None of them ever blocks the agent. |

## Install

First install the client and sign in, once per machine. Get an API key from Settings at
[atfm.io](https://atfm.io):

```bash
pip install artifactum
atfm init
```

### Claude Code

```
/plugin marketplace add atfm-io/artifactum-skills
/plugin install artifactum@artifactum-skills
```

The MCP connection uses the key `atfm init` saved in `~/.artifactum/config.toml`; there is nothing else to
configure. Check it with `/mcp`. To use a different key, set `ATFM_API_KEY` before starting Claude Code.

### Codex

```bash
codex plugin marketplace add atfm-io/artifactum-skills
```

Then open `/plugins` in Codex (or the Plugins tab in the app), install **Artifactum**, and start a new
session. Codex asks for your API key when it connects to the MCP server. Codex asks you to review and trust
plugin hooks before they run (`/hooks`).

If you'd rather configure the MCP server yourself, add this to `~/.codex/config.toml` and export
`ATFM_API_KEY`:

```toml
[mcp_servers.artifactum]
url = "https://atfm.io/mcp"
bearer_token_env_var = "ATFM_API_KEY"
```

## Options

| Environment variable | Effect |
| --- | --- |
| `ATFM_AGENT_HOOKS=off` | Turn off the session note and the data-code reminders |
| `ATFM_API_KEY` | Use this key for the MCP connection instead of the one `atfm init` saved |
| `ATFM_SERVER_URL` | A self-hosted Artifactum server, e.g. `https://atfm.mylab.org` (Claude Code) |

Your key is only ever sent to the server it was saved for.

## Without the plugin

The skills are plain [Agent Skills](https://agentskills.io): copy `skills/*` into `~/.claude/skills/`,
`~/.agents/skills/` or your project's `.agents/skills/` to use them with any agent that reads them. For
an always-on instruction without hooks, add a line like this to your project's `AGENTS.md` or `CLAUDE.md`:

> When code reads or writes data files, use Artifactum: read inputs with `atfm.artifact("ID")` and publish
> results with `atfm.publish(...)` so their lineage is recorded.

## Development

```bash
python -m unittest -v tests/test_scripts.py     # the hook and headers scripts
claude plugin validate ./                       # the Claude Code manifests
```

One repository serves both agents. Shared: `skills/`, `hooks/hooks.json` and `scripts/`. Claude Code reads
`.claude-plugin/` (its MCP server is declared in `plugin.json`). Codex reads `plugin.json`,
`.codex-plugin/plugin.json`, `mcp.json` and `.agents/plugins/marketplace.json`. Keep the version the same in
all three plugin manifests.

[Docs](https://atfm.io/docs#agents) · [Privacy](https://atfm.io/privacy) · [Terms](https://atfm.io/terms) ·
[Python client](https://github.com/atfm-io/artifactum) · MIT License
