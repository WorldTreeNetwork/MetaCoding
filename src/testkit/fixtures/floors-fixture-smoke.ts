// A fixture that IS a smoke script, in six modes, so F4.1-F4.3 can be measured
// on a real process with a real exit code rather than on a mocked one.
//
// The `legacy-*` modes are the shape all 22 scripts/smoke-*.ts had before
// floors.ts: a sequence of `if (bad) throw`, then an unconditional PASS line.
// legacy-complete and legacy-truncated are BYTE-IDENTICAL on stdout and both
// exit 0 — that is the measurement this whole mechanism exists to change, and
// it is asserted in floors.test.ts rather than claimed here.
//
// Run: bun run src/testkit/fixtures/floors-fixture-smoke.ts   (MODE env var)

import { beginRun, type Floor } from "../floors.ts";

const MODE = process.env.FLOORS_FIXTURE_MODE ?? "floors-complete";

/** The seven things this fixture "verifies". Three are dropped when truncated. */
const CHECKS: Array<[string, boolean]> = [
  ["one is one", 1 === 1],
  ["two is two", 2 === 2],
  ["three is three", 3 === 3],
  ["four is four", 4 === 4],
  ["five is five", 5 === 5],
  ["six is six", 6 === 6],
  ["seven is seven", 7 === 7],
];

/** Truncation = the edit a careless refactor makes. Same file, three fewer checks. */
function selected(): Array<[string, boolean]> {
  if (MODE.endsWith("-truncated")) return CHECKS.slice(0, 4);
  if (MODE.endsWith("-empty")) return [];
  return CHECKS;
}

// The floor is derived: the fixture declares seven checks, so seven is what a
// complete run publishes. See floors.ts's header for how much `why` is worth.
const FLOORS: Floor[] = [
  { min: 7, measuredAs: "checks", why: "this script declares seven checks; a shorter run is a truncated one" },
];

const UNPUBLISHED_FLOORS: Floor[] = [
  { min: 7, measuredAs: "checks", why: "as above" },
  {
    min: 3,
    measuredAs: "sectionsCovered",
    why: "the number a builder was told to calibrate from, which no instrument here emits",
  },
];

function legacy(): void {
  for (const [label, ok] of selected()) {
    if (!ok) throw new Error(`FAILED: ${label}`);
  }
  // Unconditional. This is the defect: it says nothing about how many ran.
  console.log("FIXTURE_SMOKE_PASS");
}

function withFloors(floors: Floor[]): void {
  const run = beginRun("fixture");
  for (const [label, ok] of selected()) run.check(label, ok);
  run.finish(floors);
}

function main(): void {
  switch (MODE) {
    case "legacy-complete":
    case "legacy-truncated":
      return legacy();
    case "floors-complete":
    case "floors-truncated":
    case "floors-empty":
      return withFloors(FLOORS);
    case "floors-unpublished":
      return withFloors(UNPUBLISHED_FLOORS);
    default:
      throw new Error(`unknown FLOORS_FIXTURE_MODE: ${MODE}`);
  }
}

try {
  main();
  process.exit(0);
} catch (err) {
  console.error("FIXTURE_SMOKE_FAIL", err instanceof Error ? err.message : String(err));
  process.exit(1);
}
