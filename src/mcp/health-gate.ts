// READ-TIME ENFORCEMENT of the index-fitness property.
//
//   A graph whose fitness for (repo, branch, commit) has not been established
//   cannot produce an answer that is INDISTINGUISHABLE from one produced by a
//   graph whose fitness has been.
//
// This is the file the MetaCoding-hy6.16 loss needed. A full 41-row re-scoring
// pass ran over a graph holding CALLS = 0 and REFERENCES = 0; every query
// returned `[]`; the pass produced numbers; the numbers were wrong in a way
// nothing downstream could see. **An empty result from an unfit graph was
// byte-identical to an empty result from a fit one.**
//
// So the enforcement is by TYPE, not by a banner someone has to read:
//
//   fit graph,     zero rows  ->  { ok: true,  rows: [] }
//   unfit graph,   zero rows  ->  { ok: false, error: "INDEX_FITNESS_UNESTABLISHED" }
//
// The second value HAS NO `rows` PROPERTY. A caller that does `result.rows.map(...)`
// crashes instead of silently absorbing a zero. That is the whole point: the
// hy6.16 rescore would have thrown on row 1 rather than written 41 wrong rows.
//
// Two postures, because two kinds of consumer are exposed differently:
//
//   * GRAPH QUERY tools (neighbors/callers/implementers/search/cypher) refuse
//     only when the answer is EMPTY. A non-empty answer is real data, and
//     refusing it would make the gate a thing people turn off; it carries the
//     health caveat instead.
//   * AGGREGATING consumers (graph_diff, CTKR motif mining, role-equivalence,
//     cross-repo comparison, the eval harness, any rescoring pass) refuse BY
//     DEFAULT, empty or not, and require an explicit acknowledgment. An
//     aggregate silently absorbs a zero — and hy6.16 WAS an aggregate. This is
//     the direct fix for the historical harm.
//
// UNKNOWN (no health record beside the graph) is unestablished. Every store
// indexed before this shipped reads UNKNOWN, including production farmOS, and
// that is the honest reading — not a bug to be defaulted away.

import type { Store } from "../store";
import {
  isAbandonedRun,
  isFitnessEstablished,
  readIndexHealth,
  type IndexHealthStatus,
} from "../store/health.ts";

export interface SliceHealth {
  repo: string;
  branch: string;
  status: IndexHealthStatus;
  /** True when a RUNNING record's owning process is gone. */
  abandoned?: boolean;
}

export interface HealthSummary {
  /** Every (repo, branch) slice the store holds symbols for. */
  slices: SliceHealth[];
  /** Slices whose fitness is REFUSED / RUNNING / UNKNOWN. */
  unestablished: SliceHealth[];
  /** True when every slice the store holds is HEALTHY or OVERRIDDEN. */
  established: boolean;
}

export const FITNESS_ERROR = "INDEX_FITNESS_UNESTABLISHED" as const;

/** A gated answer. The refusal branch deliberately has NO `rows`. */
export type GraphAnswer<T> =
  | { ok: true; rows: T[]; health: HealthSummary; caveat?: string }
  | {
      ok: false;
      error: typeof FITNESS_ERROR;
      message: string;
      health: HealthSummary;
    };

/**
 * Which (repo, branch) slices this store holds, and what the persisted health
 * record says about each. A slice with symbols but no record is UNKNOWN.
 *
 * BOUNDARY NODES ARE NOT SLICES (bead MetaCoding-scc)
 * --------------------------------------------------
 * Both lanes create name-keyed EXTERNAL BOUNDARY nodes for targets defined
 * outside the repo (`external::dataclass`, `external::ContentEntityBase`, …):
 * `language = 'external'`, no file, no position, and `branch = ''` because they
 * belong to no branch. A session writes its health record for (repo, <the git
 * branch>) and never for (repo, ''), so enumerating slices by
 * `DISTINCT s.repo, s.branch` invented a permanently UNKNOWN slice and
 * `established` was permanently FALSE — a perfectly healthy store refused every
 * empty query and every aggregate. Measured on both production stores before
 * the fix: MetaCoding@main 18117 symbols + MetaCoding@'' 6, farmos@3fe0ce7
 * 4446 + farmos@'' 354.
 *
 * `fitness.ts` already reasoned about boundary nodes for `measureStoreFitness`
 * ("external boundary nodes only ever appear as targets"); the reasoning was
 * never carried across to ENUMERATION, which asks a different question — not
 * "whose symbols count" but "what is a slice that needs a verdict of its own".
 * A boundary node is not a slice of indexed code and cannot have a fitness
 * verdict.
 *
 * WHY THIS PREDICATE. `s.file = ''` alone is the convenient one; it would also
 * silence any future real symbol that happens to carry no file, which is
 * exactly the kind of quiet slice-disappearance this gate exists to prevent.
 * `s.source = 'tree_sitter'` is wrong outright — the SCIP loader creates the
 * same boundary nodes with `source = 'scip'` (src/scip/loader.ts), and the
 * tree-sitter lane's REAL symbols carry that source too. The explicit marker
 * both lanes set is `language = 'external'`, so the predicate is the
 * CONJUNCTION of the marker and the absence of a file: a symbol that names a
 * real file is enumerated as a slice no matter what else it says about itself.
 */
export async function summarizeHealth(store: Store): Promise<HealthSummary> {
  const rows = await store.query<{ repo: string | null; branch: string | null }>(
    `MATCH (s:Symbol)
     WHERE s.language <> 'external' OR s.file <> ''
     RETURN DISTINCT s.repo AS repo, s.branch AS branch`,
  );
  const slices: SliceHealth[] = [];
  for (const r of rows) {
    const repo = r.repo ?? "";
    const branch = r.branch ?? "";
    const rec = readIndexHealth(store.dataDir, repo, branch);
    const status: IndexHealthStatus = rec?.status ?? "UNKNOWN";
    const slice: SliceHealth = { repo, branch, status };
    if (status === "RUNNING" && isAbandonedRun(rec)) slice.abandoned = true;
    slices.push(slice);
  }
  // A store with no symbols at all still has unestablished fitness — there is
  // nothing in it, and "nothing" is exactly the answer hy6.16 mistook for real.
  if (slices.length === 0) {
    slices.push({ repo: "(empty store)", branch: "", status: "UNKNOWN" });
  }
  const unestablished = slices.filter((s) => !isFitnessEstablished(s.status));
  return { slices, unestablished, established: unestablished.length === 0 };
}

function describe(h: HealthSummary): string {
  return h.unestablished
    .map((s) => `${s.repo}@${s.branch}=${s.status}${s.abandoned ? "(abandoned)" : ""}`)
    .join(", ");
}

/**
 * Gate a GRAPH QUERY result. Empty + unestablished is a refusal with a
 * different type; non-empty carries a caveat; empty + established is `[]`.
 */
export function gateQueryAnswer<T>(rows: T[], health: HealthSummary): GraphAnswer<T> {
  if (rows.length === 0 && !health.established) {
    return {
      ok: false,
      error: FITNESS_ERROR,
      message:
        `This query returned ZERO rows against a graph whose fitness is not ` +
        `established (${describe(health)}). An empty result from an unfit graph is ` +
        `indistinguishable from an empty result from a fit one — which is exactly ` +
        `how a 41-row re-scoring pass was computed over a graph with CALLS = 0 ` +
        `(bead MetaCoding-hy6.16). Refusing instead of answering [].\n` +
        `Fix: re-run 'metacoding index <path> --scip' and let it finalize, then retry.`,
      health,
    };
  }
  const answer: GraphAnswer<T> = { ok: true, rows, health };
  if (!health.established) {
    answer.caveat =
      `Fitness is not established for: ${describe(health)}. These rows are real, ` +
      `but the graph may be missing whatever an unfinished or refused run did not write.`;
  }
  return answer;
}

/**
 * Gate an AGGREGATING consumer. Refuses by default whether or not the result is
 * empty, because an aggregate absorbs a zero without anyone seeing it.
 * `acknowledged` is the caller's explicit "yes, I know, proceed".
 */
export function gateAggregate<T>(
  compute: () => T,
  health: HealthSummary,
  acknowledged: boolean,
  toolName: string,
):
  | { ok: true; result: T; health: HealthSummary; caveat?: string }
  | { ok: false; error: typeof FITNESS_ERROR; message: string; health: HealthSummary } {
  if (!health.established && !acknowledged) {
    return {
      ok: false,
      error: FITNESS_ERROR,
      message:
        `${toolName} is an AGGREGATING consumer and the graph's fitness is not ` +
        `established (${describe(health)}). An aggregate absorbs a zero silently: ` +
        `the MetaCoding-hy6.16 loss was a 41-row aggregate over a graph with no ` +
        `CALLS or REFERENCES edges, and nothing downstream could see it. ` +
        `Refusing by default.\n` +
        `Fix: re-index and let the run finalize. To proceed anyway and record that ` +
        `you know, pass acknowledge_unestablished_fitness: true.`,
      health,
    };
  }
  const out: {
    ok: true; result: T; health: HealthSummary; caveat?: string;
  } = { ok: true, result: compute(), health };
  if (!health.established) {
    out.caveat =
      `PROCEEDING OVER UNESTABLISHED FITNESS at the caller's explicit request: ` +
      `${describe(health)}. Any zero in this result may be an artifact of an ` +
      `unfinished or refused index run rather than a fact about the code.`;
  }
  return out;
}
