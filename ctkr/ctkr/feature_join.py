"""Feature ↔ subsystem join — MetaCoding-7fs.

Joins the D1 Feature Inventory (``features.parquet``, produced by the Drupal
declarative lane ``ctkr drupal-harvest``) to the structural lane
(``subsystem_members.parquet`` + the graph-export ``nodes.jsonl``) so each
feature row carries the subsystem_ids of the structural partitions its file
subtree overlaps.

The join is purely additive:

* ``subsystem_ids`` — sorted list of structural subsystem IDs whose member
  symbols live in the feature's module subtree (as determined by
  ``member_globs``). Empty when the structural lane has not run or the module
  has no symbols in the graph.
* ``interface_refs`` — left empty (``[]``) in this lane; populated later when
  the interface-extraction lane is wired. Placeholder is explicit so consumers
  don't need to guard ``AttributeError``.

The **disagreement signal** — ``feature_subsystem_disagree.parquet`` — records
the degree of mismatch between the product partition (features / modules) and
the structural partition (Louvain subsystems). A feature whose file subtree
spans many subsystems is a cross-cutting concern; a feature whose subtree maps
to exactly one subsystem is a clean vertical slice (a good first port target).
This is the feature-axis analogue of the subsystem ↔ declared-module
disagreement the subsystem partition already surfaces
(``ct-subsystem-extraction.md`` §2.1, ``decomposition-schema.md`` §2.1).

Inputs (all under ``<data_dir>/ctkr/``):
    ``features.parquet``          D1 Feature Inventory from the drupal lane
    ``subsystem_members.parquet`` structural lane members (symbol → subsystem)
    ``export/nodes.jsonl``        graph-export symbols carrying file paths

Outputs (under ``<data_dir>/ctkr/``):
    ``features.parquet``                    in-place update with subsystem_ids
    ``feature_subsystem_disagree.parquet``  disagreement signal (one row per
                                            feature, sorted by n_subsystems desc)
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

logger = logging.getLogger("ctkr.feature_join")

FEATURE_DISAGREE_FILE = "feature_subsystem_disagree.parquet"

DISAGREE_COLUMNS: tuple[str, ...] = (
    "feature_id",
    "name",
    "label",
    "n_subsystems",
    "subsystem_ids",
    "is_cross_cutting",
    "schema_version",
)

# Schema version inherited from the ctkr schema convention.
_SCHEMA_VERSION = 1


@dataclass
class JoinStats:
    """Run summary returned by :func:`join_features_to_subsystems`."""

    n_features: int = 0
    n_features_with_subsystems: int = 0
    n_features_cross_cutting: int = 0
    avg_subsystems_per_feature: float = 0.0
    top_disagreements: list[dict] = field(default_factory=list)
    nodes_loaded: int = 0
    members_loaded: int = 0
    elapsed_seconds: float = 0.0


def _matches_glob(file_path: str, glob: str) -> bool:
    """Return True if *file_path* (repo-relative POSIX string) matches *glob*.

    Supports the ``<dir>/**`` pattern emitted by :mod:`ctkr.drupal` for
    module subtrees.  Falls back to exact-match for glob-free patterns.
    """
    if glob.endswith("/**"):
        prefix = glob[:-3]  # strip trailing /**
        return file_path == prefix or file_path.startswith(prefix + "/")
    if glob == "**":
        return True  # entire repo — unlikely but handle it
    # Plain prefix with trailing * at end of a component (e.g. "modules/**/Farm*.php")
    # is not currently emitted by the drupal lane; skip full fnmatch cost and
    # fall back to exact-match so we never silently swallow unknown patterns.
    return file_path == glob


def _load_file_to_subsystems(
    nodes_path: Path,
    members_path: Path,
) -> tuple[dict[str, set[str]], int, int]:
    """Build a ``{file_path: set(subsystem_id)}`` mapping.

    Loads ``nodes.jsonl`` (graph export) for the file_path per symbol, then
    joins against ``subsystem_members.parquet`` (structural lane) for the
    subsystem assignment.

    Returns ``(mapping, n_nodes_loaded, n_members_loaded)``.
    """
    # symbol_id → file_path  (from graph export)
    symbol_file: dict[str, str] = {}
    n_nodes = 0
    with nodes_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            node = json.loads(line)
            n_nodes += 1
            fp = node.get("file") or ""
            if fp:
                symbol_file[node["id"]] = fp

    # symbol_id → subsystem_id  (from subsystem_members.parquet)
    members = pl.read_parquet(members_path)
    n_members = members.height
    symbol_subsystem: dict[str, str] = {}
    for row in members.iter_rows(named=True):
        symbol_subsystem[row["symbol_id"]] = row["subsystem_id"]

    # file_path → set(subsystem_id)
    file_subsystems: dict[str, set[str]] = defaultdict(set)
    for sym_id, fp in symbol_file.items():
        if sym_id in symbol_subsystem:
            file_subsystems[fp].add(symbol_subsystem[sym_id])

    return dict(file_subsystems), n_nodes, n_members


def join_features_to_subsystems(
    data_dir: str | Path,
    *,
    features_path: str | Path | None = None,
    out_features_path: str | Path | None = None,
    out_disagree_path: str | Path | None = None,
) -> JoinStats:
    """Join ``features.parquet`` to subsystem membership and emit the disagreement signal.

    Parameters
    ----------
    data_dir
        The MetaCoding data directory (``<project>/.metacoding/`` or the path
        passed as ``--data-dir`` to ``ctkr subsystems``). Expected layout::

            <data_dir>/ctkr/features.parquet
            <data_dir>/ctkr/subsystem_members.parquet
            <data_dir>/ctkr/export/nodes.jsonl

    features_path
        Override: explicit path to ``features.parquet``.  Defaults to
        ``<data_dir>/ctkr/features.parquet``.
    out_features_path
        Where to write the enriched ``features.parquet``.  Defaults to
        *features_path* (in-place update).
    out_disagree_path
        Where to write ``feature_subsystem_disagree.parquet``.  Defaults to
        ``<data_dir>/ctkr/feature_subsystem_disagree.parquet``.

    Returns
    -------
    JoinStats
        Summary counts for CLI output and assertions.

    Raises
    ------
    FileNotFoundError
        When ``subsystem_members.parquet`` or ``nodes.jsonl`` are missing
        (the structural lane has not been run for *data_dir*).
    """
    import time

    t0 = time.monotonic()

    data_dir = Path(data_dir).expanduser().resolve()
    ctkr_dir = data_dir / "ctkr"

    feat_path = Path(features_path).expanduser().resolve() if features_path else ctkr_dir / "features.parquet"
    members_path = ctkr_dir / "subsystem_members.parquet"
    nodes_path = ctkr_dir / "export" / "nodes.jsonl"

    for p, label in [(feat_path, "features.parquet"), (members_path, "subsystem_members.parquet"), (nodes_path, "nodes.jsonl")]:
        if not p.exists():
            raise FileNotFoundError(f"{label} not found at {p}")

    out_feat = Path(out_features_path).expanduser().resolve() if out_features_path else feat_path
    out_disagree = (
        Path(out_disagree_path).expanduser().resolve()
        if out_disagree_path
        else ctkr_dir / FEATURE_DISAGREE_FILE
    )

    # ── structural data ──────────────────────────────────────────────────────
    logger.debug("loading nodes.jsonl + subsystem_members.parquet …")
    file_subsystems, n_nodes, n_members = _load_file_to_subsystems(nodes_path, members_path)
    logger.debug("  %d nodes, %d members, %d files with subsystem assignments",
                 n_nodes, n_members, len(file_subsystems))

    # ── features ─────────────────────────────────────────────────────────────
    features = pl.read_parquet(feat_path)

    # Compute subsystem_ids for each feature via glob matching.
    subsystem_ids_col: list[list[str]] = []
    for row in features.iter_rows(named=True):
        globs: list[str] = row.get("member_globs") or []
        matched: set[str] = set()
        for fp, sids in file_subsystems.items():
            if any(_matches_glob(fp, g) for g in globs):
                matched |= sids
        subsystem_ids_col.append(sorted(matched))

    # Add or replace subsystem_ids column.
    if "subsystem_ids" in features.columns:
        features = features.with_columns(
            pl.Series("subsystem_ids", subsystem_ids_col, dtype=pl.List(pl.Utf8))
        )
    else:
        features = features.with_columns(
            pl.Series("subsystem_ids", subsystem_ids_col, dtype=pl.List(pl.Utf8))
        )

    # Ensure interface_refs column exists (placeholder; populated by a later lane).
    if "interface_refs" not in features.columns:
        features = features.with_columns(
            pl.lit(None).cast(pl.List(pl.Utf8)).alias("interface_refs")
        )

    # ── write enriched features ───────────────────────────────────────────────
    out_feat.parent.mkdir(parents=True, exist_ok=True)
    features.write_parquet(out_feat)
    logger.debug("wrote enriched features.parquet → %s", out_feat)

    # ── disagreement signal ──────────────────────────────────────────────────
    disagree_rows: list[dict] = []
    for row, sids in zip(features.iter_rows(named=True), subsystem_ids_col):
        n = len(sids)
        disagree_rows.append(
            {
                "feature_id": row["feature_id"],
                "name": row["name"],
                "label": row["label"],
                "n_subsystems": n,
                "subsystem_ids": sids,
                "is_cross_cutting": n > 1,
                "schema_version": _SCHEMA_VERSION,
            }
        )

    disagree_rows.sort(key=lambda r: (-r["n_subsystems"], r["name"]))

    disagree_df = pl.DataFrame(
        disagree_rows,
        schema={
            "feature_id": pl.Utf8,
            "name": pl.Utf8,
            "label": pl.Utf8,
            "n_subsystems": pl.Int64,
            "subsystem_ids": pl.List(pl.Utf8),
            "is_cross_cutting": pl.Boolean,
            "schema_version": pl.Int64,
        },
    ).select(DISAGREE_COLUMNS)

    out_disagree.parent.mkdir(parents=True, exist_ok=True)
    disagree_df.write_parquet(out_disagree)
    logger.debug("wrote feature_subsystem_disagree.parquet → %s", out_disagree)

    # ── stats ────────────────────────────────────────────────────────────────
    n_with = sum(1 for sids in subsystem_ids_col if sids)
    n_cross = sum(1 for sids in subsystem_ids_col if len(sids) > 1)
    avg = (sum(len(sids) for sids in subsystem_ids_col) / len(subsystem_ids_col)) if subsystem_ids_col else 0.0

    top = [
        {"name": r["name"], "label": r["label"], "n_subsystems": r["n_subsystems"]}
        for r in disagree_rows[:10]
        if r["n_subsystems"] > 1
    ]

    return JoinStats(
        n_features=len(subsystem_ids_col),
        n_features_with_subsystems=n_with,
        n_features_cross_cutting=n_cross,
        avg_subsystems_per_feature=round(avg, 2),
        top_disagreements=top,
        nodes_loaded=n_nodes,
        members_loaded=n_members,
        elapsed_seconds=round(time.monotonic() - t0, 3),
    )
