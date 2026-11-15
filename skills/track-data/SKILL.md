---
name: track-data
description: Record data files with Artifactum (atfm) when writing or editing code that reads input data or writes results — Python scripts, notebooks, pipelines, R or shell steps. Use it whenever code loads a dataset, model, table or figure, or saves one, so inputs are read by artifact ID and outputs are published with their lineage.
---

# Track data with Artifactum

Artifactum (`atfm`) gives every data file a permanent ID and records where it came from: the artifacts the
code read, the git commit and code that ran, and who published it. Files stay in the team's own storage.

When you write code that reads or writes data, use it so the result joins the record:

1. **Read inputs by ID, through `atfm.artifact()`.** It returns a local path (fetched and cached), and records
   the read as an input of whatever this run publishes.
2. **Publish outputs with `atfm.publish()`.** Parents default to every artifact read in the run, so lineage
   is recorded without listing it.
3. **Keep plain paths for scratch and intermediate files** nobody else needs. Publish what someone may reuse,
   cite or need to trace: cleaned data, models, results tables, figures, reports.

```python
import artifactum as atfm
import pandas as pd

counts = pd.read_parquet(atfm.artifact("CNTS4M8B"))    # input: recorded as a parent
hits = call_hits(counts)
hits.to_csv("gene_hits.csv", index=False)

atfm.publish(
    "gene_hits.csv",
    description="Gene hits, MAGeCK MLE, LDL uptake",  # one line: what it is
    tags=["crispr", "hits"],
    name="ldl_uptake_hits",                            # versions: same name = new version
)
```

## Finding the ID of an input

Don't guess IDs. In order of preference:

- Ask the registry with the Artifactum MCP tools if they're connected: `search_artifacts(query, tags)`,
  then `get_artifact(id)` for its record and how to load it.
- From Python: `atfm.search("harmonised sumstats", tags=["gwas"])` returns matches with `.id`, `.name`,
  `.description`, `.superseded_by` and `.stale`.
- From the shell: `atfm describe ID` or `atfm log ID` (add `--json` to parse it).

If the data isn't in the registry yet, publish the raw file once (`atfm publish raw.csv -d "..."`) and read it
by its new ID from then on. Leave existing hard-coded paths alone unless the user wants them moved over.

## Publishing well

- `description`: one line saying what the file is, e.g. "SuSiE 95% credible sets, LDL". Not the file name.
- `tags`: a few lower-case words the team filters by (`["fine-mapping", "ldl"]`).
- `name`: give one when the file will be regenerated. Everything published under the same name is a version
  of it, and anything built from an older version is flagged stale. Without a name there are no versions.
- `docs`: Markdown shown on the artifact's page, as text or a path (`docs="README.md"`): purpose, method,
  samples, QC and caveats. Worth it for results others will use.
- `parents=[...]` sets inputs explicitly (for steps that read data outside `atfm.artifact()`);
  `parents=[]` records none.
- `publish()` returns the new ID. Identical content already in the registry returns the existing ID and
  uploads nothing, so re-running is safe.

## Several outputs from one script

Use `atfm.step()` so each output's parents are only what that step read:

```python
with atfm.step("normalise"):
    raw = sc.read_h5ad(atfm.artifact("QCFL2N6P"))
    sc.pp.normalize_total(raw)
    raw.write("normalized.h5ad")
    atfm.publish("normalized.h5ad", description="Library-size normalised", name="normalized")
```

It also works as a decorator (`@atfm.step()`); each call is its own step.

## Before you rely on an input

`atfm.artifact()` logs a warning when an ID is an old version (a newer one exists) or is stale (built from
inputs that changed). Tell the user rather than silently switching IDs: the old version may be intended,
for example to reproduce a published figure.

## Shell, R, Snakemake, Nextflow

See [references/shell.md](references/shell.md) for `atfm get`, `atfm publish` and `atfm run start/end`.

## When atfm isn't set up

If `import artifactum` fails or `atfm` says there's no config, use the `setup` skill: `pip install
artifactum`, then `atfm init` (the user supplies their own API token; never invent or ask them to paste one
into code).
