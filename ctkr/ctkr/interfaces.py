"""Interface + data-shape extraction — Stage B (subsystem-extraction §3, T2).

A subsystem's **interface contract is not written down anywhere — it is the set
of morphisms crossing its boundary** (§3). For subsystem ``S`` with complement
``S̄`` this module extracts, from the typed graph + the T1 partition:

- **provides** — generating morphisms ``x → s`` with ``x ∈ S̄``, ``s ∈ S``: the
  API surface. Each externally-referenced internal symbol ``s`` is an export;
  the crossing edge kind is its usage mode (``REFERENCES``/``CALLS`` in =
  invoked, ``IMPLEMENTS`` in = extension point, ``TYPE_OF``/``RETURNS_TYPE`` in
  = used as a type, ``CONSTRUCTS`` in = instantiated).
- **consumes** — morphisms ``s → y`` with ``y ∈ S̄``: the dependency surface.
  Grouped by target symbol *and* target subsystem, this is the deck's
  subsystem-level topology (the quotient of ``C``'s edges by the partition).
- **data shapes** — the type vocabulary crossing the boundary, recovered from
  the data-flavoured edge kinds (``TYPE_OF``/``RETURNS_TYPE``/``CONSTRUCTS`` for
  types, ``READS_FIELD``/``WRITES_FIELD`` for field-level flow). Types that
  cross the interface are **boundary** shapes (a port must reproduce them
  semantically); private ones are **internal** shapes (a port may restructure
  them). Per-field read/write direction is recorded so an output contract (a
  field written by ``S`` and read by ``S̄``) is distinguishable from an input.

``CONTAINS`` is the containment backbone (tier-A scaffolding, §6.1) and is
**not** a contract morphism — it is excluded from interface edges. Everything
else present in the graph is a crossing contract morphism.

Roll-up to exports. A crossing edge often lands on a *nested* member — a field
of an exported type (``types.ts::PatternRow::confidence``) or a parameter of an
exported method (``artifacts.ts::CtkrHandle::homProfilesKnn::…::k``). The
re-implementer's API surface is the enclosing **top-level declaration**, so each
row also carries ``internal_export_*``: the top-level owner of
``internal_symbol_id``, computed name-blind from the qualified-name path (the
first path segment after the file), independent of the (approximate,
synthetic-node-laden) CONTAINS chain. The raw ``internal_symbol_id`` stays
maximal-precision; the roll-up is an additive convenience column.

Structure-only lane (§5): this module reads exclusively typed edges + the T1
partition. No identifier text influences any boundary or contract. The NL lane
(T5) labels these rows later.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import networkx as nx
import polars as pl

from ctkr.schema import (
    DATA_SHAPES_COLUMNS,
    INTERFACES_COLUMNS,
    SCHEMA_VERSION,
)

logger = logging.getLogger("ctkr.interfaces")

# ── edge-kind taxonomy (§3) ──
# CONTAINS is scaffolding, never a contract morphism (§6.1 tier-A); excluded.
CONTAINMENT_KIND = "CONTAINS"
# Data-flavoured kinds whose *target* is a type (the type vocabulary crossing
# the boundary — §3 "for every type T referenced by a crossing TYPE_OF /
# RETURNS_TYPE / CONSTRUCTS edge").
TYPE_EDGE_KINDS: frozenset[str] = frozenset({"TYPE_OF", "RETURNS_TYPE", "CONSTRUCTS"})
# Field-level flow edges (READS_FIELD / WRITES_FIELD target a field).
READ_KIND = "READS_FIELD"
WRITE_KIND = "WRITES_FIELD"
FIELD_FLOW_KINDS: frozenset[str] = frozenset({READ_KIND, WRITE_KIND})
# All data-alphabet kinds, for the coverage note (§3 reality check).
DATA_ALPHABET_KINDS: tuple[str, ...] = (
    "TYPE_OF",
    "RETURNS_TYPE",
    "CONSTRUCTS",
    "READS_FIELD",
    "WRITES_FIELD",
)

# Node kinds that name a data shape (a type) vs. a field of one. Kept broad so
# the extractor is stack-agnostic (Python class / TS interface|type_alias /
# Rust struct|enum|trait, …).
TYPE_KINDS: frozenset[str] = frozenset(
    {"class", "interface", "type_alias", "enum", "struct", "trait", "type", "record"}
)
FIELD_KINDS: frozenset[str] = frozenset({"field", "property", "enum_member", "attribute"})


@dataclass(slots=True, frozen=True)
class InterfaceStats:
    n_interfaces: int
    n_provides: int
    n_consumes: int
    n_data_shapes: int
    n_boundary_types: int
    n_internal_types: int
    n_subsystems: int
    total_seconds: float
    per_subsystem: dict[str, dict[str, float]] = field(default_factory=dict)
    alphabet_coverage: dict[str, dict] = field(default_factory=dict)


# ----- public API -----


def compute_interfaces(
    g: nx.MultiDiGraph,
    members_df: pl.DataFrame,
    *,
    repos: Iterable[str] | None = None,
    generated_at: str | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, InterfaceStats]:
    """Extract boundary morphisms + data shapes for every subsystem in
    ``members_df``.

    Returns ``(interfaces_df, data_shapes_df, stats)`` with columns in
    ``INTERFACES_COLUMNS`` / ``DATA_SHAPES_COLUMNS`` order. Deterministic: rows
    are content-sorted so re-runs over the same graph + partition are
    byte-identical.
    """
    start = time.perf_counter()
    _gen_at = generated_at or datetime.now(tz=UTC).isoformat()

    # symbol → subsystem, and the per-subsystem repo (all members of a
    # subsystem share a repo — T1 partitions per repo).
    sym2sub: dict[str, str] = {}
    sub2repo: dict[str, str] = {}
    wanted = set(repos) if repos is not None else None
    for row in members_df.iter_rows(named=True):
        r = row["repo"]
        if wanted is not None and r not in wanted:
            continue
        sym2sub[row["symbol_id"]] = row["subsystem_id"]
        sub2repo[row["subsystem_id"]] = r
    if not sym2sub:
        empty_i = pl.DataFrame(schema=_interfaces_schema()).select(INTERFACES_COLUMNS)
        empty_d = pl.DataFrame(schema=_data_shapes_schema()).select(DATA_SHAPES_COLUMNS)
        return empty_i, empty_d, InterfaceStats(0, 0, 0, 0, 0, 0, 0, 0.0)

    # qualified_name → symbol_id (first wins; deterministic since we iterate the
    # graph's insertion order which is the export file order).
    byqn: dict[str, str] = {}
    for n, d in g.nodes(data=True):
        q = d.get("qualified_name")
        if q and q not in byqn:
            byqn[q] = n

    def nd(n: str) -> dict:
        return g.nodes.get(n, {})

    def qn(n: str) -> str:
        return nd(n).get("qualified_name", "") or ""

    def top_export(sym_id: str) -> tuple[str | None, str]:
        """Top-level declaration owning ``sym_id`` (name-blind, path-based).

        The qualified name is ``<file>::<decl>[::<nested>…]``; the export is
        ``<file>::<decl>``. Files themselves (no ``::``) own themselves. Returns
        ``(export_symbol_id_or_None, export_qualified_name)``.
        """
        d = nd(sym_id)
        q = d.get("qualified_name") or ""
        f = d.get("file") or ""
        if not q:
            return sym_id, ""
        if f and q == f:  # a file node — its own top level
            return byqn.get(q, sym_id), q
        if f and q.startswith(f + "::"):
            seg1 = q[len(f) + 2 :].split("::", 1)[0]
            top_qn = f + "::" + seg1
        elif "::" in q:
            parts = q.split("::")
            top_qn = parts[0] + "::" + parts[1] if len(parts) > 1 else q
        else:
            top_qn = q
        return byqn.get(top_qn, sym_id if top_qn == q else None), top_qn

    # ── containment maps (from CONTAINS edges) ──
    contains_children: dict[str, list[str]] = defaultdict(list)
    contains_parent: dict[str, str] = {}
    for u, v, k in g.edges(keys=True):
        if k == CONTAINMENT_KIND:
            contains_children[u].append(v)
            contains_parent[v] = u

    # ── interface rows (cross-boundary contract morphisms) ──
    # keyed by (subsystem, direction, internal, external, external_sub, kind)
    iface_agg: dict[tuple, int] = defaultdict(int)
    for u, v, k, data in g.edges(keys=True, data=True):
        if k == CONTAINMENT_KIND or u == v:
            continue
        su = sym2sub.get(u)
        sv = sym2sub.get(v)
        if su == sv:  # both inside the same subsystem (or both unpartitioned)
            continue
        cnt = int(data.get("count", 1) or 1)
        if sv is not None:  # v internal to sv → provides (external u references it)
            iface_agg[(sv, "provides", v, u, su, k)] += cnt
        if su is not None:  # u internal to su → consumes (it references external v)
            iface_agg[(su, "consumes", u, v, sv, k)] += cnt

    iface_rows: list[dict[str, object]] = []
    prov_by_sub: dict[str, int] = defaultdict(int)
    cons_by_sub: dict[str, int] = defaultdict(int)
    # boundary type set: any internal symbol crossing via a type-edge, plus the
    # enclosing type of any field crossing via a field-flow edge.
    boundary_types: set[str] = set()
    for (sub, direction, internal, external, ext_sub, kind), cnt in iface_agg.items():
        ex_id, ex_qn = top_export(internal)
        iface_rows.append(
            {
                "subsystem_id": sub,
                "repo": sub2repo.get(sub, ""),
                "direction": direction,
                "edge_kind": kind,
                "edge_count": int(cnt),
                "internal_symbol_id": internal,
                "internal_qualified_name": qn(internal),
                "internal_export_symbol_id": ex_id,
                "internal_export_qualified_name": ex_qn,
                "external_symbol_id": external,
                "external_qualified_name": qn(external),
                "external_subsystem_id": ext_sub,
                "schema_version": SCHEMA_VERSION,
            }
        )
        if direction == "provides":
            prov_by_sub[sub] += 1
        else:
            cons_by_sub[sub] += 1
        # boundary-type accounting (from the internal side of the crossing)
        if kind in TYPE_EDGE_KINDS:
            boundary_types.add(internal)
        elif kind in FIELD_FLOW_KINDS:
            parent = contains_parent.get(internal)
            if parent is not None:
                boundary_types.add(parent)

    # ── data-shape rows ──
    # For every type member of a subsystem, walk its contained fields and record
    # per-field read/write direction; flag the type boundary vs internal.
    data_rows: list[dict[str, object]] = []
    n_boundary_types = 0
    n_internal_types = 0
    boundary_by_sub: dict[str, int] = defaultdict(int)
    # Precompute per-field readers/writers split by subsystem membership, and
    # per-type constructors, from the graph edges once.
    field_readers: dict[str, set[str]] = defaultdict(set)
    field_writers: dict[str, set[str]] = defaultdict(set)
    type_constructors: dict[str, list[str]] = defaultdict(list)
    field_type_of: dict[str, str] = {}
    for u, v, k in g.edges(keys=True):
        if k == READ_KIND:
            field_readers[v].add(u)
        elif k == WRITE_KIND:
            field_writers[v].add(u)
        elif k == "CONSTRUCTS":
            type_constructors[v].append(u)
        elif k == "TYPE_OF":
            # field/param v-as-src is typed-as v-dst; store the field's own type.
            field_type_of.setdefault(u, v)

    for sym_id, sub in sorted(sym2sub.items()):
        kind = nd(sym_id).get("kind", "")
        if kind not in TYPE_KINDS:
            continue
        is_boundary = sym_id in boundary_types
        # fields of this type: contained members of a field kind
        fields = [
            c
            for c in contains_children.get(sym_id, [])
            if nd(c).get("kind", "") in FIELD_KINDS
        ]
        if not fields and not is_boundary:
            continue  # private, fieldless internal type — not spec-bearing
        if is_boundary:
            n_boundary_types += 1
            boundary_by_sub[sub] += 1
        else:
            n_internal_types += 1
        constructed_by = sorted({qn(c) for c in type_constructors.get(sym_id, []) if qn(c)})
        tqn = qn(sym_id)
        repo = sub2repo.get(sub, "")
        if not fields:
            data_rows.append(
                _data_row(sub, repo, sym_id, tqn, is_boundary, None, None, None,
                          False, False, False, False, constructed_by)
            )
            continue
        for f in fields:
            fqn = qn(f)
            fname = nd(f).get("short_name") or (fqn.split("::")[-1] if fqn else None)
            ftype_id = field_type_of.get(f)
            ftype = qn(ftype_id) if ftype_id else None
            readers = field_readers.get(f, set())
            writers = field_writers.get(f, set())
            r_int = any(sym2sub.get(x) == sub for x in readers)
            r_ext = any(sym2sub.get(x) != sub for x in readers)
            w_int = any(sym2sub.get(x) == sub for x in writers)
            w_ext = any(sym2sub.get(x) != sub for x in writers)
            data_rows.append(
                _data_row(sub, repo, sym_id, tqn, is_boundary, f, fname, ftype,
                          r_int, r_ext, w_int, w_ext, constructed_by)
            )

    iface_df = pl.DataFrame(iface_rows, schema=_interfaces_schema()).select(INTERFACES_COLUMNS)
    data_df = pl.DataFrame(data_rows, schema=_data_shapes_schema()).select(DATA_SHAPES_COLUMNS)
    iface_df = iface_df.sort(
        ["repo", "subsystem_id", "direction", "internal_symbol_id",
         "external_symbol_id", "edge_kind"]
    )
    data_df = data_df.sort(
        ["repo", "subsystem_id", "type_symbol_id", "field_name"], nulls_last=True
    )

    alphabet = _alphabet_coverage(g, sym2sub, sub2repo)

    per_sub: dict[str, dict[str, float]] = {}
    for sub in sorted(set(sym2sub.values())):
        per_sub[sub] = {
            "provides": float(prov_by_sub.get(sub, 0)),
            "consumes": float(cons_by_sub.get(sub, 0)),
            "boundary_types": float(boundary_by_sub.get(sub, 0)),
        }

    stats = InterfaceStats(
        n_interfaces=iface_df.height,
        n_provides=sum(prov_by_sub.values()),
        n_consumes=sum(cons_by_sub.values()),
        n_data_shapes=data_df.height,
        n_boundary_types=n_boundary_types,
        n_internal_types=n_internal_types,
        n_subsystems=len(set(sym2sub.values())),
        total_seconds=round(time.perf_counter() - start, 3),
        per_subsystem=per_sub,
        alphabet_coverage=alphabet,
    )
    return iface_df, data_df, stats


# ----- helpers -----


def _data_row(
    sub, repo, type_id, type_qn, boundary, field_id, field_name, field_type,
    r_int, r_ext, w_int, w_ext, constructed_by,
) -> dict[str, object]:
    return {
        "subsystem_id": sub,
        "repo": repo,
        "type_symbol_id": type_id,
        "type_qualified_name": type_qn,
        "boundary": bool(boundary),
        "field_symbol_id": field_id,
        "field_name": field_name,
        "field_type": field_type,
        "read_by_internal": bool(r_int),
        "read_by_external": bool(r_ext),
        "written_by_internal": bool(w_int),
        "written_by_external": bool(w_ext),
        "constructed_by": list(constructed_by),
        "schema_version": SCHEMA_VERSION,
    }


def _alphabet_coverage(
    g: nx.MultiDiGraph,
    sym2sub: dict[str, str],
    sub2repo: dict[str, str],
) -> dict[str, dict]:
    """Per-repo data-alphabet coverage note (§3 reality check).

    The data alphabet is per-lane and per-language uneven — a thin shapes
    section must read as an *extractor gap*, not "this subsystem has no data
    model". Emit, per repo lane, the raw data-edge-kind histogram, the source
    (tree-sitter vs scip) mix, and a human note.
    """
    repos = sorted(set(sub2repo.values()))
    # per-repo edge-kind counts (edges with both endpoints in the repo's members)
    kind_counts: dict[str, dict[str, int]] = {r: defaultdict(int) for r in repos}
    total_edges: dict[str, int] = defaultdict(int)
    for u, v, k in g.edges(keys=True):
        su = sym2sub.get(u)
        ru = sub2repo.get(su) if su else None
        if ru is None:
            continue
        total_edges[ru] += 1
        if k in DATA_ALPHABET_KINDS:
            kind_counts[ru][k] += 1
    # per-repo source mix (scip vs tree_sitter) from node attrs
    src_counts: dict[str, dict[str, int]] = {r: defaultdict(int) for r in repos}
    for n, d in g.nodes(data=True):
        sub = sym2sub.get(n)
        r = sub2repo.get(sub) if sub else None
        if r is None:
            continue
        src_counts[r][d.get("source", "unknown")] += 1
    out: dict[str, dict] = {}
    for r in repos:
        dk = {k: int(kind_counts[r].get(k, 0)) for k in DATA_ALPHABET_KINDS}
        present = [k for k, c in dk.items() if c > 0]
        missing = [k for k, c in dk.items() if c == 0]
        srcs = dict(src_counts[r])
        n_src = sum(srcs.values()) or 1
        scip_frac = round(srcs.get("scip", 0) / n_src, 3)
        thin = len(present) < 3
        note = (
            f"data alphabet {'THIN' if thin else 'ok'}: "
            f"{len(present)}/{len(DATA_ALPHABET_KINDS)} data-edge kinds present "
            f"({', '.join(present) or 'none'}); "
            f"missing: {', '.join(missing) or 'none'}; "
            f"scip_fraction={scip_frac}. "
            f"Thin data_shapes for this lane read as extractor coverage, not "
            f"an empty data model (§3)."
        )
        out[r] = {
            "data_edge_kinds": dk,
            "n_edges": int(total_edges[r]),
            "source_mix": srcs,
            "scip_fraction": scip_frac,
            "thin": thin,
            "note": note,
        }
    return out


def _interfaces_schema() -> dict[str, pl.DataType]:
    return {
        "subsystem_id": pl.Utf8,
        "repo": pl.Utf8,
        "direction": pl.Utf8,
        "edge_kind": pl.Utf8,
        "edge_count": pl.Int64,
        "internal_symbol_id": pl.Utf8,
        "internal_qualified_name": pl.Utf8,
        "internal_export_symbol_id": pl.Utf8,
        "internal_export_qualified_name": pl.Utf8,
        "external_symbol_id": pl.Utf8,
        "external_qualified_name": pl.Utf8,
        "external_subsystem_id": pl.Utf8,
        "schema_version": pl.Int64,
    }


def _data_shapes_schema() -> dict[str, pl.DataType]:
    return {
        "subsystem_id": pl.Utf8,
        "repo": pl.Utf8,
        "type_symbol_id": pl.Utf8,
        "type_qualified_name": pl.Utf8,
        "boundary": pl.Boolean,
        "field_symbol_id": pl.Utf8,
        "field_name": pl.Utf8,
        "field_type": pl.Utf8,
        "read_by_internal": pl.Boolean,
        "read_by_external": pl.Boolean,
        "written_by_internal": pl.Boolean,
        "written_by_external": pl.Boolean,
        "constructed_by": pl.List(pl.Utf8),
        "schema_version": pl.Int64,
    }


def write_interfaces(df: pl.DataFrame, out_path: str | Path) -> None:
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    df.select(INTERFACES_COLUMNS).write_parquet(p)


def write_data_shapes(df: pl.DataFrame, out_path: str | Path) -> None:
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    df.select(DATA_SHAPES_COLUMNS).write_parquet(p)


def write_manifest(
    data_dir: str | Path,
    *,
    n_interfaces: int,
    n_data_shapes: int,
    alphabet_coverage: dict | None = None,
    generated_at: str | None = None,
) -> Path:
    """Merge interface presence into ``<data_dir>/ctkr/manifest.json``.

    Additive: reads any existing manifest and updates only the interface fields
    (multiple commands share the file). Creates a fresh manifest if none exists.
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
        "interfaces": True,
        "data_shapes": True,
        "n_interfaces": int(n_interfaces),
        "n_data_shapes": int(n_data_shapes),
    }
    if alphabet_coverage is not None:
        merged["alphabet_coverage"] = alphabet_coverage
    manifest_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return manifest_path


__all__ = [
    "TYPE_EDGE_KINDS",
    "FIELD_FLOW_KINDS",
    "DATA_ALPHABET_KINDS",
    "InterfaceStats",
    "compute_interfaces",
    "write_interfaces",
    "write_data_shapes",
    "write_manifest",
]
