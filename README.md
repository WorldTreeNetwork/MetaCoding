# MetaCoding

*A local-first code-graph for AI coding agents. The structure was always there — this just listens for it.*

Underneath every codebase there's a graph no editor ever shows you: the
wiring between symbols, what calls what, what implements what, what
depends on what. The source files are the surface; the graph is the
thing. MetaCoding walks a project, builds that graph on disk, and
serves it back to an agent through MCP so it can ask the questions
that actually move work forward:

> who calls this? what implements `IFoo`? trace this controller all the way down to the database.

## Most tools listen for words

Vector RAG chunks source files into 1000-character windows and tosses
them at an index. That works when you can name what you're after. It
falls over the moment the question crosses an edge the type system
already knows — interface implementers, call graphs, dependency
injection — because those edges live in the wiring, not in the words.

MetaCoding's bet is that the wiring deserves first-class storage.
Five complementary lanes feed one embedded graph store:

| Lane | Purpose |
|---|---|
| **SCIP** | resolved symbol graph for committed code (TS / Python / Java / Go) |
| **LSP** | live overlay for dirty buffers and SCIP-missing languages |
| **Tree-sitter** | universal fallback; configs; pattern queries; bootstrap |
| **SQLite FTS5** | string DI, reflection, ORM table names, route literals — the AST blind spots |
| **Joern** (opt-in) | interprocedural dataflow / taint, on demand |

All five write into a single [ladybugdb](https://github.com/ladybugdb/ladybugdb)
graph (the maintained Kùzu fork) plus a SQLite FTS5 sidecar. One process,
two files on disk, no servers.

The graph is exposed over **MCP** as a small typed surface
(`graph_neighbors`, `graph_implementers`, `graph_callers`, `graph_diff`,
`code_search`, plus live `lsp_hover` / `lsp_diagnostics`, and the
`ctkr.*` categorical-knowledge tools — see
[mcp-surface.md](docs/design/mcp-surface.md)). The agent composes — it
doesn't author Cypher. Call `describe_api` to discover the live list.

## Status

Phases 1–4 of the build plan are wired and exercised by a smoke
gauntlet:

- Tree-sitter extractor (TS + Python), SCIP loader (TS + Python), LSP
  overlay (multilspy-style), FTS5 sidecar with a code-aware splitter.
- ladybugdb store with a single swap-boundary and the Bun finalizer
  mitigation lifted from Dreamball's spike (see
  [storage-integration.md](docs/design/storage-integration.md)).
- MCP server (stdio transport): seven core graph/FTS tools, four live
  LSP tools, and six `ctkr.*` categorical-knowledge tools over the
  cross-repo corpus artifacts.
- Incremental re-indexing keyed on AST hash; file watcher; branch
  auto-detect.
- `metacoding export` dumps the graph to JSONL for downstream analysis.

## CTKR — what the corpus already knows

The graph in one project is one thing. The *shapes that recur across
many projects* are another. CTKR is a structure-mining overlay,
[`ctkr/`](ctkr/), that walks a corpus of related codebases and asks:
what wiring shows up in many of them? When the same pattern surfaces
in thirty-eight projects under thirty-eight different names, that's a
design pattern — found, not declared. The names were always noise.
The arrows were always the signal.

CTKR finds the shapes. An LLM names them afterward — structure first,
language second. Motif mining, graph embeddings, persistent-homology
shape signatures, centrality, and an LLM-bridged labeler all read the
same store MetaCoding writes.

Think of MetaCoding as the **ground** and CTKR as a **listener** held
against it. CTKR is in active development; see
[`docs/design/ctkr.md`](docs/design/ctkr.md) for the long story and
[`docs/design/ctkr-artifacts.md`](docs/design/ctkr-artifacts.md) for
the concrete artifacts it produces.

## Install

MetaCoding is a [Bun](https://bun.sh) program — install Bun ≥ 1.1 first,
then install globally:

```bash
bun add -g @identikey/metacoding
metacoding --help
```

If `metacoding` isn't on your PATH, add Bun's global bin folder:

```bash
export PATH="$HOME/.cache/.bun/bin:$PATH"   # add to ~/.zshrc / ~/.bashrc
```

> `bunx @identikey/metacoding ...` is **not** supported — bunx skips the
> `optionalDependencies` and lifecycle scripts that ladybugdb's native
> binary depends on. Use `bun add -g` instead.

Wire it into Claude Code from inside a repo you've indexed:

```bash
metacoding index . --scip                       # indexes into XDG data dir (~/.local/share/metacoding/<repo-id>/)
claude mcp add metacoding -- metacoding serve   # writes .mcp.json
```

`--scip` needs no extra setup: the `@sourcegraph/scip-typescript` /
`scip-python` indexers ship as dependencies, so a global install already
has them. (To override with your own, `bun add -g` them onto PATH.)

Equivalent hand-rolled `.mcp.json`:

```json
{
  "mcpServers": {
    "metacoding": {
      "command": "metacoding",
      "args": ["serve"]
    }
  }
}
```

`metacoding serve` resolves `--data-dir` using the same order as `index`:
`--data-dir` flag first, then `./.metacoding/` if it already exists (legacy),
then the XDG per-repo location (`~/.local/share/metacoding/<repo-id>/`).
`--workspace` defaults to `.`.

### Give Claude the `/metacoding` skill

The MCP server exposes the tools; the bundled skill teaches an agent *when
and how* to reach for them. Install it once per machine:

```bash
metacoding install-skill        # copies the skill into ~/.claude/skills/
                                # (or --dir <path> for another harness)
```

Then restart Claude Code so `/metacoding` registers. Or install it as a
plugin without a global binary:

```
/plugin marketplace add WorldTreeNetwork/MetaCoding
/plugin install metacoding
```

## Quick start

```bash
# Index a codebase (writes to XDG data dir by default; adds SCIP resolved edges)
metacoding index . --scip

# Watch for changes (incremental re-index)
metacoding watch .

# Serve over MCP (stdio) — point Claude Code at this
metacoding serve

# Ad-hoc Cypher (escape hatch — prefer the typed MCP tools)
metacoding query 'MATCH (n:Symbol) RETURN count(n)'

# Dump the graph to JSONL for ctkr / external analysis
metacoding export ./out
```

Data dir resolution order: `--data-dir <path>` wins; then `./.metacoding/` if
it already exists (legacy, keeps existing installs working); otherwise
`$XDG_DATA_HOME/metacoding/<repo-id>/` (default
`~/.local/share/metacoding/<repo-id>/`), where `<repo-id>` is a 12-char
sha1 of `remote.origin.url` (or the repo toplevel for remotes-less repos),
shared across all worktrees of the same project. `metacoding index` prints
the resolved `dataDir` in its JSON output. `--workspace` (for `serve`)
defaults to `.`.

### From a clone (hacking on MetaCoding itself)

```bash
git clone https://github.com/WorldTreeNetwork/MetaCoding.git
cd MetaCoding
bun install
bun run src/cli/main.ts index <path> --data-dir <path>/.metacoding
```

A single shipped smoke command runs every lane end-to-end against a
test fixture:

```bash
bun run smoke
```

## Design principles

- **Deterministic before probabilistic.** AST / SCIP / LSP first; LLM
  extraction only where structure runs out of signal. The 2026 paper
  that motivated this (see
  [docs/research/paper-2601.08773v1.md](docs/research/paper-2601.08773v1.md))
  found probabilistic extraction was dominated 2× to 45× on cost,
  latency, and recall. Don't add it back without a reason that fits
  in one sentence.
- **Local-first, embedded.** No servers, no cloud, no Docker. One
  process, one on-disk DB. Your code stays where you put it; nothing
  phones home; the graph is yours.
- **Typed MCP surface.** Specific tools the agent will reach for
  (`graph_implementers`, `graph_callers`) over raw Cypher passthrough.
  Compose, don't bloat.
- **Layered fidelity.** Tree-sitter ships immediately at low fidelity;
  SCIP and LSP upgrade specific languages without reshaping the API.
- **Defer what isn't load-bearing.** No embeddings v0. No taint v0.
  Add a lane only when a class of questions fails through the existing
  ones.

## Layout

```
metacoding/
├── src/                          TypeScript / Bun — the indexer + MCP server
│   ├── extractor/                Tree-sitter walkers (TS, Python)
│   ├── scip/                     SCIP loader + runner
│   ├── lsp/                      Live LSP overlay
│   ├── store/                    ladybugdb + FTS5 single swap-boundary
│   ├── mcp/                      MCP server + tool handlers
│   └── cli/                      `metacoding` CLI entry points
├── ctkr/                         Python — the structure-mining overlay
├── docs/
│   ├── design/                   architecture, schema, MCP surface, build plan
│   └── research/                 paper notes, prior art
└── scripts/                      Smoke tests, peek-scip helpers
```

Design docs are the prose source of truth:

- [docs/design/architecture.md](docs/design/architecture.md) — the
  five-lane stack and why each lane earns its slot.
- [docs/design/schema.md](docs/design/schema.md) — graph node / edge
  schema (Joern CPG flattened) and the FTS table.
- [docs/design/mcp-surface.md](docs/design/mcp-surface.md) — concrete
  MCP tools.
- [docs/design/storage-integration.md](docs/design/storage-integration.md)
  — ladybugdb + FTS5 lifecycle, Bun finalizer mitigation, format
  compatibility notes.
- [docs/design/build-plan.md](docs/design/build-plan.md) — MVP order
  of operations and what each phase ships.
- [docs/design/ctkr.md](docs/design/ctkr.md) — the categorical
  knowledge-representation track.

## Stack

| Component | Choice |
|---|---|
| Runtime | Bun |
| Graph DB | ladybugdb (embedded Cypher; Kùzu fork) |
| Text index | SQLite FTS5 (trigram + code-aware splitter) |
| Parsers | Tree-sitter (every language) |
| Symbol resolution | SCIP indexers for HEAD; LSP for dirty / extra languages |
| Optional dataflow | Joern, out-of-band |
| Transport | MCP stdio |

## License

MIT — see [LICENSE](LICENSE).

---

*Built on the premise that the map already exists; you just have to read it.*
