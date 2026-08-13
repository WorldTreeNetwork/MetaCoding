
Default to using Bun instead of Node.js.

- Use `bun <file>` instead of `node <file>` or `ts-node <file>`
- Use `bun test` instead of `jest` or `vitest`
- Use `bun build <file.html|file.ts|file.css>` instead of `webpack` or `esbuild`
- Use `bun install` instead of `npm install` or `yarn install` or `pnpm install`
- Use `bun run <script>` instead of `npm run <script>` or `yarn run <script>` or `pnpm run <script>`
- Use `bunx <package> <command>` instead of `npx <package> <command>`
- Bun automatically loads .env, so don't use dotenv.

## APIs

- `Bun.serve()` supports WebSockets, HTTPS, and routes. Don't use `express`.
- `bun:sqlite` for SQLite. Don't use `better-sqlite3`.
- `Bun.redis` for Redis. Don't use `ioredis`.
- `Bun.sql` for Postgres. Don't use `pg` or `postgres.js`.
- `WebSocket` is built-in. Don't use `ws`.
- Prefer `Bun.file` over `node:fs`'s readFile/writeFile
- Bun.$`ls` instead of execa.

## Testing

Use `bun test` to run tests.

```ts#index.test.ts
import { test, expect } from "bun:test";

test("hello world", () => {
  expect(1).toBe(1);
});
```

## Frontend

Use HTML imports with `Bun.serve()`. Don't use `vite`. HTML imports fully support React, CSS, Tailwind.

Server:

```ts#index.ts
import index from "./index.html"

Bun.serve({
  routes: {
    "/": index,
    "/api/users/:id": {
      GET: (req) => {
        return new Response(JSON.stringify({ id: req.params.id }));
      },
    },
  },
  // optional websocket support
  websocket: {
    open: (ws) => {
      ws.send("Hello, world!");
    },
    message: (ws, message) => {
      ws.send(message);
    },
    close: (ws) => {
      // handle close
    }
  },
  development: {
    hmr: true,
    console: true,
  }
})
```

HTML files can import .tsx, .jsx or .js files directly and Bun's bundler will transpile & bundle automatically. `<link>` tags can point to stylesheets and Bun's CSS bundler will bundle.

```html#index.html
<html>
  <body>
    <h1>Hello, world!</h1>
    <script type="module" src="./frontend.tsx"></script>
  </body>
</html>
```

With the following `frontend.tsx`:

```tsx#frontend.tsx
import React from "react";
import { createRoot } from "react-dom/client";

// import .css files directly and it works
import './index.css';

const root = createRoot(document.body);

export default function Frontend() {
  return <h1>Hello, world!</h1>;
}

root.render(<Frontend />);
```

Then, run index.ts

```sh
bun --hot ./index.ts
```

For more information, read the Bun API docs in `node_modules/bun-types/docs/**.mdx`.

## Agent workflows

### Ralph / ultrawork + long-running subprocesses

**Anti-pattern.** OMC's `ralph` and `ultrawork` skills are driven by a "boulder
never stops" stop hook that fires on every assistant turn regardless of elapsed
real time. When the actual blocker on progress is a long-running subprocess the
harness cannot track (a `--scip` reindex, a multi-minute test suite, an
external CI run, a remote queue), each boulder tick still demands a response —
turning a genuine wait into a rapid poll loop that burns tokens without
producing progress.

Symptoms observed in the 2026-05-28 session:
- Stop hook reinforces "continue working" while the only sensible action is
  waiting for an out-of-band process.
- Cancellation via `/oh-my-claudecode:cancel` clears state files but the hook
  may keep firing for one or more turns from stale skill-active reinforcements.
- The "skill-active" state file (`skill-active-state.json`) is the usual
  culprit when the hook keeps firing after `state_clear` reports no state to
  clear; clear it explicitly as the final step of any cancel.

**Convention.** When task progress depends on a background subprocess the
harness can't track:

1. **Exit ralph/ultrawork explicitly** rather than emitting wait-loop
   responses. Invoke `/oh-my-claudecode:cancel` and return control to the
   user, who can re-invoke ralph after the subprocess finishes.
2. **Don't sleep inside the loop** to mask the wait — that just delays the
   same token-spending tick.
3. **Use `run_in_background: true`** for any process that the harness *can*
   track (Bun's tool will notify on completion); reserve cancel-and-resume
   for genuinely external waits.
4. **Always clear `skill-active` state** as the final step of any cancel —
   `state_clear(mode="ralph")` does not clear it on its own.

**Upstream issue (recommended follow-up).** The real fix lives in OMC's ralph
skill: after N consecutive assistant turns with no tool calls or only
status-check calls, exponentially back off the boulder cadence. Filing an
issue against `oh-my-claudecode` is tracked separately — see bead
`MetaCoding-4jw` for the discussion.

### Command timing — MEASURED, and the number I first wrote here was wrong

**Measured 2026-08-12, by running them:**

| command | wall clock |
|---|---|
| `bun test` (MetaCoding, 580 tests / 43 files) | **~38-41s** |
| `bun test` (farmos-port, 980 tests / 76 files) | **~2s** |
| `bun run smoke` | **~0.7s** — it fails fast at `smoke-extractor.ts` (`6ep`) |

**Nothing in this project takes 16 minutes.** An earlier version of this section said
`bun test` took ~16 minutes and told agents never to foreground it. That figure was
inferred from stall-gap adjacency in agent transcripts — the longest gap in a dying
agent happened to follow a `bun test` call — and I wrote it here as measured fact
without running the command. Running it takes 40 seconds. Correlation was read as
causation and then promoted to documentation; this is the same failure the rest of
this file is about, committed while writing the file about it.

**So we do not know what stalled those agents.** The `bun test` explanation is
refuted. Candidates not yet tested: long model-streaming gaps with no tool call,
`metacoding index` / `loadScip` (genuinely slow — ~170-220s per repo, see the
data-dir section below), or a harness-level stall. **Do not optimize the test suite
on the strength of this — it is not the bottleneck.**

What survives the correction, because it was observed rather than inferred:

- **A killed agent's uncommitted work is a poison pill.** On 2026-08-12 one agent
  finished correct work, died before committing, and five successive retries each
  spent their whole budget re-discovering the dirty tree it left: 3h22m of wall clock
  and ~1.77M tokens for zero output, until 375 orphaned lines were rescued by hand.
  **COMMIT INCREMENTALLY.** If you are about to start something long, commit first.
- **File beads before composing the report.** A judge killed that same night had
  already filed `hy6.52`-`hy6.57`; its prose was lost and its findings survived.
- Still use `run_in_background` or an explicit `timeout` for anything genuinely long
  (indexing, scip, an external process) — the advice is sound even though the example
  that motivated it was wrong.

### Parallel agents share one worktree — stage by path

Never use the stage-everything commit flag. It stages every modified file,
including work belonging to other agents running at the same time. On 2026-08-12
it swept three other agents' uncommitted changes into a commit labelled
`fix(hy6.60)` — 13 files, toolchain and testkit work filed under a
verdict-currency bead — and one of those agents then died before recording its own
evidence, so its work survives under someone else's message.

The commit messages are this project's best instrument: a process-observing agent
reconstructed four days of analysis from `git log` alone. A commit that misstates
what it contains poisons the artifact everything else is rebuilt from. A
`PreToolUse` hook now refuses it.

Also observed the same day: agents clobbering each other's mutation sandboxes in
the shared scratchpad, and full-suite runs showing phantom failures from a
neighbour's uncommitted edits. When dispatching parallel agents, give each one
disjoint FILES — not just disjoint beads — tell it which paths belong to others,
and have it stage by path.

### Absolute paths, always

A `cd <path> && <interpreter>` compound does not reliably hold cwd here. On
2026-08-12 that landed four mutations in the real source and shipped a gate that
passed everything (`MetaCoding-hy6.52`). A `PreToolUse` hook in
`.claude/settings.json` now refuses that shape — see `docs/design/enforceability.md`.

### Reading the oracle — use `tools/oracle_read.py`, and never read `[]` as "none"

The live farmOS oracle is at `localhost:8095`. To read it:

```bash
python3 /Users/dukejones/work/WorldTree/farmos-port/tools/oracle_read.py /api/asset/plant
python3 /Users/dukejones/work/WorldTree/farmos-port/tools/oracle_read.py --types
```

**An unauthenticated JSON:API read does not fail.** It returns `200` with
`data: []` and hides the reason in `meta.omitted`. A reader who does not look at
`meta` concludes *the oracle has no records* instead of *I am anonymous* — charter
I3, absence of an answer read as an answer, sitting in the path of every reading.
Measured 2026-08-12 (`MetaCoding-4ifi`): two fresh readers both named the oracle
rule, not their time box, as what limited them, and one filed **zero of nine**
guards as witnessed. `oracle_read.py` refuses instead of returning what it cannot
see, and it can only issue GETs.

**"GET-only" never meant "do not authenticate."** Minting a token is not a
mutation. What is forbidden is state: no POST/PATCH/DELETE of entity data, no
fixtures, no trace; never `drush en` a module by hand; never move an image pin;
never `bring-up.sh` to "start" it (that runs `drush site-install` and would
**rebuild** the site — use `tools/oracle_up.sh`); never restart it. **It is shared
with concurrent agents** and holds the state 43 sealed packs were observed against.

A `404` usually means **the module is not enabled**, not a wrong path — four of
seven asset bundles are 404 today (`MetaCoding-ahrq`). A bundle you cannot GET is
one no finding about it can ever witness; say so in the report rather than
treating it as absence of evidence.

### Reporting data-dir scope on artifact-producing tasks

**Anti-pattern.** In the 2026-05-28 session, three executor agents reindexed
into `/tmp` sandboxes (correctly, to avoid lock contention with the running
`serve` process) but their summary reports said *"Reindex completed"* without
surfacing that the data lived in `/tmp/metacoding-9le`, not the user's
production `$ORCHESTRATORS_ROOT/.metacoding/`. The mismatch was caught only
by checking file timestamps — one iteration away from compounding into wasted
work against the wrong directory.

**Convention.** When you are an agent (or delegating to an agent) on a task
that produces or mutates data artifacts (graph stores, parquet files, indexes,
caches, etc.), the final report MUST explicitly include:

1. **The data-dir path of every artifact produced.** Absolute paths only;
   `~` and `$VAR` expand differently in different shells.
2. **Whether that path is the user's production location or a sandbox.**
   Production = the path a downstream consumer (`serve`, MCP tools, the eval
   harness) will read by default. Sandbox = anything else, including
   `/tmp/*`, `/var/tmp/*`, scratch worktrees, or any path the user did not
   ask for by name.
3. **If sandbox: what was different about the run from a production reindex.**
   A different `--scip` flag, a subset of repos, a different `--data-dir`,
   skipped tokens, no commit-identity scoping — anything the user would need
   to know before promoting the sandbox output to production.

This applies even when the task is "successful" — the failure mode is silent
ambiguity, not error. Default to over-reporting locations rather than
under-reporting.


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
### The iteration loop (read `docs/design/iteration-methodology.md`)

**red → green → *how would I fake this?* → refactor.** The third step is not
optional and is not the same as refactoring: on 2026-07-20 an invariant ("the
defendant holds no pen") was refactored into place faithfully and then handed the
pen back through a new public verb. The invariant was satisfied; the intention was
not. Ask what would satisfy the check while defeating its purpose, before shipping.

- **State a red as a PROPERTY, not as a defect to block.** "Attack N must fail"
  moves sideways; "a port wrong about the source cannot score better than one
  that is right" moves toward the goal and can subsume whole families of findings.
- **Tier by what you are touching.** Instrument (judge, recorder, fixture schema,
  kernel, a bound decision) → fresh adversaries, full weight. Measured thing (a
  feature port, a build, a pack) → green + the fake-it question + a discriminating
  fixture. An instrument that is cheap to change is one nobody can trust.
- **Definition of done: a fix ships with the evidence that would catch its
  regression.** A fix in the code and not in the evidence has a half-life.
- **A contrast pair and a mutation test are one operation** — `src/testkit/discriminate.ts`.
  Two inputs, one verdict function returning a NAMED tag (never a boolean, never a
  throw), and tags that must differ. The argument lives in that file's header, at the
  point of import; this is a pointer, not the home.
- **A floor is not a number** — `src/testkit/floors.ts`. It is a PAIR: a value and the
  NAME of the field the instrument publishes it against, and a floor over a field
  nobody emits is an INSTRUMENT failure, never a pass. Counts are derived from
  `run.check()`, never written down. Same rule: the argument is in that file's header.
- **Self-verification is never load-bearing.** Measured, not assumed: builds have
  documented "load-bearing" gates that were not, comments have claimed source
  semantics the code did not implement, and a test called a hook that does not
  exist and passed. Every real finding came from a fresh adversary or the live
  source. Judges are always fresh, never the builder — and a judge must prove
  which tree it tested before its findings count.

## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->
