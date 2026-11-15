# Artifactum from the shell

The `atfm` command works from bash and anything that can run a command: R, Snakemake, Nextflow, Make.
stdout carries only the result (a path or an ID), so commands compose; messages and errors go to stderr,
and a failure exits non-zero. Add `--json` to `get`, `publish`, `describe`, `log` or `run status` for one
JSON object instead.

## Read and publish

```bash
ref="$(atfm get GRCH38RF)"                  # local path to the artifact, fetched and cached
atfm get GRCH38RF -o data/                  # and copy it somewhere too

atfm publish aligned.bam \
  -d "Reads aligned with BWA-MEM" \
  -t alignment -t rna-seq \
  -n aligned_reads \
  --code align.sh \
  --docs README.md
```

| Option | Meaning |
| --- | --- |
| `-d`, `--description` | One line: what the file is |
| `-t`, `--tag` | Tag, repeatable |
| `-n`, `--name` | Make this a new version of whatever was published under this name |
| `-p`, `--parent` | Parent artifact ID, repeatable. Default: the run's inputs |
| `--no-parents` | Record no parents, even inside a run |
| `--code` | The script that made it, snapshotted as provenance |
| `--docs` | Markdown file shown on the artifact's page |

## Group commands into one run

Outside a run each command stands alone. Wrap a step so what it reads becomes the parents of what it
publishes:

```bash
eval "$(atfm run start 'align reads')"
bwa mem "$(atfm get GRCH38RF)" "$(atfm get FQ7R1A2B)" > aligned.sam
samtools sort -o aligned.bam aligned.sam
atfm publish aligned.bam -d "Reads aligned with BWA-MEM" --code align.sh
eval "$(atfm run end)"
```

`atfm run status --json` shows the current run and what it has read.

## R

```r
counts_path <- system2("atfm", c("get", "CNTS4M8B"), stdout = TRUE)
counts <- read.delim(counts_path)
# ...
id <- system2("atfm", c("publish", "de_results.tsv", "-d", shQuote("DESeq2 results, treated vs control")),
              stdout = TRUE)
```

## Snakemake

```python
rule align:
    output: "aligned.bam"
    shell:
        """
        eval "$(atfm run start align)"
        bwa mem "$(atfm get GRCH38RF)" "$(atfm get {config[reads]})" | samtools sort -o {output}
        atfm publish {output} -d "Aligned reads" --code workflow/Snakefile
        eval "$(atfm run end)"
        """
```

## Look things up

```bash
atfm describe CRED2S9Q          # record: description, tags, storage path, run, commit
atfm log CRED2S9Q               # upstream lineage as a tree
atfm log CRED2S9Q --json | jq -r '.parents[].id'
atfm code CRED2S9Q              # the code snapshot captured at publish
```
