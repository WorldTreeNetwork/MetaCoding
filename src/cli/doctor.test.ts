import { test, expect, spyOn } from "bun:test";

// Test that runDoctor completes without throwing and writes output to console.
test("runDoctor: runs without error and prints lanes", async () => {
  const lines: string[] = [];
  const spy = spyOn(console, "log").mockImplementation((...args: unknown[]) => {
    lines.push(args.map(String).join(" "));
  });

  try {
    const { runDoctor } = await import("./doctor");
    await runDoctor({ cmd: "doctor", positional: [], flags: {} });
  } finally {
    spy.mockRestore();
  }

  const output = lines.join("\n");
  expect(output).toContain("Lanes:");
  expect(output).toContain("SCIP TypeScript");
  expect(output).toContain("SCIP Python");
  expect(output).toContain("LSP TypeScript");
  expect(output).toContain("LSP Python");
  expect(output).toContain("Tree-sitter");
  expect(output).toContain("FTS5 (SQLite)");
  expect(output).toContain("Joern (opt-in)");
  expect(output).toContain("CTKR Phase 2+ readiness:");
  expect(output).toContain("Recommendations:");
});
