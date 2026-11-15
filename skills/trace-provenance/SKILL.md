---
name: trace-provenance
description: Answer questions about data from the Artifactum registry — what a file, figure or result is built from, who made it and with which code, what is out of date (stale or superseded), what a collection holds, what the team published recently — and find the right artifact to load. Use when the user asks about the origin, lineage, freshness or location of their data or results.
---

# Trace provenance with Artifactum

Answer from the record, not from guesses. Artifactum knows, for each artifact: its inputs (lineage), the
run that made it (git commit, command, code snapshot, packages), who published, edited and used it, its
versions, and the team's data card for it.

## Tools

If the Artifactum MCP server is connected (tools named `search_artifacts`, `get_artifact`, ...), use it:

| Question | Tool |
| --- | --- |
| Find an artifact by words or tags | `search_artifacts(query, tags, status, limit)`; `status` is `current`, `stale` or `superseded` |
| Everything about one artifact | `get_artifact(id)`: description, tags, storage path, run, docs, uses, version status, how to load it |
| What it's built from / what's built on it | `get_lineage(id, depth)`: nodes and parent→child edges |
| What's stale, most used, recent | `registry_overview()` |
| What to rerun after an input changed | `rerun_plan(artifact_id)`: ordered steps, each a run to repeat (script, argv, commit), what it rebuilds, the IDs to change in the code and the steps to do first. Empty `artifact_id` = the whole registry |
| Are these IDs current? (e.g. every `atfm.artifact("...")` in a script) | `check_versions(artifact_ids)` |
| What happened lately | `recent_activity(limit, kinds)` |
| Collections | `list_collections()`, then `get_collection(id)` |

Without MCP, use the CLI: `atfm describe ID --json`, `atfm log ID --json`, `atfm code ID`, and from Python
`atfm.search(...)`.

## How to answer well

- **Name things the way people do**: file name, then ID (`association_loci.tsv`, LOCI6R2T). Quote IDs
  exactly; they're permanent and citable.
- **Lineage**: walk `get_lineage` far enough to reach raw inputs when asked "what is this built from". Group
  the answer by project or step rather than dumping every node.
- **Stale vs superseded**: *superseded* means a newer version of the same name exists. *Stale* means the
  artifact is current but one of its inputs has since been replaced, so it was built from out-of-date data.
  Only direct children of a replaced input are marked stale; `rerun_plan` covers everything further
  downstream too. Stale doesn't mean wrong: say what changed and let the user judge.
- **Bringing things up to date**: use `rerun_plan` and present its steps in order. Code reads inputs by ID,
  so rerunning a script unchanged reads the old version again: for each step, change the `update_inputs`
  IDs to their `newer_version`, and inputs rebuilt by earlier steps (`after_steps`) to the IDs those steps
  publish. Steps with no `run` were published without recorded code. Don't rerun anything without asking.
- **Collections** hold either exact versions (`tracks: "id"`, e.g. a paper's inputs) or the latest version
  of each name (`tracks: "latest"`). In a latest-tracking collection, `follows` is the name and
  `added_version` the ID originally added.
- **Show your working** briefly: which tools you called and what they returned, so the user can check.
- **Be clear about the record's edges**: Artifactum records what passes through it. A file read directly
  (not through `atfm.artifact()`) isn't in the lineage, and nothing in the record says whether a result is
  scientifically right.

## Loading what you found

When the user wants to use an artifact in code, give them the ID and the read call, using the
`track-data` skill:

```python
import artifactum as atfm
credible_sets = pd.read_parquet(atfm.artifact("CRED2S9Q"))
```

Prefer the current version. If the user asked for a specific (older) one, use it and mention that a newer
version exists.
