"""Family-scoped role-equivalence sweep + idiom filter (MetaCoding-034).

Channel 2 of the lexicon pipeline: find role classes that RECUR across the
features of one farmOS module family, drop the framework idioms, and emit the
DOMAIN classes the glossary cannot name — a machine-readable gap list feeding
``propose-terms`` (MetaCoding-5c5). Everything here is deterministic and
LM-free; naming happens later.

Pipeline
--------

1. **Scope** — symbols whose ``file`` lies under ``modules/<family>/``; the
   *feature* of a symbol is the path segment right after the family
   (``modules/log/birth/src/…`` → feature ``birth``). Files sitting directly in
   the family directory belong to the pseudo-feature ``(family-root)``.
2. **Hom-profiles** — reuse ``<data_dir>/ctkr/hom_profiles.parquet`` when
   present, else compute in-memory over the full graph via
   :func:`ctkr.hom_profiles.compute_hom_profiles` (never written into the
   data-dir by this lane — a read-only sandbox must stay untouched).
3. **Role classes** — the existing deterministic clustering core,
   :func:`ctkr.label_roles.compute_role_clusters` (L1-normalise → 1/k-step
   discretize → bucket-key equality). Honest v1 caveat: this is bucket-key
   equality on hom-profiles, not the embedding lane — coarse but
   renaming-invariant by construction.
4. **Idiom filter (F6)** — tag each class ``framework-idiom`` vs ``domain``
   using boundary-quality's member classification
   (:func:`ctkr.boundary_quality.framework_reason`), extended member-wise: a
   member is idiomatic when it *is* a framework node, or when every
   non-CONTAINS edge it touches lands on a framework endpoint (pure wiring —
   storage/revision/migration/rendering scaffolding shows up this way). A
   class is ``framework-idiom`` when at least half its members are idiomatic.
5. **Glossary gap** — for each DOMAIN class recurring across ``>= k``
   features, look up the explicit :data:`GLOSSARY_TERM_TO_CLASS` mapping
   (seeded EMPTY on purpose: the machine-readable gap list is the product, a
   guessed mapping would poison it). Unmapped recurring domain classes get a
   partial TERM-SPEC v1 candidate with the term left blank.

TERM-SPEC v1 (shared contract with propose-terms and the binding gate)::

    {"term": str, "kind": "entity"|"action"|"assertion", "description": str,
     "probe_semantics": str, "discriminating_flow": {<flow-DSL sketch>},
     "provenance": {"role_class_id": str|null, "config_source": str|null,
                    "punts": [str], "first_pack_seal": null}}

A term is PROVISIONAL until ``first_pack_seal`` is filled by a real sealed
recording. This module only ever emits candidates with ``term=""`` and
``first_pack_seal=None`` — it proposes shapes, never binds vocabulary.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import networkx as nx
import polars as pl

from ctkr.boundary_quality import CONTAINMENT_KIND, framework_reason
from ctkr.label_roles import (
    DEFAULT_GRANULARITY,
    RoleCluster,
    compute_role_clusters,
)
from ctkr.oracle.glossary import ACTION_TERMS, ASSERTION_TERMS, ENTITY_TERMS

FAMILY_ROOT_FEATURE = "(family-root)"

# ── explicit glossary-term → role-class mapping ──────────────────────────────
# term -> class_id. Seeded EMPTY deliberately (MetaCoding-034): the point of
# the sweep is the machine-readable *gap* list. Entries are added only when a
# human (or a later, evidence-bearing lane) has verified that a glossary
# ACTION/ASSERTION/ENTITY term genuinely names the role class. A guessed
# mapping here would silently shrink the gap list — the exact failure the
# channel exists to surface.
GLOSSARY_TERM_TO_CLASS: dict[str, str] = {}

_VALID_MAPPING_TERMS = ACTION_TERMS | ASSERTION_TERMS | ENTITY_TERMS


def validate_mapping(mapping: dict[str, str]) -> None:
    """Reject mapping keys that are not glossary ACTION/ASSERTION/ENTITY terms."""
    bad = sorted(set(mapping) - _VALID_MAPPING_TERMS)
    if bad:
        raise ValueError(
            f"GLOSSARY_TERM_TO_CLASS keys must be glossary terms; unknown: {bad}"
        )


# ── scoping ──────────────────────────────────────────────────────────────────


def family_prefix(family: str) -> str:
    return f"modules/{family.strip('/')}/"


def feature_of(file_path: str, family: str) -> str | None:
    """Feature name for *file_path* within *family*, or None if out of scope.

    ``modules/log/birth/src/X.php`` → ``birth``;
    ``modules/log/log.info.yml`` → ``(family-root)``.
    """
    prefix = family_prefix(family)
    if not file_path or not file_path.startswith(prefix):
        return None
    rest = file_path[len(prefix):]
    if "/" not in rest:
        return FAMILY_ROOT_FEATURE
    return rest.split("/", 1)[0]


def scope_symbols(g: nx.MultiDiGraph, family: str) -> dict[str, str]:
    """``symbol_id -> feature`` for every node under ``modules/<family>/``."""
    out: dict[str, str] = {}
    for nid, attrs in g.nodes(data=True):
        feat = feature_of(attrs.get("file") or attrs.get("file_path") or "", family)
        if feat is not None:
            out[nid] = feat
    return out


# ── member-level idiom classification (boundary-quality, member-wise) ────────


def member_idiom_reason(g: nx.MultiDiGraph, nid: str) -> str | None:
    """Why this member is framework scaffolding, or None if domain.

    ``"external"``/``"drupal-base"`` — the node itself is a framework node
    (boundary-quality's :func:`framework_reason`).
    ``"framework-wiring"`` — every non-CONTAINS edge the node touches has a
    framework endpoint on the other side (pure scaffolding wiring; the node
    exists only to satisfy the framework contract). Nodes with no
    non-CONTAINS edges at all are NOT tagged — absence of evidence.
    """
    reason = framework_reason(g.nodes[nid])
    if reason is not None:
        return reason
    saw_edge = False
    for _, other, kind in _incident_edges(g, nid):
        if kind == CONTAINMENT_KIND:
            continue
        saw_edge = True
        if framework_reason(g.nodes[other]) is None:
            return None
    return "framework-wiring" if saw_edge else None


def _incident_edges(g: nx.MultiDiGraph, nid: str):
    for _, dst, kind in g.out_edges(nid, keys=True):
        if dst != nid:
            yield nid, dst, kind
    for src, _, kind in g.in_edges(nid, keys=True):
        if src != nid:
            yield nid, src, kind


# ── the sweep ────────────────────────────────────────────────────────────────


@dataclass(slots=True, frozen=True)
class RoleClassReport:
    """One family-scoped role class, tagged and glossary-checked."""

    class_id: str
    bucket_key: str
    members: tuple[str, ...]  # symbol_ids, sorted
    member_names: tuple[str, ...]  # qualified names, aligned with members
    features: tuple[str, ...]  # sorted distinct features the class recurs in
    tag: str  # "domain" | "framework-idiom"
    idiom_reasons: dict[str, int] = field(default_factory=dict)
    glossary_terms: tuple[str, ...] = ()
    candidate: dict[str, Any] | None = None

    @property
    def n_features(self) -> int:
        return len(self.features)


@dataclass(slots=True)
class RoleGapsResult:
    family: str
    k: int
    granularity_k: int
    n_scoped_symbols: int
    n_features: int
    n_classes: int
    n_framework_idiom: int
    n_domain: int
    n_recurring_domain: int
    n_gaps: int
    classes: list[RoleClassReport] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "record_type": "summary",
            "family": self.family,
            "k": self.k,
            "granularity_k": self.granularity_k,
            "n_scoped_symbols": self.n_scoped_symbols,
            "n_features": self.n_features,
            "n_classes": self.n_classes,
            "n_framework_idiom": self.n_framework_idiom,
            "n_domain": self.n_domain,
            "n_recurring_domain": self.n_recurring_domain,
            "n_gaps": self.n_gaps,
        }


def _candidate_kind(g: nx.MultiDiGraph, members: tuple[str, ...]) -> str:
    """Deterministic kind guess from member symbol kinds: methods/functions →
    ``action``, everything else → ``entity``. ``assertion`` is never guessed —
    a value predicate cannot be read off graph shape; propose-terms decides."""
    kinds = Counter((g.nodes[m].get("kind") or "").lower() for m in members)
    n_actionish = sum(c for k, c in kinds.items() if k in ("method", "function"))
    return "action" if n_actionish * 2 >= len(members) else "entity"


def _partial_term_spec(
    g: nx.MultiDiGraph,
    cls: RoleCluster,
    features: tuple[str, ...],
    member_names: tuple[str, ...],
) -> dict[str, Any]:
    """Partial TERM-SPEC v1 for an unnamed recurring domain role class."""
    kind = _candidate_kind(g, cls.members)
    return {
        "term": "",  # PROVISIONAL and unnamed: naming is propose-terms' job
        "kind": kind,
        "description": (
            f"Unnamed domain role class recurring across features "
            f"{', '.join(features)}; {len(cls.members)} structurally "
            f"role-equivalent symbols (hom-profile bucket {cls.bucket_key})."
        ),
        "probe_semantics": (
            "TBD — a probe must deliver the value this role computes at the "
            "boundary; derive from the shared hom-profile shape, not from "
            "member names."
        ),
        "discriminating_flow": {
            "given": [],
            "when": [],
            "then": [],
            "note": (
                "flow-DSL sketch deliberately empty: a discriminating flow "
                "requires domain semantics this deterministic channel does "
                "not have."
            ),
        },
        "provenance": {
            "role_class_id": cls.cluster_id,
            "config_source": None,
            "punts": [
                "term left blank (LLM naming happens in propose-terms)",
                "kind guessed from member symbol kinds "
                "(action-vs-assertion undecidable structurally)",
                "probe_semantics and discriminating_flow not derivable "
                "deterministically",
            ],
            "first_pack_seal": None,
        },
    }


def role_gaps(
    g: nx.MultiDiGraph,
    profiles_df: pl.DataFrame,
    *,
    family: str,
    k: int = 2,
    granularity_k: int = DEFAULT_GRANULARITY,
    min_cluster_size: int = 2,
    mapping: dict[str, str] | None = None,
) -> RoleGapsResult:
    """Run the family-scoped role-equivalence sweep with the idiom filter.

    Parameters
    ----------
    g
        Full loaded graph (used for scoping, idiom edges, and kind guesses).
    profiles_df
        Hom-profiles table (``symbol_id``, ``qualified_name``,
        ``profile_vec``) — the reused parquet or a fresh in-memory compute.
    family
        Module family, e.g. ``log`` → ``modules/log/``.
    k
        Minimum distinct features a class must recur across to count as
        recurring (default 2).
    mapping
        Explicit term→class_id table; defaults to the module-level
        :data:`GLOSSARY_TERM_TO_CLASS` (seeded empty).
    """
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    mapping = GLOSSARY_TERM_TO_CLASS if mapping is None else mapping
    validate_mapping(mapping)
    class_to_terms: dict[str, list[str]] = {}
    for term, cid in sorted(mapping.items()):
        class_to_terms.setdefault(cid, []).append(term)

    sym2feat = scope_symbols(g, family)
    scoped_df = profiles_df.filter(
        pl.col("symbol_id").is_in(sorted(sym2feat))
    )

    clusters = compute_role_clusters(
        scoped_df,
        granularity_k=granularity_k,
        min_cluster_size=min_cluster_size,
    )

    qn = {
        str(r["symbol_id"]): str(r.get("qualified_name") or "")
        for r in scoped_df.iter_rows(named=True)
    }

    reports: list[RoleClassReport] = []
    n_fw = n_dom = n_recur_dom = n_gaps = 0
    for cls in clusters:
        features = tuple(sorted({sym2feat[m] for m in cls.members}))
        reasons = Counter()
        n_idiom = 0
        for m in cls.members:
            r = member_idiom_reason(g, m)
            if r is not None:
                n_idiom += 1
                reasons[r] += 1
        is_idiom = n_idiom * 2 >= len(cls.members)
        tag = "framework-idiom" if is_idiom else "domain"
        terms = tuple(class_to_terms.get(cls.cluster_id, ()))
        member_names = tuple(qn.get(m, "") for m in cls.members)

        candidate: dict[str, Any] | None = None
        if tag == "framework-idiom":
            n_fw += 1
        else:
            n_dom += 1
            if len(features) >= k:
                n_recur_dom += 1
                if not terms:
                    n_gaps += 1
                    candidate = _partial_term_spec(g, cls, features, member_names)

        reports.append(
            RoleClassReport(
                class_id=cls.cluster_id,
                bucket_key=cls.bucket_key,
                members=cls.members,
                member_names=member_names,
                features=features,
                tag=tag,
                idiom_reasons=dict(reasons),
                glossary_terms=terms,
                candidate=candidate,
            )
        )

    return RoleGapsResult(
        family=family,
        k=k,
        granularity_k=granularity_k,
        n_scoped_symbols=len(sym2feat),
        n_features=len(set(sym2feat.values())),
        n_classes=len(reports),
        n_framework_idiom=n_fw,
        n_domain=n_dom,
        n_recurring_domain=n_recur_dom,
        n_gaps=n_gaps,
        classes=reports,
    )


def class_record(rep: RoleClassReport) -> dict[str, Any]:
    """The JSONL record for one role class (stable field order)."""
    return {
        "record_type": "role_class",
        "class_id": rep.class_id,
        "bucket_key": rep.bucket_key,
        "members": list(rep.members),
        "member_names": list(rep.member_names),
        "features": list(rep.features),
        "n_features": rep.n_features,
        "tag": rep.tag,
        "idiom_reasons": rep.idiom_reasons,
        "glossary_terms": list(rep.glossary_terms),
        "candidate": rep.candidate,
    }


__all__ = [
    "FAMILY_ROOT_FEATURE",
    "GLOSSARY_TERM_TO_CLASS",
    "validate_mapping",
    "family_prefix",
    "feature_of",
    "scope_symbols",
    "member_idiom_reason",
    "RoleClassReport",
    "RoleGapsResult",
    "role_gaps",
    "class_record",
]
