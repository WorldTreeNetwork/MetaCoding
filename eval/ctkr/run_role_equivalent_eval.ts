/**
 * eval/ctkr/run_role_equivalent_eval.ts
 *
 * Eval harness for the ctkr.role_equivalent MCP tool (Phase 2a).
 *
 * Usage:
 *   bun run eval/ctkr/run_role_equivalent_eval.ts
 *
 * The tool itself is not yet implemented.  This harness uses a stub client
 * that returns empty results so the plumbing can be verified end-to-end
 * before the real tool lands.  See RoleEquivalentClient below.
 *
 * When the real tool ships, replace StubRoleEquivalentClient with
 * McpRoleEquivalentClient (also defined below).
 *
 * TODO(23q.3): wire to real ctkr.role_equivalent
 */

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { parse as parseYaml } from "yaml";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ClusterMember {
  repo: string;
  qualified_name: string;
}

interface Cluster {
  id: string;
  description: string;
  members: ClusterMember[];
}

interface GroundTruth {
  clusters: Cluster[];
}

interface RoleEquivalentResult {
  qualified_name: string;
  repo: string;
  score: number; // lower = more similar (distance)
}

// ---------------------------------------------------------------------------
// RoleEquivalentClient interface
//
// When the real tool lands, implement McpRoleEquivalentClient using the MCP
// SDK and swap it in at the bottom of this file.
// ---------------------------------------------------------------------------

interface RoleEquivalentClient {
  /**
   * Returns the top-k cross-repo symbols most structurally similar to the
   * given symbol, ranked by hom-profile distance.
   *
   * @param qualified_name  The symbol to query, in "<package>.<module>.<Class>" form.
   * @param k               Maximum number of results to return.
   * @param cross_repo_only If true, exclude results from the same repo as the query.
   */
  roleEquivalent(params: {
    qualified_name: string;
    k: number;
    cross_repo_only: boolean;
  }): Promise<RoleEquivalentResult[]>;
}

// ---------------------------------------------------------------------------
// StubRoleEquivalentClient — returns empty results (zero-signal baseline)
//
// Replace this with McpRoleEquivalentClient once ctkr.role_equivalent ships.
// ---------------------------------------------------------------------------

class StubRoleEquivalentClient implements RoleEquivalentClient {
  async roleEquivalent(_params: {
    qualified_name: string;
    k: number;
    cross_repo_only: boolean;
  }): Promise<RoleEquivalentResult[]> {
    // TODO(23q.3): wire to real ctkr.role_equivalent
    return [];
  }
}

// ---------------------------------------------------------------------------
// McpRoleEquivalentClient — skeleton for the real integration
//
// Fill in the MCP transport details once ctkr.role_equivalent is registered
// in src/mcp/ctkr-tools.ts.  The tool name and parameter schema should match
// whatever is declared there.
// ---------------------------------------------------------------------------

// class McpRoleEquivalentClient implements RoleEquivalentClient {
//   constructor(
//     private readonly mcpServerUrl: string = "http://localhost:3000",
//   ) {}
//
//   async roleEquivalent(params: {
//     qualified_name: string;
//     k: number;
//     cross_repo_only: boolean;
//   }): Promise<RoleEquivalentResult[]> {
//     // TODO(23q.3): wire to real ctkr.role_equivalent
//     const resp = await fetch(`${this.mcpServerUrl}/mcp`, {
//       method: "POST",
//       headers: { "Content-Type": "application/json" },
//       body: JSON.stringify({
//         tool: "ctkr.role_equivalent",
//         params,
//       }),
//     });
//     const body = await resp.json();
//     return body.results as RoleEquivalentResult[];
//   }
// }

// ---------------------------------------------------------------------------
// Ground-truth loader (tiny inline YAML parser for the simple list format)
// ---------------------------------------------------------------------------

function loadGroundTruth(yamlPath: string): GroundTruth {
  const raw = readFileSync(yamlPath, "utf8");
  return parseYaml(raw) as GroundTruth;
}

// ---------------------------------------------------------------------------
// Metrics
// ---------------------------------------------------------------------------

const K_VALUES = [5, 10, 20] as const;
type KValue = (typeof K_VALUES)[number];

interface ClusterMetrics {
  cluster_id: string;
  query_count: number; // number of members used as queries
  /** precision@k: fraction of top-k hits that are ground-truth cluster members */
  precision: Record<KValue, number>;
  /** recall@k: fraction of ground-truth members found in top-k (averaged over queries) */
  recall: Record<KValue, number>;
  hits: Record<KValue, number>; // total hits across all queries
  misses: Record<KValue, number>; // total misses (expected - hits)
}

interface EvalReport {
  generated_at: string;
  client_kind: string;
  corpus_metrics: {
    mean_precision: Record<KValue, number>;
    mean_recall: Record<KValue, number>;
  };
  per_cluster: ClusterMetrics[];
  worst_clusters: { k: KValue; clusters: string[] }[];
}

function emptyMetrics(cluster_id: string, query_count: number): ClusterMetrics {
  return {
    cluster_id,
    query_count,
    precision: { 5: 0, 10: 0, 20: 0 },
    recall: { 5: 0, 10: 0, 20: 0 },
    hits: { 5: 0, 10: 0, 20: 0 },
    misses: { 5: 0, 10: 0, 20: 0 },
  };
}

/**
 * Evaluate a single cluster.
 *
 * For each member m of the cluster:
 *   - Query ctkr.role_equivalent(m.qualified_name, k=max_k, cross_repo_only=true)
 *   - For each k in K_VALUES:
 *     - relevant = other members of the cluster (excluding m itself)
 *     - hits@k = |top_k_results ∩ relevant_qualified_names|
 *     - precision@k = hits@k / k
 *     - recall@k    = hits@k / |relevant|
 */
async function evalCluster(
  cluster: Cluster,
  client: RoleEquivalentClient,
): Promise<ClusterMetrics> {
  const maxK = Math.max(...K_VALUES);
  const metrics = emptyMetrics(cluster.id, cluster.members.length);

  for (const member of cluster.members) {
    const results = await client.roleEquivalent({
      qualified_name: member.qualified_name,
      k: maxK,
      cross_repo_only: true,
    });

    // The ground-truth relevant set: other members of this cluster
    const relevantNames = new Set(
      cluster.members
        .filter((m) => m.qualified_name !== member.qualified_name)
        .map((m) => m.qualified_name),
    );
    const totalRelevant = relevantNames.size;

    for (const k of K_VALUES) {
      const topK = results.slice(0, k).map((r) => r.qualified_name);
      const hitsAtK = topK.filter((name) => relevantNames.has(name)).length;

      metrics.precision[k] += totalRelevant > 0 ? hitsAtK / k : 0;
      metrics.recall[k] +=
        totalRelevant > 0 ? hitsAtK / totalRelevant : 0;
      metrics.hits[k] += hitsAtK;
      metrics.misses[k] += totalRelevant - hitsAtK;
    }
  }

  // Average over queries
  const n = cluster.members.length;
  if (n > 0) {
    for (const k of K_VALUES) {
      metrics.precision[k] /= n;
      metrics.recall[k] /= n;
    }
  }

  return metrics;
}

// ---------------------------------------------------------------------------
// Report renderer
// ---------------------------------------------------------------------------

function pct(v: number): string {
  return (v * 100).toFixed(1) + "%";
}

function renderReport(report: EvalReport): string {
  const lines: string[] = [];

  lines.push(`# ctkr.role_equivalent Eval Report`);
  lines.push(``);
  lines.push(`Generated: ${report.generated_at}`);
  lines.push(`Client: \`${report.client_kind}\``);
  lines.push(``);

  lines.push(`## Corpus-level metrics`);
  lines.push(``);
  lines.push(`| k | mean precision@k | mean recall@k |`);
  lines.push(`|---|---|---|`);
  for (const k of K_VALUES) {
    lines.push(
      `| ${k} | ${pct(report.corpus_metrics.mean_precision[k])} | ${pct(report.corpus_metrics.mean_recall[k])} |`,
    );
  }
  lines.push(``);

  lines.push(`## Per-cluster metrics`);
  lines.push(``);
  lines.push(
    `| cluster | queries | p@5 | p@10 | p@20 | r@5 | r@10 | r@20 | hits@20 | misses@20 |`,
  );
  lines.push(
    `|---|---|---|---|---|---|---|---|---|---|`,
  );
  for (const cm of report.per_cluster) {
    lines.push(
      [
        `| ${cm.cluster_id}`,
        cm.query_count,
        pct(cm.precision[5]),
        pct(cm.precision[10]),
        pct(cm.precision[20]),
        pct(cm.recall[5]),
        pct(cm.recall[10]),
        pct(cm.recall[20]),
        cm.hits[20],
        cm.misses[20],
      ].join(" | ") + " |",
    );
  }
  lines.push(``);

  lines.push(`## Worst-performing clusters`);
  lines.push(``);
  for (const entry of report.worst_clusters) {
    lines.push(
      `- k=${entry.k}: ${entry.clusters.map((c) => `\`${c}\``).join(", ")}`,
    );
  }
  lines.push(``);

  lines.push(`---`);
  lines.push(`*Note: this report is generated against a human-curated ground-truth set.*`);
  lines.push(`*See \`eval/ctkr/README.md\` for precision/recall definitions and caveats.*`);

  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  const __dir = dirname(fileURLToPath(import.meta.url));
  const truthPath = join(__dir, "role_equivalent_truth.yaml");
  const resultsDir = join(__dir, "results");

  console.log("Loading ground truth from", truthPath);
  const groundTruth = loadGroundTruth(truthPath);
  console.log(`Loaded ${groundTruth.clusters.length} clusters.`);

  // Swap StubRoleEquivalentClient for McpRoleEquivalentClient when the tool ships.
  // TODO(23q.3): wire to real ctkr.role_equivalent
  const client: RoleEquivalentClient = new StubRoleEquivalentClient();
  const clientKind = client.constructor.name;

  console.log(`Using client: ${clientKind}`);
  console.log("");

  // Evaluate each cluster
  const perCluster: ClusterMetrics[] = [];
  for (const cluster of groundTruth.clusters) {
    process.stdout.write(`  Evaluating cluster '${cluster.id}' (${cluster.members.length} members)...`);
    const metrics = await evalCluster(cluster, client);
    perCluster.push(metrics);
    process.stdout.write(
      ` p@5=${pct(metrics.precision[5])} r@5=${pct(metrics.recall[5])}\n`,
    );
  }

  // Corpus aggregates (mean over clusters)
  const nClusters = perCluster.length;
  const meanPrecision = {} as Record<KValue, number>;
  const meanRecall = {} as Record<KValue, number>;
  for (const k of K_VALUES) {
    meanPrecision[k] =
      perCluster.reduce((s, m) => s + m.precision[k], 0) / nClusters;
    meanRecall[k] =
      perCluster.reduce((s, m) => s + m.recall[k], 0) / nClusters;
  }

  // Worst 3 clusters by recall@10
  const sorted = [...perCluster].sort(
    (a, b) => a.recall[10] - b.recall[10],
  );
  const worst3 = sorted.slice(0, 3).map((m) => m.cluster_id);

  const report: EvalReport = {
    generated_at: new Date().toISOString(),
    client_kind: clientKind,
    corpus_metrics: { mean_precision: meanPrecision, mean_recall: meanRecall },
    per_cluster: perCluster,
    worst_clusters: [
      { k: 10, clusters: worst3 },
    ],
  };

  // Write report
  mkdirSync(resultsDir, { recursive: true });
  const timestamp = new Date()
    .toISOString()
    .replace(/[:.]/g, "-")
    .slice(0, 19);
  const reportPath = join(resultsDir, `${timestamp}.md`);
  const md = renderReport(report);
  writeFileSync(reportPath, md, "utf8");

  console.log("");
  console.log("Report written to:", reportPath);
  console.log("");
  console.log("Corpus summary:");
  for (const k of K_VALUES) {
    console.log(
      `  mean precision@${k}: ${pct(meanPrecision[k])}  mean recall@${k}: ${pct(meanRecall[k])}`,
    );
  }

  if (clientKind === "StubRoleEquivalentClient") {
    console.log("");
    console.log(
      "NOTE: Using stub client — all metrics are 0.0 (expected). " +
        "Wire McpRoleEquivalentClient when ctkr.role_equivalent ships.",
    );
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
