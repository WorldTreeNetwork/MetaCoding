"""Subsystem partition — Stage A / DECOMPOSE (subsystem-extraction §2, T1).

Partition one indexed repo's object set into subsystems ("modules-as-emergent"
at a *team-would-own-this* granularity) with **robust** boundaries: robust
meaning stable under a Louvain resolution sweep, not an artifact of one run.

The pipeline, per §2.1:

1. Build a per-repo undirected weighted graph. Typed edges carry weight (with
   ``REFERENCES`` — the cross-cutting-noise kind — down-weighted by default and
   ``CONTAINS`` kept as the containment backbone). A **declared-structure
   prior** (§2.1.4) is added as low-weight edges from every symbol to a synthetic
   per-directory hub node, so directory cohesion is a *prior* the behavioural
   edges can override, not ground truth. The prior is what keeps subsystem names
   attachable and covers the zero-profile floor (§2.3): a structurally-isolated
   symbol has no typed edges, so its only tie is to its directory hub — it is
   placed by locality, exactly the honest division of labour the floor forces.

2. Run Louvain across a resolution sweep (entropy-as-a-dial applied to
   partitioning). The partition is emitted at a single default resolution; the
   sweep supplies **persistence** metadata — per-member ``boundary_confidence``
   (mean co-association with its subsystem across the sweep) and per-subsystem
   ``persistence_score``. Boundary symbols (low co-association) are the
   judgment-call assignments a re-implementer must know about.

3. Zero-profile / isolated symbols are flagged ``placement="locality"`` (placed
   by their directory hub); everyone else is ``placement="structural"``.

Determinism (§ acceptance): Louvain is seeded; community ordering and all
tie-breaks are by ``(-size, min member id)`` and members are sorted, so the same
input graph yields byte-identical parquet across runs regardless of
``PYTHONHASHSEED``.

Pure-NetworkX + NumPy; no heavy community-detection dependency (Louvain ships in
networkx). Louvain/graph community detection lives in the Python lane per
decision MetaCoding-p4b.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import networkx as nx
import numpy as np
import polars as pl
from blake3 import blake3

from ctkr.schema import (
    SCHEMA_VERSION,
    SUBSYSTEM_MEMBERS_COLUMNS,
    SUBSYSTEMS_COLUMNS,
)

logger = logging.getLogger("ctkr.subsystems")

# ── defaults (dials, not truths — tuned on the MetaCoding self-index so the
#    default partition clears the directory-truth ARI sanity floor while still
#    letting behaviour disagree with directories; see the T1 acceptance run) ──
DEFAULT_RESOLUTION: float = 0.5
DEFAULT_SWEEP: tuple[float, ...] = (0.3, 0.5, 0.7, 1.0, 1.3, 1.6, 2.0)
DEFAULT_SEED: int = 42
DEFAULT_CONTAINS_WEIGHT: float = 1.0
DEFAULT_REFERENCES_WEIGHT: float = 0.5
DEFAULT_DIR_PRIOR: float = 1.0
DEFAULT_DIR_LEVEL: int = 2
DEFAULT_PERSISTENCE_THRESHOLD: float = 0.5
DEFAULT_MIN_REPO_SIZE: int = 4

_HUB_PREFIX = "__dir__"


@dataclass(slots=True, frozen=True)
class SubsystemStats:
    n_repos: int
    n_subsystems: int
    n_members: int
    n_locality: int
    pct_persistent: float
    total_seconds: float
    per_repo: dict[str, dict[str, float]] = field(default_factory=dict)


# ----- public API -----


def compute_subsystems(
    g: nx.MultiDiGraph,
    *,
    repos: Iterable[str] | None = None,
    default_resolution: float = DEFAULT_RESOLUTION,
    sweep: Sequence[float] = DEFAULT_SWEEP,
    seed: int = DEFAULT_SEED,
    contains_weight: float = DEFAULT_CONTAINS_WEIGHT,
    references_weight: float = DEFAULT_REFERENCES_WEIGHT,
    dir_prior: float = DEFAULT_DIR_PRIOR,
    dir_level: int = DEFAULT_DIR_LEVEL,
    persistence_threshold: float = DEFAULT_PERSISTENCE_THRESHOLD,
    min_repo_size: int = DEFAULT_MIN_REPO_SIZE,
    generated_at: str | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, SubsystemStats]:
    """Partition each repo in ``g`` into subsystems.

    Returns ``(subsystems_df, members_df, stats)`` with columns in
    ``SUBSYSTEMS_COLUMNS`` / ``SUBSYSTEM_MEMBERS_COLUMNS`` order. ``generated_at``
    (ISO 8601) is stamped once for the whole run; pass a fixed value for
    byte-identical re-runs, otherwise ``now()`` is used (which of course changes
    the ``generated_at`` column but not the partition — subsystem_ids exclude
    ``generated_at`` from their digest, see :func:`_subsystem_id`).
    """
    start = time.perf_counter()
    gen_at = generated_at or datetime.now(tz=UTC).isoformat()

    # Resolution sweep must include the default so the emitted partition is one
    # of the sweep points its own persistence is measured against.
    sweep_res = sorted({round(float(r), 6) for r in sweep} | {round(float(default_resolution), 6)})

    by_repo: dict[str, list[str]] = {}
    for n, d in g.nodes(data=True):
        repo = d.get("repo")
        if repo is None:
            continue
        by_repo.setdefault(repo, []).append(n)
    if repos is not None:
        wanted = set(repos)
        by_repo = {k: v for k, v in by_repo.items() if k in wanted}

    sub_rows: list[dict[str, object]] = []
    mem_rows: list[dict[str, object]] = []
    per_repo: dict[str, dict[str, float]] = {}
    n_repos_done = 0
    n_locality_total = 0
    n_persistent_total = 0
    n_members_total = 0

    config = {
        "stage": "A",
        "default_resolution": float(default_resolution),
        "sweep": [float(r) for r in sweep_res],
        "seed": int(seed),
        "contains_weight": float(contains_weight),
        "references_weight": float(references_weight),
        "dir_prior": float(dir_prior),
        "dir_level": int(dir_level),
        "persistence_threshold": float(persistence_threshold),
        "schema_version": SCHEMA_VERSION,
    }
    config_json = json.dumps(config, sort_keys=True, separators=(",", ":"))

    for repo in sorted(by_repo):
        node_ids = by_repo[repo]
        if len(node_ids) < min_repo_size:
            continue
        result = _partition_repo(
            g,
            repo=repo,
            node_ids=node_ids,
            default_resolution=default_resolution,
            sweep=sweep_res,
            seed=seed,
            contains_weight=contains_weight,
            references_weight=references_weight,
            dir_prior=dir_prior,
            dir_level=dir_level,
        )
        if result is None:
            continue
        labels, bc, placement, order = result
        n_repos_done += 1

        # Group members by their default-partition community, in deterministic
        # subsystem order (largest first, ties by first member id).
        comm_to_members: dict[int, list[str]] = {}
        for nid in order:  # order is the sorted real-node list
            comm_to_members.setdefault(int(labels[nid]), []).append(nid)

        # Rank communities deterministically for stable local ids (unused in the
        # id itself but keeps row order + reporting stable).
        ranked = sorted(
            comm_to_members.items(),
            key=lambda kv: (-len(kv[1]), min(kv[1])),
        )
        for _comm, members in ranked:
            members_sorted = sorted(members)
            ssid = _subsystem_id(repo, config_json, members_sorted)
            # Per-subsystem persistence = mean member boundary_confidence.
            ps = float(np.mean([bc[m] for m in members_sorted])) if members_sorted else 1.0
            ps = max(0.0, min(1.0, ps))
            sub_rows.append(
                {
                    "subsystem_id": ssid,
                    "repo": repo,
                    "n_members": len(members_sorted),
                    "resolution": float(default_resolution),
                    "persistence_score": ps,
                    "config": config_json,
                    "generated_at": gen_at,
                    "schema_version": SCHEMA_VERSION,
                }
            )
            for m in members_sorted:
                conf = max(0.0, min(1.0, float(bc[m])))
                mem_rows.append(
                    {
                        "subsystem_id": ssid,
                        "symbol_id": m,
                        "repo": repo,
                        "qualified_name": g.nodes[m].get("qualified_name", "") or "",
                        "boundary_confidence": conf,
                        "placement": placement[m],
                        "schema_version": SCHEMA_VERSION,
                    }
                )
                if conf >= persistence_threshold:
                    n_persistent_total += 1
                if placement[m] == "locality":
                    n_locality_total += 1
                n_members_total += 1

        n_this = len(order)
        n_loc_this = sum(1 for nid in order if placement[nid] == "locality")
        n_pers_this = sum(1 for nid in order if bc[nid] >= persistence_threshold)
        per_repo[repo] = {
            "n_members": float(n_this),
            "n_subsystems": float(len(ranked)),
            "n_locality": float(n_loc_this),
            "pct_persistent": (n_pers_this / n_this) if n_this else 0.0,
        }

    sub_df = pl.DataFrame(sub_rows, schema=_subsystems_schema()).select(SUBSYSTEMS_COLUMNS)
    mem_df = pl.DataFrame(mem_rows, schema=_members_schema()).select(SUBSYSTEM_MEMBERS_COLUMNS)
    # Deterministic, byte-stable row order.
    sub_df = sub_df.sort(["repo", "subsystem_id"])
    mem_df = mem_df.sort(["repo", "subsystem_id", "symbol_id"])

    pct = (n_persistent_total / n_members_total) if n_members_total else 0.0
    stats = SubsystemStats(
        n_repos=n_repos_done,
        n_subsystems=sub_df.height,
        n_members=n_members_total,
        n_locality=n_locality_total,
        pct_persistent=pct,
        total_seconds=round(time.perf_counter() - start, 3),
        per_repo=per_repo,
    )
    return sub_df, mem_df, stats


# ----- per-repo partitioning -----


def _partition_repo(
    g: nx.MultiDiGraph,
    *,
    repo: str,
    node_ids: list[str],
    default_resolution: float,
    sweep: Sequence[float],
    seed: int,
    contains_weight: float,
    references_weight: float,
    dir_prior: float,
    dir_level: int,
) -> tuple[dict[str, int], dict[str, float], dict[str, str], list[str]] | None:
    """Partition a single repo. Returns (labels, boundary_conf, placement, order).

    ``labels`` maps each real symbol_id → its default-partition community index.
    ``boundary_conf`` maps symbol_id → co-association ∈ [0,1] across the sweep.
    ``placement`` maps symbol_id → "structural" | "locality".
    ``order`` is the sorted real-node list (deterministic member iteration).
    """
    real = sorted(node_ids)
    real_set = set(real)
    idx = {n: i for i, n in enumerate(real)}
    n = len(real)

    # Weighted undirected graph over real symbols. Collapse parallel typed edges
    # into a single weight; skip self-loops. Track real (non-self) adjacency so
    # we can classify zero-profile/isolated symbols for locality placement.
    edge_w: dict[tuple[str, str], float] = {}
    has_real_edge: set[str] = set()
    for u, v, data in g.edges(data=True):
        if u == v or u not in real_set or v not in real_set:
            continue
        kind = data.get("kind", "")
        if kind == "CONTAINS":
            w = contains_weight
        elif kind == "REFERENCES":
            w = references_weight
        else:
            w = 1.0
        if w <= 0.0:
            continue
        key = (u, v) if u <= v else (v, u)
        edge_w[key] = edge_w.get(key, 0.0) + w
        has_real_edge.add(u)
        has_real_edge.add(v)

    h = nx.Graph()
    h.add_nodes_from(real)
    for (u, v), w in edge_w.items():
        h.add_edge(u, v, weight=w)

    # Declared-structure prior: connect every symbol to its per-directory hub.
    # Hub ids are repo-local and prefixed so they never collide with symbol ids.
    if dir_prior > 0.0:
        for nid in real:
            hub = _HUB_PREFIX + _dir_of(g.nodes[nid], dir_level)
            h.add_edge(nid, hub, weight=dir_prior)

    if h.number_of_edges() == 0:
        return None

    placement: dict[str, str] = {
        nid: ("structural" if nid in has_real_edge else "locality") for nid in real
    }

    # ── resolution sweep: one label vector per resolution ──
    label_mat = np.empty((len(sweep), n), dtype=np.int32)
    default_labels: np.ndarray | None = None
    for r_i, res in enumerate(sweep):
        lab = _louvain_label_vector(h, real, idx, resolution=res, seed=seed)
        label_mat[r_i] = lab
        if abs(res - default_resolution) < 1e-9 and default_labels is None:
            default_labels = lab
    if default_labels is None:
        # default_resolution wasn't in the swept set (shouldn't happen — caller
        # unions it in) — compute it explicitly.
        default_labels = _louvain_label_vector(
            h, real, idx, resolution=default_resolution, seed=seed
        )

    # ── per-member boundary_confidence via within-community co-association ──
    labels = {nid: int(default_labels[idx[nid]]) for nid in real}
    bc: dict[str, float] = {}
    n_runs = len(sweep)
    for comm in set(default_labels.tolist()):
        members_i = np.where(default_labels == comm)[0]
        m = len(members_i)
        if m == 1:
            bc[real[int(members_i[0])]] = 1.0
            continue
        sub = label_mat[:, members_i]  # (n_runs, m)
        # agreement[a,b] = # sweep runs where members a,b share a community
        agree = np.zeros((m, m), dtype=np.int32)
        for r_i in range(n_runs):
            col = sub[r_i]
            agree += (col[:, None] == col[None, :]).astype(np.int32)
        row_sums = agree.sum(axis=1) - np.diag(agree)  # exclude self
        conf = row_sums / (n_runs * (m - 1))
        for a in range(m):
            bc[real[int(members_i[a])]] = float(conf[a])

    return labels, bc, placement, real


def _louvain_label_vector(
    h: nx.Graph,
    real: list[str],
    idx: dict[str, int],
    *,
    resolution: float,
    seed: int,
) -> np.ndarray:
    """Run Louvain and project onto a deterministic per-real-node label vector.

    Communities are ranked by ``(-size-of-real-members, min real member id)`` —
    a total order independent of Python set-iteration/hash order — so the label
    integers are stable across processes and PYTHONHASHSEED values.
    """
    comms = nx.community.louvain_communities(
        h, weight="weight", resolution=resolution, seed=seed
    )
    real_comms: list[list[str]] = []
    for c in comms:
        members = [nid for nid in c if nid in idx]
        if members:
            real_comms.append(members)
    real_comms.sort(key=lambda members: (-len(members), min(members)))
    lab = np.full(len(real), -1, dtype=np.int32)
    for cid, members in enumerate(real_comms):
        for nid in members:
            lab[idx[nid]] = cid
    return lab


# ----- helpers -----


def _dir_of(node_attrs: dict, level: int) -> str:
    """Directory home of a symbol at the given path depth (the locality key)."""
    path = (node_attrs.get("file") or node_attrs.get("qualified_name") or "")
    path = str(path).split("::", 1)[0]
    parts = [p for p in path.split("/") if p]
    if not parts:
        return "(root)"
    return "/".join(parts[:level]) if len(parts) >= level else "/".join(parts)


def _subsystem_id(repo: str, config_json: str, sorted_members: list[str]) -> str:
    """Content-addressed subsystem id: blake3(repo + config + member digest).

    Excludes ``generated_at`` so a re-run at the same config over the same graph
    produces identical ids (byte-identical artifact requirement).
    """
    member_digest = blake3("\n".join(sorted_members).encode("utf-8")).hexdigest()
    h = blake3()
    h.update(repo.encode("utf-8"))
    h.update(b"\x00")
    h.update(config_json.encode("utf-8"))
    h.update(b"\x00")
    h.update(member_digest.encode("utf-8"))
    return "ss:" + h.hexdigest()[:24]


def _subsystems_schema() -> dict[str, pl.DataType]:
    return {
        "subsystem_id": pl.Utf8,
        "repo": pl.Utf8,
        "n_members": pl.Int64,
        "resolution": pl.Float64,
        "persistence_score": pl.Float64,
        "config": pl.Utf8,
        "generated_at": pl.Utf8,
        "schema_version": pl.Int64,
    }


def _members_schema() -> dict[str, pl.DataType]:
    return {
        "subsystem_id": pl.Utf8,
        "symbol_id": pl.Utf8,
        "repo": pl.Utf8,
        "qualified_name": pl.Utf8,
        "boundary_confidence": pl.Float64,
        "placement": pl.Utf8,
        "schema_version": pl.Int64,
    }


def write_subsystems(df: pl.DataFrame, out_path: str | Path) -> None:
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    df.select(SUBSYSTEMS_COLUMNS).write_parquet(p)


def write_subsystem_members(df: pl.DataFrame, out_path: str | Path) -> None:
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    df.select(SUBSYSTEM_MEMBERS_COLUMNS).write_parquet(p)


def write_manifest(
    data_dir: str | Path,
    *,
    n_subsystems: int,
    generated_at: str | None = None,
) -> Path:
    """Merge subsystem presence into ``<data_dir>/ctkr/manifest.json``.

    Reads any existing manifest and updates only the subsystem fields; every
    other presence flag / counter survives intact (multiple commands share the
    file). Creates a fresh manifest if none exists.
    """
    base = Path(data_dir).expanduser().resolve()
    manifest_path = base / "ctkr" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict = {}
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("manifest.json at %s is malformed; overwriting", manifest_path)
            existing = {}

    merged = {
        **existing,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(tz=UTC).isoformat(),
        "metacoding_data_dir": str(base),
        "subsystems": True,
        "subsystem_members": True,
        "n_subsystems": int(n_subsystems),
    }
    manifest_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return manifest_path


__all__ = [
    "DEFAULT_RESOLUTION",
    "DEFAULT_SWEEP",
    "DEFAULT_SEED",
    "SubsystemStats",
    "compute_subsystems",
    "write_subsystems",
    "write_subsystem_members",
    "write_manifest",
]
