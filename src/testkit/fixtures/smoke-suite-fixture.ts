// Drives scripts/smoke-all.ts's runSuite() over the stub suites in
// smoke-suite/, as a real subprocess with a real exit code.
//
// WHY (MetaCoding-6a0): a judge ran five mutations against smoke-all.ts — delete
// the bracket's `silent.push`, replace its refusal with `true`, set
// scriptsReported to SUITE.length, drop the suite floors whole, lower the
// runner's own floor 5 -> 1 — and ALL FIVE survived the full test suite, because
// nothing drove main(). Every case below fails under at least one of them.
//
// Run: SUITE_FIXTURE_CASE=<case> bun run src/testkit/fixtures/smoke-suite-fixture.ts

import { join } from "node:path";

import { type SuiteOptions, runSuite } from "../../../scripts/smoke-all.ts";

const HERE = join(import.meta.dir, "smoke-suite");

const CASES: Record<string, SuiteOptions> = {
  // All green, both scripts publish: 2 + 3 = 5 checks across the suite.
  green: {
    dir: join(HERE, "green"),
    suite: ["smoke-three.ts", "smoke-two.ts"],
    runName: "fixture-suite",
    checksAcrossSuiteFloor: 5,
  },
  // Identical, except the suite-wide floor is one higher than the suite runs.
  "green-floor-unmet": {
    dir: join(HERE, "green"),
    suite: ["smoke-three.ts", "smoke-two.ts"],
    runName: "fixture-suite",
    checksAcrossSuiteFloor: 6,
  },
  // One script exits 0 having said nothing. THE BRACKET.
  silent: {
    dir: join(HERE, "silent"),
    suite: ["smoke-silent.ts", "smoke-two.ts"],
    runName: "fixture-suite",
    keepGoing: true,
    checksAcrossSuiteFloor: 2,
  },
  // A red script AND a silent one. The red one must not shadow the silent one.
  "red-and-silent": {
    dir: join(HERE, "red-and-silent"),
    suite: ["smoke-red.ts", "smoke-silent.ts", "smoke-two.ts"],
    runName: "fixture-suite",
    keepGoing: true,
    checksAcrossSuiteFloor: 2,
  },
  // A script on disk that the suite never runs.
  drift: {
    dir: join(HERE, "drift"),
    suite: ["smoke-two.ts"],
    runName: "fixture-suite",
    checksAcrossSuiteFloor: 2,
  },
  // --only narrows the run; the per-script record floor still binds what ran.
  only: {
    dir: join(HERE, "green"),
    suite: ["smoke-three.ts", "smoke-two.ts"],
    only: "three",
    runName: "fixture-suite",
  },
  // --only matching nothing is a refusal, not an empty green.
  "only-matches-nothing": {
    dir: join(HERE, "green"),
    suite: ["smoke-three.ts", "smoke-two.ts"],
    only: "no-such-script",
    runName: "fixture-suite",
  },
};

const name = process.env.SUITE_FIXTURE_CASE ?? "green";
const opts = CASES[name];
if (!opts) throw new Error(`unknown SUITE_FIXTURE_CASE: ${name}`);

runSuite(opts)
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("SUITE_FIXTURE_FAIL", err instanceof Error ? err.message : String(err));
    process.exit(1);
  });
