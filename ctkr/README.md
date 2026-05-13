# ctkr — Categorical-Theoretic Knowledge Representation

Layer-1 (mechanical) and Layer-3 (LLM-bridged) analysis over the MetaCoding
code graph. Python sub-project, co-located in the MetaCoding repo so it can
read `.metacoding/graph.lbug` and `.metacoding/tokens.fts.sqlite` directly.

The bun TypeScript root owns indexing (SCIP → ladybugdb + FTS). `ctkr` owns
everything downstream: subgraph mining, embeddings, topology, motif labeling,
cross-repo synthesis. See the bd issues prefixed `CTKR L1/*` and `CTKR L3/*`
for scope.

## Layout

```
ctkr/
├── pyproject.toml           # project metadata, deps, console-script
├── .python-version          # 3.12 (uv-managed)
├── ctkr/
│   ├── __init__.py
│   ├── __main__.py          # `python -m ctkr`
│   ├── cli.py               # subcommand discovery
│   └── commands/
│       ├── __init__.py
│       └── info.py          # `ctkr info` — seed subcommand + template
└── tests/
    └── test_cli.py
```

## Quickstart

From this directory (`MetaCoding/ctkr/`):

```bash
uv sync                # creates .venv, resolves & installs deps
uv run ctkr --help     # list subcommands
uv run ctkr info       # environment + artifact paths
uv run pytest          # run the test suite
```

`uv` pins to Python 3.12 (see `.python-version`). The bun/TS root and this
Python sub-project share the same git repo but have independent dependency
graphs.

## Adding a sub-command

`ctkr.cli` auto-discovers anything under `ctkr/commands/`. Each module needs
exactly two functions:

```python
# ctkr/commands/embed.py
import argparse

def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("embed", help="Run node2vec over the graph.")
    p.add_argument("--dim", type=int, default=128)
    p.set_defaults(func=run)

def run(args: argparse.Namespace) -> int:
    ...
    return 0
```

Drop the file, re-run `uv run ctkr --help`, and the new subcommand appears.
`info.py` is the canonical template.

For optional-heavy dependencies, declare an extras group in `pyproject.toml`
and `import` inside `run()` so the base install stays light:

```toml
[project.optional-dependencies]
embed = ["gensim>=4.3"]
```

Then `uv sync --extra embed` before running.

## Artifacts

`ctkr` reads from and writes to `<repo_root>/.metacoding/ctkr/`. Output schema
is defined by issue `Orchestrators-003 — CTKR L1/F3`. Until that lands, expect
parquet files (embeddings, motifs) and jsonl (patterns, evidence).
