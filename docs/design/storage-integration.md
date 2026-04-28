# Storage integration

Concrete patterns for the ladybugdb + SQLite FTS5 layer. Most of these are lifted from Dreamball's selection ADR and Phase 0 spike — they did the validation work first; we benefit.

**Reference:** `~/projects/Dreamball/docs/decisions/2026-04-21-ladybugdb-selection.md`

## On-disk layout

One data directory per indexed repo:

```
.metacoding/
├── graph.lbug          ladybugdb columnar graph (Cypher)
├── graph.lbug.wal      write-ahead log (managed by ladybugdb)
└── tokens.fts.sqlite   SQLite FTS5 sidecar
```

Both files share a directory. The wrapper module owns both lifecycles together — open together, close together, atomic-ish snapshots together.

## Single swap-boundary

**Exactly one module imports the ladybugdb client.** Everything else calls into that module. Same rule for the FTS5 connection. If we ever swap stores (ladybugdb regresses, a different fork wins, vector lane gets added), one file changes.

In TypeScript/Bun:
```ts
// metacoding/store/index.ts — the only file that imports @ladybugdb/core
import { Database, Connection } from '@ladybugdb/core';
```

In Python:
```python
# metacoding/store/__init__.py — the only module that imports the ladybug binding
import ladybugdb  # or kuzu, whichever Python binding is current
```

The MCP tool handlers, the Tree-sitter writers, the SCIP loader — none of them import the DB client directly.

## Bun + `@ladybugdb/core`: the finalizer crash and its fix

If the MCP server runs on Bun, you will hit a Bun napi-finalizer segfault on process teardown — Dreamball's spike confirmed this on Bun 1.3.3 / `@ladybugdb/core` 0.15.3 (macOS arm64). Userland completes successfully, exit code is 0, and *then* Bun panics walking still-open native handles. The crash is in Bun, not in ladybugdb.

Two mitigations, either independently sufficient. **Apply both — belt and braces.**

### Mitigation 1: wrap every query result so callers can't forget close()

```ts
// metacoding/store/query.ts
export async function query<T>(
  conn: Connection,
  cypher: string,
  params?: unknown,
): Promise<T[]> {
  const qr = await conn.query(cypher, params);
  try {
    return (await qr.getAll()) as T[];
  } finally {
    await qr.close();
  }
}
```

Connection and Database are closed via `try/finally` at top-level teardown or process signal handler.

### Mitigation 2: explicit `process.exit(0)` on successful CLI runs

For short-lived CLI invocations, the exit-on-success path skips Bun's napi finalizer pass entirely. Cheap, effective, harmless.

```ts
async function main() {
  // ... CLI work ...
  process.exit(0);  // belt-and-braces; not load-bearing if Mitigation 1 is correct
}
```

Don't skip Mitigation 1 just because Mitigation 2 is in place — long-lived processes (the MCP server) won't have an exit path on every operation.

## Python equivalent

The same shape transposes to context managers. If we go Python:

```python
from contextlib import contextmanager

@contextmanager
def query_result(conn, cypher, params=None):
    qr = conn.query(cypher, params)
    try:
        yield qr.get_all()
    finally:
        qr.close()

# usage
with query_result(conn, "MATCH (n:Symbol) RETURN n LIMIT 10") as rows:
    ...
```

Top-level `Database` and `Connection` are owned by the MCP server lifecycle and closed in the shutdown handler.

Whether the Python ladybugdb binding has the same finalizer hazard as Bun's napi binding is unverified. Treat it as "likely yes," apply the same discipline; revisit if a Python-specific spike shows otherwise.

## FTS5 sidecar lifecycle

SQLite FTS5 lives in the same data directory as a separate file. Wrapper owns the connection alongside ladybugdb's:

```ts
class Store {
  private graphDb: Database;
  private graphConn: Connection;
  private fts: SqliteDatabase;  // bun:sqlite or better-sqlite3

  static async open(dataDir: string) { ... }
  async close()                       { ... }  // closes both, in order
}
```

Reads that need both lanes (graph match + string fallback) run them in parallel and merge in the wrapper. Writes happen in matching transactions on each store; we accept eventual consistency between graph and FTS for now (a token may be in FTS before its symbol node lands, briefly). If that ever bites, add a write coordinator.

## Browser fallback (deferred but worth knowing)

Dreamball's spike found that `@ladybugdb/wasm-core` 0.15.3 cannot persist a `.lbug` file in the browser today — the bundled FS configurations all fail (OPFS needs pthread context the default build doesn't have; multithreaded builds deadlock on PTHREAD_POOL_SIZE; sync build has Vite worker resolution issues).

The clean workaround: **use `kuzu-wasm@0.11.3` in the browser**. It's the last upstream Kùzu release before the Apple acqui-hire, supports IDBFS persistence (works under Vite + Chromium with no COOP/COEP setup), and is **storage-format compatible with `.lbug`** files written by `@ladybugdb/core`. So a graph indexed by our Bun MCP server can be loaded by a browser inspector lens later, byte-for-byte.

Not on the v0 path (we have no browser surface), but worth keeping in the schema discussion: don't introduce features that would break this compatibility (e.g., custom storage extensions only one runtime supports).

## MCP self-documentation endpoint

Dreamball ships a `/.well-known/mcp` endpoint that generates the API surface — routes, schemas, examples — at request time from the live route table and Valibot schemas. Drift between docs and reality is structurally impossible because the docs *are* the live registration data.

We should mirror this for MetaCoding's MCP server:

- A `describe_api` tool the agent can call to learn the full surface.
- Generated from whatever schema authority we pick (Pydantic/Valibot/zod), not hand-maintained.
- Includes per-tool examples drawn from a fixtures registry, not docstrings.

This is cheap to add at scaffold time and expensive to retrofit. Do it in Phase 1.

## Adopted decisions checklist

- [x] One data dir, two files (`graph.lbug` + `tokens.fts.sqlite`).
- [x] Single swap-boundary module imports the ladybugdb client.
- [x] Wrap every `QueryResult` in try/finally close().
- [x] CLI invocations call `process.exit(0)` on success (Bun route only).
- [x] Same try/finally discipline applied to FTS5 connections.
- [x] No features that break `.lbug` ↔ `kuzu-wasm@0.11.3` storage compatibility.
- [x] MCP self-doc endpoint generated from live schema; ship in Phase 1.
