/**
 * The stage-everything commit hook, tested where tests actually run.
 *
 * WHY THIS FILE EXISTS AND WHY IT IS HERE
 * =======================================
 * `docs/design/enforceability.md` says only four things execute in this project,
 * and a shell script sitting in `.claude/` is not one of them. The hook itself IS
 * enforced — Claude Code runs it on every Bash call — but nothing checked that it
 * refuses the right things, so it drifted into refusing the WRONG things and
 * nobody found out until it blocked live work.
 *
 * On 2026-08-12 two fresh readers were dispatched to read `spine-asset` and
 * `spine-taxonomy-b`. The hook refused three well-formed, staged-by-path commits
 * because the substring `-asset` inside `spine-asset` — in the COMMIT MESSAGE —
 * matched its flag-cluster pattern `-[a-zA-Z]*a`. Replaying the old pattern here
 * shows it also refused `--amend` and `--author`: five legitimate forms.
 *
 * A guard that fires on the wrong input teaches people to route around it, and a
 * routed-around guard protects nothing. So the pattern is now pinned by the case
 * that broke it plus its contrast, and it is read from the REAL settings.json —
 * a copy of the regex in this file would pass forever while the deployed hook
 * said something else.
 */
import { test, expect } from "bun:test";
import { execFileSync } from "node:child_process";

const SETTINGS = new URL("../../.claude/settings.json", import.meta.url).pathname;

/** The deployed hook command, read from settings.json — never a copy of it. */
function hookCommand(): string {
  const doc = JSON.parse(require("node:fs").readFileSync(SETTINGS, "utf8"));
  const found: string[] = [];
  for (const group of doc?.hooks?.PreToolUse ?? []) {
    for (const h of group?.hooks ?? []) {
      const c = String(h?.command ?? "");
      if (c.includes("commit") && c.includes("--all")) found.push(c);
    }
  }
  // Exactly one. Zero means the hook was deleted and every case below would
  // "pass" as ALLOW — absence of the guard must fail, never quietly succeed.
  expect(found.length).toBe(1);
  return found[0]!;
}

/** Run the real hook against a real stdin payload. Deny => non-empty stdout. */
function verdict(command: string): "REFUSE" | "ALLOW" {
  const out = execFileSync("bash", ["-c", hookCommand()], {
    input: JSON.stringify({ tool_input: { command } }),
    encoding: "utf8",
  });
  return out.trim().length > 0 ? "REFUSE" : "ALLOW";
}

// Assembled from fragments so this FILE never contains the literal the hook
// greps for — otherwise editing this test trips the hook that guards it.
const A = "-" + "a";
const AM = "-" + "am";
const ALL = "--" + "all";

test("it refuses the thing it exists to refuse", () => {
  expect(verdict(`git commit ${A} -m "wip"`)).toBe("REFUSE");
  expect(verdict(`git commit ${AM} "wip"`)).toBe("REFUSE");
  expect(verdict(`git commit ${ALL} -m "wip"`)).toBe("REFUSE");
  expect(verdict(`git -C /repo commit ${A}`)).toBe("REFUSE");
  expect(verdict(`git commit -q${A.slice(1)} -m "wip"`)).toBe("REFUSE");
});

test("a bead or path containing a hyphen-a is NOT a flag — the case that blocked two readers", () => {
  // These are verbatim the shapes the readers were refused on.
  expect(
    verdict('git -C /r commit -m "reading(hy6.63): cheap-scope reading of spine-asset store"'),
  ).toBe("ALLOW");
  expect(verdict('git -C /r commit -m "fix: spine-taxonomy-a and the wave-2 analysis"')).toBe(
    "ALLOW",
  );
  expect(verdict('git -C /r commit -m "port_runs/wave2/spine-asset/build/shared-store"')).toBe(
    "ALLOW",
  );
});

test("ordinary commit forms are not collateral", () => {
  expect(verdict('git commit -q -m "chore: beads"')).toBe("ALLOW");
  expect(verdict("git commit --amend --no-edit")).toBe("ALLOW");
  expect(verdict('git commit --author="A B <a@b>" -m "x"')).toBe("ALLOW");
});

test("the guard is not satisfied by refusing everything", () => {
  // The contrast that makes the refusals above mean something. A hook that
  // denied every command would pass the first test and is worthless; a hook that
  // allowed everything would pass this one. Both directions are required.
  expect(verdict('git commit -m "ordinary"')).toBe("ALLOW");
  expect(verdict(`git commit ${A} -m "hazard"`)).toBe("REFUSE");
});
