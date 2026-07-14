/**
 * Tests for the port verifier (ct-subsystem-extraction.md §7, T6).
 *
 * The rename-fork "port" is the acceptance control: a fork is a PERFECT port, so
 * every §7 gate must pass at ceiling (role coverage 1.0, interface preservation
 * 1.0, fidelity ≥ 0.95) and the punch list must be empty. A degree-rewired fork
 * is the negative control: gates drop and the punch list localizes the failures
 * (proving the output is a punch list, not a boolean). Plus unit tests for the
 * §6.2 normalization transforms (kind-collapse, idiom-fold, reweight symmetry).
 *
 * Fixtures are the synthetic depth-2 harness from eval/ctkr/functor_eval.ts —
 * CI-runnable, deterministic, no SCIP index.
 */

import { describe, test, expect } from "bun:test";
import {
  buildBaseGraph,
  renameFork,
  computeDepth2Profiles,
  orbitSignatures,
  toFunctorObjects,
  degreeMatchedRewire,
  type SynthGraph,
} from "../../eval/ctkr/functor_eval.ts";
import { functorSearch, type FunctorObject, type FunctorEdge } from "./functorSearch.ts";
import {
  verifyPort,
  normalizeSide,
  collapsedAlphabet,
  loadNormalization,
  BASE_EDGE_KINDS,
  type SubsystemSpec,
  type SpecRole,
  type SpecProvide,
  type SpecOp,
  type SideGraph,
  type NormalizationSpec,
} from "./verifyPort.ts";

// ---------------------------------------------------------------------------
// Spec construction from a base graph (mirrors what T3/T2/T4 emit)
// ---------------------------------------------------------------------------

const HIGH_SIGNAL = { normalize: "none" as const };

function incidentKinds(edges: FunctorEdge[], id: string): string[] {
  const s = new Set<string>();
  for (const e of edges) {
    if (e.src === id || e.dst === id) s.add(e.kind);
  }
  return [...s].sort();
}

/**
 * Build an extracted-spec + both side graphs for the base subsystem
 * `S = {C0..C3, accessors, I0, I1}` and its rename fork as the port `S'`. The
 * spec's roles / provides / ops are constructed only over symbols the functor
 * actually maps (pre-run F), so a perfect port lands every gate at ceiling —
 * exactly the acceptance condition, not a tautology (the negative control below
 * shares this spec and fails).
 */
function buildForkFixture(modules = 8) {
  const base = buildBaseGraph(modules);
  const baseP = computeDepth2Profiles(base);
  const { fork } = renameFork(base);
  const forkP = computeDepth2Profiles(fork);

  const inSubsystem = (id: string) => /^(C[0-3]($|[.])|I[01]$)/.test(id);
  const srcMembers = new Set(base.objects.map((o) => o.id).filter(inSubsystem));
  const dstMembers = new Set([...srcMembers].map((id) => `fk::${id}`));

  const srcObjects = toFunctorObjects(base, baseP);
  const dstObjects = toFunctorObjects(fork, forkP);

  // pre-run the forward functor to learn dom(F) — the spec is built over it.
  const fwd = functorSearch(
    { srcObjects, srcEdges: base.edges, dstObjects, dstEdges: fork.edges, srcMembers, dstMembers },
    HIGH_SIGNAL,
  );
  const dom = new Set(fwd.mapping.map((m) => m.srcId));

  // roles = orbit classes restricted to mapped members.
  const orbits = orbitSignatures(base, baseP);
  const byOrbit = new Map<string, string[]>();
  for (const o of base.objects) {
    if (!srcMembers.has(o.id) || !dom.has(o.id)) continue;
    const sig = orbits.get(o.id)!;
    (byOrbit.get(sig) ?? byOrbit.set(sig, []).get(sig)!).push(o.id);
  }
  let ri = 0;
  const roles: SpecRole[] = [];
  const roleOf = new Map<string, string>();
  for (const [, members] of byOrbit) {
    const sorted = [...members].sort();
    const roleId = `role${ri++}`;
    for (const m of sorted) roleOf.set(m, roleId);
    roles.push({
      roleId,
      label: roleId,
      members: sorted,
      interfaceParticipation: [],
      exemplarSymbolId: sorted[0]!,
      exemplarQualifiedName: sorted[0]!,
      cardinality: sorted.length,
      invarianceTier: "I",
    });
  }

  // provides = a few mapped members with their real incident kinds.
  const provideIds = ["C0.m0", "C1", "C2.m0"].filter((id) => dom.has(id));
  const provides: SpecProvide[] = provideIds.map((id) => ({
    internalSymbolId: id,
    internalQualifiedName: id,
    roleId: roleOf.get(id),
    usageModes: incidentKinds(base.edges, id).filter((k) => k !== "CONTAINS").slice(0, 2),
  }));

  // ops = a handful of role-path steps drawn from real mapped edges.
  const ops: SpecOp[] = [];
  const seenOp = new Set<string>();
  let oi = 0;
  for (const e of base.edges) {
    if (!dom.has(e.src) || !dom.has(e.dst)) continue;
    const rA = roleOf.get(e.src);
    const rB = roleOf.get(e.dst);
    if (!rA || !rB) continue;
    const key = `${rA}|${e.kind}|${rB}`;
    if (seenOp.has(key)) continue;
    seenOp.add(key);
    if (ops.length >= 6) break;
    ops.push({
      operationId: `op${oi++}`,
      label: `${rA} ->${e.kind} ${rB}`,
      opKind: "path",
      inputRoles: [rA],
      outputRole: rB,
      edgeKinds: [e.kind],
      isBoundaryOp: e.kind === "CALLS", // treat CALLS steps as protocol
      invarianceTier: "I",
      exemplarPaths: [`${e.src} -> ${e.dst}`],
    });
  }

  const spec: SubsystemSpec = {
    subsystemId: "ss:test",
    repo: "base",
    name: "TestSubsystem",
    view: "orbit",
    roles,
    provides,
    ops,
  };

  const qn = new Map(base.objects.map((o) => [o.id, o.id]));
  const qnFork = new Map(fork.objects.map((o) => [o.id, o.id]));
  const source: SideGraph = { objects: srcObjects, edges: base.edges, memberSet: srcMembers, qualifiedNames: qn, language: "py" };
  const port: SideGraph = { objects: dstObjects, edges: fork.edges, memberSet: dstMembers, qualifiedNames: qnFork, language: "py" };
  return { spec, source, port, base, fork, srcMembers, dstMembers, srcObjects, dstObjects, baseP, forkP, roles };
}

// ---------------------------------------------------------------------------
// §7 acceptance — rename fork is a perfect port: all gates at ceiling
// ---------------------------------------------------------------------------

describe("rename-fork port — §7 gates at ceiling", () => {
  const { spec, source, port } = buildForkFixture();

  test("all five gates pass at ceiling, punch list empty", () => {
    const r = verifyPort({ spec, source, port, config: HIGH_SIGNAL });
    expect(r.gates.roleCoverage.score).toBe(1.0);
    expect(r.gates.interfacePreservation.score).toBe(1.0);
    expect(r.gates.compositionPreservation.score).toBe(1.0);
    expect(r.gates.fidelity.score).toBeGreaterThanOrEqual(0.95);
    expect(r.gates.cycleConsistency.score).toBeGreaterThanOrEqual(0.9);
    expect(r.passedAtCeiling).toBe(true);
    expect(r.punchList).toHaveLength(0);
  });

  test("deterministic — identical report across runs", () => {
    const a = verifyPort({ spec, source, port, config: HIGH_SIGNAL });
    const b = verifyPort({ spec, source, port, config: HIGH_SIGNAL });
    expect(JSON.stringify(a.gates)).toBe(JSON.stringify(b.gates));
    expect(JSON.stringify(a.punchList)).toBe(JSON.stringify(b.punchList));
  });

  test("§6.2 normalization ON is a no-op ceiling for a same-language fork", () => {
    const norm = loadNormalization();
    const r = verifyPort({ spec, source, port, normalization: norm, config: HIGH_SIGNAL });
    expect(r.normalizationApplied).toBe(true);
    expect(r.gates.roleCoverage.score).toBe(1.0);
    expect(r.gates.interfacePreservation.score).toBe(1.0);
    expect(r.gates.fidelity.score).toBeGreaterThanOrEqual(0.95);
    expect(r.passedAtCeiling).toBe(true);
    expect(r.punchList).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Negative control — a rewired fork breaks gates and localizes the failures
// ---------------------------------------------------------------------------

describe("rewired fork — punch list localizes failures (not a boolean)", () => {
  test("gates drop and the punch list is non-empty with blockers", () => {
    const { spec, source, base } = buildForkFixture();
    // destroy higher-order structure: degree-matched edge rewire of the fork.
    const { fork } = renameFork(base);
    const rewired = degreeMatchedRewire(fork, 0x5eed);
    const rewiredP = computeDepth2Profiles(rewired);
    const dstMembers = new Set(rewired.objects.map((o) => o.id).filter((id) => spec.provides.length >= 0 && /^fk::(C[0-3]($|[.])|I[01]$)/.test(id)));
    const port: SideGraph = {
      objects: toFunctorObjects(rewired, rewiredP),
      edges: rewired.edges,
      memberSet: dstMembers,
      qualifiedNames: new Map(rewired.objects.map((o) => [o.id, o.id])),
      language: "py",
    };
    const r = verifyPort({ spec, source, port, config: HIGH_SIGNAL });
    expect(r.passedAtCeiling).toBe(false);
    expect(r.punchList.length).toBeGreaterThan(0);
    // fidelity must collapse — the rewire destroyed edge preservation.
    expect(r.gates.fidelity.score).toBeLessThan(0.95);
    // every punch item names a concrete card section (localized, not a boolean).
    for (const p of r.punchList) {
      expect(p.cardSection.length).toBeGreaterThan(0);
      expect(["role-coverage", "interface-preservation", "composition-preservation", "fidelity", "cycle-consistency"]).toContain(p.gate);
    }
  });
});

// ---------------------------------------------------------------------------
// §6.2 normalization transforms — kind-collapse, idiom-fold, reweight
// ---------------------------------------------------------------------------

describe("§6.2 normalizeSide transforms", () => {
  const norm = loadNormalization();
  const alphabet = collapsedAlphabet(BASE_EDGE_KINDS, norm.kind_collapse);

  test("collapsed alphabet folds synonymous kinds", () => {
    // IMPLEMENTS/EXTENDS/OVERRIDES → SUBTYPES ; TYPE_OF/RETURNS_TYPE → TYPED_AS.
    expect(alphabet).toContain("SUBTYPES");
    expect(alphabet).toContain("TYPED_AS");
    expect(alphabet).not.toContain("IMPLEMENTS");
    expect(alphabet).not.toContain("RETURNS_TYPE");
    // CALLS/CONTAINS pass through unchanged.
    expect(alphabet).toContain("CALLS");
    expect(alphabet).toContain("CONTAINS");
  });

  test("kind-collapse rewrites edges", () => {
    const side: SideGraph = {
      objects: [
        { id: "A", kind: "class", profileVec: [] },
        { id: "B", kind: "interface", profileVec: [] },
      ],
      edges: [{ src: "A", dst: "B", kind: "IMPLEMENTS" }],
      language: "ts",
      qualifiedNames: new Map([["A", "A"], ["B", "B"]]),
    };
    const n = normalizeSide(side, norm, alphabet);
    expect(n.edges[0]!.kind).toBe("SUBTYPES");
    expect(n.foldedOut.size).toBe(0);
  });

  test("idiom-fold merges a TS accessor into its CONTAINS parent", () => {
    const side: SideGraph = {
      objects: [
        { id: "foo", kind: "class", profileVec: [] },
        { id: "getbar", kind: "method", profileVec: [] },
        { id: "field", kind: "field", profileVec: [] },
      ],
      edges: [
        { src: "foo", dst: "getbar", kind: "CONTAINS" },
        { src: "getbar", dst: "field", kind: "READS_FIELD" },
      ],
      language: "ts",
      qualifiedNames: new Map([
        ["foo", "src/Foo.ts::Foo"],
        ["getbar", "src/Foo.ts::Foo.getBar"], // matches \.(get|set)[A-Z]
        ["field", "src/Foo.ts::Foo.bar"],
      ]),
    };
    const n = normalizeSide(side, norm, alphabet);
    expect(n.foldedOut.has("getbar")).toBe(true);
    expect(n.containerOf.get("getbar")).toBe("foo");
    // getbar's READS_FIELD edge rerouted to foo.
    expect(n.edges.some((e) => e.src === "foo" && e.dst === "field" && e.kind === "READS_FIELD")).toBe(true);
    // getbar is gone from the object set.
    expect(n.objects.some((o) => o.id === "getbar")).toBe(false);
  });

  test("reweight up-weights a rare kind over a dense one", () => {
    // 9 CALLS + 1 INJECTS: INJECTS is rarer → larger inverse-marginal weight,
    // so an object's INJECTS dim ends up weighted more per-count than CALLS.
    const objects: FunctorObject[] = [
      { id: "h", kind: "method", profileVec: [] },
      { id: "x", kind: "method", profileVec: [] },
    ];
    const edges: FunctorEdge[] = [];
    for (let i = 0; i < 9; i++) edges.push({ src: "h", dst: "x", kind: "CALLS" });
    edges.push({ src: "h", dst: "x", kind: "INJECTS" });
    const side: SideGraph = { objects, edges, language: "py", qualifiedNames: new Map() };
    const n = normalizeSide(side, norm, alphabet);
    const idxOut = (k: string) => alphabet.indexOf(k) * 2 + 1;
    const hvec = n.objects.find((o) => o.id === "h")!.profileVec;
    const callsW = hvec[idxOut("CALLS")]! / 9; // per-count weight
    const injW = hvec[idxOut("INJECTS")]! / 1;
    expect(injW).toBeGreaterThan(callsW);
  });

  test("normalization off leaves the provided profile vectors untouched", () => {
    const { spec, source, port } = buildForkFixture();
    const r = verifyPort({ spec, source, port, normalization: null, config: HIGH_SIGNAL });
    expect(r.normalizationApplied).toBe(false);
    expect(r.passedAtCeiling).toBe(true);
  });
});
