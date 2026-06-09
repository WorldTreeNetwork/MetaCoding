"""L3 role-class labeler — turn clustered hom-profiles into labeled role classes.

Pipeline
--------

1. Read ``hom_profiles.parquet`` (produced by ``ctkr hom-profiles``).
2. Cluster rows by the **bucket-key approach** from
   ``docs/notes/entropy-as-dial.md``: L1-normalise the raw count vector,
   discretize each component to 1/granularity_k steps, serialise to a
   stable string. Symbols with identical bucket keys belong to the same
   role class at that granularity. This sidesteps O(n²) pairwise
   clustering at corpus scale and aligns exactly with the granularity-
   dial framing.
3. Drop the all-zeros cluster (isolates) and any clusters below
   ``min_cluster_size``.
4. For each surviving cluster, pick representative anchors via the same
   round-robin-by-repo rule used in :mod:`ctkr.label_motifs`.
5. Build an :class:`EvidencePack` and send it to the LLM with a
   structured-output schema.
6. Emit one :class:`PatternRow` (source_kind='role-cluster') per
   cluster and one :class:`EvidenceRow` per instance.

Owning bd issue: ``MetaCoding-23q.4``.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import blake3
import networkx as nx
import polars as pl
from pydantic import BaseModel, Field

from ctkr.evidence import EvidencePack, build_evidence_pack
from ctkr.llm import LLMClient
from ctkr.schema_l3 import EvidenceRow, LineRange, PatternRow

logger = logging.getLogger("ctkr.label_roles")

DEFAULT_PROMPT_VERSION = "role-labeler:v1"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_TEMPERATURE = 0.0
DEFAULT_TOKEN_BUDGET = 8_000
DEFAULT_MAX_INSTANCES = 8
DEFAULT_GRANULARITY = 4
DEFAULT_MIN_CLUSTER_SIZE = 2

PATTERN_ID_PREFIX = "role"
SOURCE_KIND = "role-cluster"


# ----- LLM response schema -----


class RoleClusterLabelOutput(BaseModel):
    """What the LLM emits for one role cluster.

    Same shape as :class:`ctkr.label_motifs.MotifLabelOutput` — provenance
    fields are filled in by the caller; the LLM only owns the natural-
    language judgement.
    """

    label: str = Field(
        description=(
            "Short canonical name for this role — 2-4 words. Describes the "
            "structural function the symbols in this cluster play, "
            "independent of name or repo (e.g. 'Tool registry', "
            "'Agent factory', 'Decorated handler')."
        ),
    )
    description: str = Field(
        description=(
            "One paragraph (2-4 sentences) explaining what unifies these "
            "symbols structurally — what edges they share, what they call "
            "or are called by, what they contain or are contained by. "
            "Avoid surface naming similarity; ground the description in "
            "the typed-edge neighborhood that defined the cluster."
        ),
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Self-reported confidence in [0, 1] that this label and "
            "description accurately characterize the shared role."
        ),
    )


# ----- bucket-key clustering -----


def _l1_normalize(vec: Sequence[int]) -> list[float]:
    s = sum(vec)
    if s == 0:
        return [0.0] * len(vec)
    return [v / s for v in vec]


def _discretize(normalised: Sequence[float], k: int) -> list[float]:
    return [round(v * k) / k for v in normalised]


def profile_bucket_key(profile_vec: Sequence[int], granularity_k: int) -> str:
    """Stable string key for a role-class bucket at granularity ``k``.

    Two profiles share a key iff their L1-normalised vectors round to
    the same 1/k-step discretization. Matches the TS-side
    ``profileBucketKey`` in ``src/ctkr/homProfile.ts`` so callers on
    either lane group identically.
    """
    if granularity_k <= 0:
        raise ValueError(
            f"granularity_k must be a positive integer, got {granularity_k}"
        )
    return "|".join(
        f"{v:.6f}" for v in _discretize(_l1_normalize(profile_vec), granularity_k)
    )


@dataclass(slots=True, frozen=True)
class RoleCluster:
    """One role-equivalence class discovered by bucket-key grouping."""

    cluster_id: str
    bucket_key: str
    members: tuple[str, ...]  # symbol_ids, sorted

    @property
    def size(self) -> int:
        return len(self.members)


def cluster_id_for_members(members: Sequence[str]) -> str:
    """Deterministic cluster_id from the sorted symbol_id tuple.

    Re-runs at the same granularity on the same corpus yield identical
    cluster IDs. Re-runs at a *different* granularity will produce
    different cluster IDs even when the membership happens to overlap —
    the granularity is part of the bucket-key, which is part of the
    member set, which is part of the hash.
    """
    canon = json.dumps(sorted(members), separators=(",", ":")).encode("utf-8")
    return blake3.blake3(canon).hexdigest(length=8)


def compute_role_clusters(
    profiles_df: pl.DataFrame,
    *,
    granularity_k: int = DEFAULT_GRANULARITY,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
    drop_isolates: bool = True,
) -> list[RoleCluster]:
    """Group hom-profiles into role classes by bucket-key equivalence.

    Parameters
    ----------
    profiles_df
        Loaded ``hom_profiles.parquet`` — must have ``symbol_id`` and
        ``profile_vec`` columns.
    granularity_k
        Buckets per dimension in the discretization. Lower → coarser
        (fewer, larger clusters). See ``docs/notes/entropy-as-dial.md``.
    min_cluster_size
        Clusters with fewer than this many members are dropped. Default
        2 — a singleton cluster carries no role information.
    drop_isolates
        When True (default), drop the all-zeros bucket (symbols with no
        edges contribute no structural signal).

    Returns
    -------
    list[RoleCluster]
        Sorted by descending size, ties broken by cluster_id for
        determinism.
    """
    buckets: dict[str, list[str]] = {}
    # Detect the isolate (all-zero) bucket by length-aware key so this works on
    # both production hom_profiles (28-dim) and small test fixtures.
    isolate_keys: set[str] = set()
    for row in profiles_df.iter_rows(named=True):
        vec = list(row["profile_vec"])
        key = profile_bucket_key(vec, granularity_k)
        if sum(vec) == 0:
            isolate_keys.add(key)
        buckets.setdefault(key, []).append(str(row["symbol_id"]))

    clusters: list[RoleCluster] = []
    for key, members in buckets.items():
        if drop_isolates and key in isolate_keys:
            continue
        if len(members) < min_cluster_size:
            continue
        sorted_members = tuple(sorted(members))
        clusters.append(
            RoleCluster(
                cluster_id=cluster_id_for_members(sorted_members),
                bucket_key=key,
                members=sorted_members,
            )
        )

    clusters.sort(key=lambda c: (-c.size, c.cluster_id))
    return clusters


# ----- pattern_id -----


def pattern_id_for_role_cluster(
    cluster_id: str,
    *,
    prompt_version: str,
    llm_model: str,
) -> str:
    """Deterministic pattern_id for a labeled role cluster."""
    canon = json.dumps(
        ["role-cluster", cluster_id, prompt_version, llm_model], sort_keys=True
    ).encode("utf-8")
    h = blake3.blake3(canon).hexdigest(length=8)
    return f"{PATTERN_ID_PREFIX}:{cluster_id}@{h}"


# ----- prompt -----


_SYSTEM = (
    "You are a software-architecture labeler. You see a cluster of symbols "
    "from a cross-repo corpus of agent-orchestrator codebases that share "
    "the same hom-profile shape — they have identical structural "
    "neighborhoods up to a discretization granularity, even though their "
    "names and repos differ. Your job is to give the cluster a short "
    "canonical name for the *role* it plays and a one-paragraph "
    "description of what unifies these symbols structurally. Stay "
    "grounded in the typed-edge neighborhoods shown — do not infer roles "
    "from surface naming similarity."
)


def render_prompt(
    cluster: RoleCluster, pack: EvidencePack, *, granularity_k: int
) -> str:
    """Compose the user-side prompt from a cluster + its EvidencePack."""
    parts: list[str] = []
    parts.append(f"# Role cluster `{cluster.cluster_id}`")
    parts.append("")
    parts.append("## Cluster signature")
    parts.append(f"- members: {cluster.size}")
    parts.append(f"- granularity: 1/{granularity_k} buckets per profile dimension")
    parts.append(f"- bucket_key: `{cluster.bucket_key}`")
    parts.append(
        f"- repos covered ({len(pack.repos_covered)}): {', '.join(pack.repos_covered[:20])}"
    )
    parts.append("")
    parts.append(
        f"## Evidence ({len(pack.instances)} representative instances)"
    )
    if pack.truncated:
        parts.append(
            f"_Note: cluster has {cluster.size} members; sampled to fit a "
            f"{pack.token_budget}-token budget._"
        )
    parts.append("")

    for i, inst in enumerate(pack.instances, 1):
        parts.append(f"### Instance {i}: `{inst.qualified_name}` ({inst.repo})")
        parts.append(
            f"- file: `{inst.file}` lines {inst.line_range.start}-{inst.line_range.end}"
        )
        parts.append(f"- kind: {inst.kind}")
        if inst.docstring:
            parts.append(f"- docstring: {inst.docstring}")
        parts.append("")
        parts.append("```")
        parts.append(inst.snippet)
        parts.append("```")
        if inst.neighbors:
            parts.append("")
            parts.append("**1-hop neighbors:**")
            for nb in inst.neighbors:
                arrow = "→" if nb.direction == "outgoing" else "←"
                sig = f" `{nb.signature}`" if nb.signature else ""
                parts.append(
                    f"- {arrow} [{nb.edge_kind}] `{nb.qualified_name}` ({nb.repo}){sig}"
                )
        parts.append("")

    parts.append("---")
    parts.append("")
    parts.append(
        "Emit a `RoleClusterLabelOutput` naming the role these symbols share. "
        "Anchor the label in the typed-edge neighborhood — what they contain, "
        "what calls them, what they call, what they return. Avoid words like "
        "'class' or 'function' that describe the kind rather than the role."
    )
    return "\n".join(parts)


# ----- one cluster -----


@dataclass(slots=True)
class LabeledRoleCluster:
    pattern: PatternRow
    evidence: list[EvidenceRow]
    cost_usd: float
    cache_hit: bool


def label_role_cluster(
    *,
    cluster: RoleCluster,
    pack: EvidencePack,
    client: LLMClient,
    granularity_k: int,
    model: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
    max_tokens: int = 1024,
) -> LabeledRoleCluster:
    prompt = render_prompt(cluster, pack, granularity_k=granularity_k)
    result = client.complete_structured(
        prompt,
        schema=RoleClusterLabelOutput,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        system=_SYSTEM,
    )
    parsed = result.parsed
    pid = pattern_id_for_role_cluster(
        cluster.cluster_id, prompt_version=prompt_version, llm_model=model
    )
    now = datetime.now(tz=UTC)
    pattern = PatternRow(
        pattern_id=pid,
        source_kind=SOURCE_KIND,
        source_ref=cluster.cluster_id,
        label=parsed.label,
        description=parsed.description,
        instances=[i.symbol_id for i in pack.instances],
        confidence=parsed.confidence,
        llm_model=model,
        llm_temperature=temperature,
        prompt_version=prompt_version,
        generated_at=now,
    )
    evidence_rows = [
        EvidenceRow(
            pattern_id=pid,
            repo=inst.repo,
            file=inst.file,
            line_range=LineRange(start=inst.line_range.start, end=inst.line_range.end),
            snippet=inst.snippet,
            context=inst.qualified_name,
        )
        for inst in pack.instances
    ]
    return LabeledRoleCluster(
        pattern=pattern,
        evidence=evidence_rows,
        cost_usd=result.cost_estimate_usd,
        cache_hit=result.cache_hit,
    )


# ----- driver -----


@dataclass(slots=True)
class RoleLabelRunStats:
    n_clusters: int
    n_labeled: int
    n_skipped: int
    n_failed: int
    total_cost_usd: float
    cache_hits: int


def _load_existing_pattern_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    out: set[str] = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("skipping malformed line in %s", path)
                continue
            pid = d.get("pattern_id")
            if pid is not None:
                out.add(pid)
    return out


def _pick_anchors_by_repo(
    g: nx.MultiDiGraph,
    members: Sequence[str],
    *,
    max_instances: int,
) -> list[str]:
    """Round-robin by repo. Same shape as label_motifs._iter_motif_instance_anchors
    so the labeler sees cross-repo evidence rather than one repo's worth."""
    by_repo: dict[str, list[str]] = {}
    for sym_id in members:
        if not g.has_node(sym_id):
            continue
        repo = g.nodes[sym_id].get("repo") or ""
        by_repo.setdefault(repo, []).append(sym_id)

    repo_iters = [iter(by_repo[r]) for r in sorted(by_repo)]
    out: list[str] = []
    while repo_iters and len(out) < max_instances:
        next_round = []
        for it in repo_iters:
            sym = next(it, None)
            if sym is None:
                continue
            out.append(sym)
            if len(out) >= max_instances:
                return out
            next_round.append(it)
        repo_iters = next_round
    return out


def label_roles(
    *,
    clusters: Sequence[RoleCluster],
    graph: nx.MultiDiGraph,
    orchestrators_root: str | Path,
    client: LLMClient,
    out_patterns: Path,
    out_evidence: Path,
    granularity_k: int = DEFAULT_GRANULARITY,
    model: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
    max_instances_per_cluster: int = DEFAULT_MAX_INSTANCES,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    force: bool = False,
    max_clusters: int | None = None,
    progress: Iterable[str] | None = None,
) -> RoleLabelRunStats:
    """Label every cluster in ``clusters``; stream rows to JSONL.

    Mirrors :func:`ctkr.label_motifs.label_motifs` for resumability —
    idempotent under the same prompt-version + model, skips already-
    labeled clusters by ``pattern_id`` unless ``force=True``.
    """
    out_patterns.parent.mkdir(parents=True, exist_ok=True)
    out_evidence.parent.mkdir(parents=True, exist_ok=True)

    existing = _load_existing_pattern_ids(out_patterns) if not force else set()

    iter_clusters: list[RoleCluster] = list(clusters)
    if max_clusters is not None:
        iter_clusters = iter_clusters[:max_clusters]
    n_total = len(iter_clusters)

    n_labeled = 0
    n_skipped = 0
    n_failed = 0
    total_cost = 0.0
    cache_hits = 0

    with out_patterns.open("a", encoding="utf-8") as pf, out_evidence.open(
        "a", encoding="utf-8"
    ) as ef:
        for i, cluster in enumerate(iter_clusters):
            pid = pattern_id_for_role_cluster(
                cluster.cluster_id, prompt_version=prompt_version, llm_model=model
            )
            if pid in existing:
                n_skipped += 1
                logger.debug("skipping %s (already labeled)", cluster.cluster_id)
                continue

            anchors = _pick_anchors_by_repo(
                graph, cluster.members, max_instances=max_instances_per_cluster
            )
            if not anchors:
                n_skipped += 1
                logger.warning(
                    "cluster %s — no resolvable graph nodes among %d members",
                    cluster.cluster_id,
                    cluster.size,
                )
                continue

            pack = build_evidence_pack(
                graph,
                anchors,
                source_kind=SOURCE_KIND,
                source_ref=cluster.cluster_id,
                orchestrators_root=orchestrators_root,
                token_budget=token_budget,
            )
            if not pack.instances:
                n_skipped += 1
                logger.warning(
                    "cluster %s — no instances had readable evidence; skipped",
                    cluster.cluster_id,
                )
                continue

            try:
                out = label_role_cluster(
                    cluster=cluster,
                    pack=pack,
                    client=client,
                    granularity_k=granularity_k,
                    model=model,
                    temperature=temperature,
                    prompt_version=prompt_version,
                )
            except Exception as e:  # noqa: BLE001
                n_failed += 1
                logger.exception("cluster %s failed: %s", cluster.cluster_id, e)
                continue

            pf.write(out.pattern.model_dump_json() + "\n")
            pf.flush()
            for ev in out.evidence:
                ef.write(ev.model_dump_json() + "\n")
            ef.flush()
            n_labeled += 1
            total_cost += out.cost_usd
            cache_hits += 1 if out.cache_hit else 0
            existing.add(pid)
            logger.info(
                "labeled %s as %r (size=%d cost=$%.6f cache=%s)",
                cluster.cluster_id,
                out.pattern.label,
                cluster.size,
                out.cost_usd,
                out.cache_hit,
            )
            if progress is not None:
                logger.info("progress: %d/%d", i + 1, n_total)

    return RoleLabelRunStats(
        n_clusters=n_total,
        n_labeled=n_labeled,
        n_skipped=n_skipped,
        n_failed=n_failed,
        total_cost_usd=round(total_cost, 6),
        cache_hits=cache_hits,
    )


__all__ = [
    "DEFAULT_GRANULARITY",
    "DEFAULT_MAX_INSTANCES",
    "DEFAULT_MIN_CLUSTER_SIZE",
    "DEFAULT_MODEL",
    "DEFAULT_PROMPT_VERSION",
    "DEFAULT_TEMPERATURE",
    "DEFAULT_TOKEN_BUDGET",
    "SOURCE_KIND",
    "LabeledRoleCluster",
    "RoleCluster",
    "RoleClusterLabelOutput",
    "RoleLabelRunStats",
    "cluster_id_for_members",
    "compute_role_clusters",
    "label_role_cluster",
    "label_roles",
    "pattern_id_for_role_cluster",
    "profile_bucket_key",
    "render_prompt",
]
