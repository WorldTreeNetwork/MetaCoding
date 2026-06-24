
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
