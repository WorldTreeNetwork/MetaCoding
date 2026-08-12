// Evidence for scripts/smoke-all.ts — the suite-level bracket.
//
// Each check exercises a REFUTING outcome and its contrast, because a guard
// shown only in its passing state cannot be told apart from a guard that
// cannot fire.

import { describe, expect, test } from "bun:test";

import { SUITE_SIZE, missing, parseRecord, scriptsOnDisk, unlisted } from "./smoke-all.ts";

describe("the suite list must match the directory", () => {
  test("a script on disk that the suite never runs is NAMED", () => {
    const disk = ["smoke-a.ts", "smoke-b.ts", "smoke-new.ts"];
    expect(unlisted(disk, ["smoke-a.ts", "smoke-b.ts"])).toEqual(["smoke-new.ts"]);
    // Contrast: the complete list reports nothing.
    expect(unlisted(disk, disk)).toEqual([]);
  });

  test("a script the suite lists but that does not exist is NAMED", () => {
    expect(missing(["smoke-a.ts"], ["smoke-a.ts", "smoke-ghost.ts"])).toEqual(["smoke-ghost.ts"]);
    expect(missing(["smoke-a.ts"], ["smoke-a.ts"])).toEqual([]);
  });

  test("the REAL directory and the REAL suite agree right now", () => {
    // This is the one that fires when someone adds scripts/smoke-foo.ts and
    // forgets the runner. It is a live assertion, not a fixture.
    const disk = scriptsOnDisk();
    expect(unlisted(disk)).toEqual([]);
    expect(missing(disk)).toEqual([]);
    expect(disk.length).toBe(SUITE_SIZE);
  });

  test("the runner does not count itself as a smoke script", () => {
    expect(scriptsOnDisk()).not.toContain("smoke-all.ts");
    // Contrast: it does see the ordinary ones.
    expect(scriptsOnDisk()).toContain("smoke-store.ts");
  });
});

describe("exit 0 without a record is not a pass", () => {
  test("stdout carrying no SMOKE_RECORD parses to null", () => {
    expect(parseRecord("some output\nSTORE_SMOKE_PASS\n")).toBeNull();
    expect(parseRecord("")).toBeNull();
  });

  test("a record is parsed, and the LAST one wins", () => {
    const one = parseRecord('SMOKE_RECORD {"published":{"checks":3},"checkLabels":["a"]}\n');
    expect(one!.published.checks).toBe(3);
    // A script that spawns a child smoke script emits two records; the
    // parent's is last, and it is the one that describes this run.
    const two = parseRecord(
      'SMOKE_RECORD {"published":{"checks":1},"checkLabels":[]}\n' +
        'SMOKE_RECORD {"published":{"checks":9},"checkLabels":[]}\n',
    );
    expect(two!.published.checks).toBe(9);
  });

  test("a MALFORMED record is null, not a silently accepted pass", () => {
    // Absence of an answer is never a pass, and neither is an unreadable one.
    expect(parseRecord("SMOKE_RECORD {not json}\n")).toBeNull();
  });
});
