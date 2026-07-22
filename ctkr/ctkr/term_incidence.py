"""Feature × glossary-term incidence graph (MetaCoding-01k, lexicon channel 3).

The feature-kinds analogue for the *oracle vocabulary*: where
:mod:`ctkr.feature_kinds` graphs features against the event kinds their builds
emit/fold, this module graphs features against the **glossary terms their sealed
evidence exercises** — the assertion terms a pack's ``then`` steps assert and the
action terms its ``when`` steps perform.

Reading the graph by degree answers the Elenchus's wave-1 pith question
("did we port one spine four times?") as a number:

* **SPINE** — terms exercised by ≥ ``spine_threshold`` (default 80%) of the
  features. High spine mass means the features are re-walking one shared
  backbone of the domain language.
* **SHARED** — terms exercised by more than one feature but below the spine
  threshold.
* **IDENTITY** — degree-1 terms: the vocabulary only one feature needed. These
  are what distinguish a feature *in the lexicon*; a feature with no identity
  terms is lexically indistinguishable from the spine.

**Identity coverage** (optional, degrades gracefully): given the role-sweep's
``role-classes.jsonl`` (MetaCoding-034 — recurring domain role classes, each
optionally *named* by glossary terms), compute per feature

    distinguishing domain classes reachable by any term the feature exercises
    ─────────────────────────────────────────────────────────────────────────
    all distinguishing domain classes touching the feature

A class is *reachable* when at least one of the glossary terms naming it appears
in the feature's incidence. Coverage 1.0 means the glossary can already name
everything that structurally distinguishes the feature; the shortfall is the
lexicon gap the propose-terms channel (MetaCoding-5c5) should fill. Without the
file the metric is reported as ``n/a`` — the incidence and degrees stand alone.

Everything here is measurement, not verdict: this module only *reads* sealed
packs (``fixtures.jsonl`` + ``pack.seal.json`` presence is recorded, never
issued) and never contacts a source system.

Expected ``role-classes.jsonl`` row shape (one JSON object per line)::

    {"class_id": "...",            # stable id for the role class
     "kind": "domain",             # "domain" | "framework" (framework ignored)
     "features": ["log.input"],    # features the class touches
     "terms": ["yield_total"],     # glossary terms naming it ([] = unnamed)
     "distinguishing": true}       # optional; default true

Unknown extra keys are ignored so the role sweep can enrich rows later without
breaking this consumer. The actual ``ctkr role-gaps`` producer (MetaCoding-034)
speaks a superset dialect, accepted here as aliases:

* rows carry ``record_type`` — anything other than ``"role_class"`` (e.g. the
  trailing ``"summary"`` record) is skipped, not an error;
* ``tag`` maps to ``kind`` (``"framework-idiom"`` → ``"framework"``, anything
  else → as-is) when ``kind`` is absent;
* ``glossary_terms`` maps to ``terms`` when ``terms`` is absent.

Feature names on the two sides of the seam differ in qualification: packs name
features ``log.input`` while the role sweep, already scoped to one family,
says ``input``. A class feature *touches* a pack feature when they are equal
or the pack feature ends with ``"." + class_feature``.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# Degree fraction at (or above) which a term is classified SPINE.
DEFAULT_SPINE_THRESHOLD = 0.8

FIXTURES_FILENAME = "fixtures.jsonl"
SEAL_FILENAME = "pack.seal.json"
CONTRACT_FILENAME = "adapter_contract.json"


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TermEdge:
    """One edge of the bipartite feature ↔ term graph."""

    feature: str
    term: str
    role: str  # "assertion" | "action"
    count: int  # occurrences across the feature's (deduplicated) fixtures


@dataclass
class PackRecord:
    """One discovered fixtures.jsonl and what was read from it."""

    path: Path  # absolute path to fixtures.jsonl
    sealed: bool  # pack.seal.json present alongside
    contract_path: Path | None  # adapter_contract.json located for the pack
    adapter_name: str | None
    n_fixtures: int  # lines parsed
    n_new_fixtures: int  # fixtures not already seen (by fixture_id)
    features: tuple[str, ...]  # features contributed (post-dedup)


@dataclass
class FeatureProfile:
    """Per-feature aggregation."""

    feature: str
    n_fixtures: int = 0
    assertion_terms: dict[str, int] = field(default_factory=dict)
    action_terms: dict[str, int] = field(default_factory=dict)
    adapter_names: set[str] = field(default_factory=set)

    @property
    def terms(self) -> frozenset[str]:
        return frozenset(self.assertion_terms) | frozenset(self.action_terms)


@dataclass
class IncidenceGraph:
    features: list[str]
    edges: list[TermEdge]
    profiles: dict[str, FeatureProfile]
    packs: list[PackRecord]

    @property
    def terms(self) -> list[str]:
        return sorted({e.term for e in self.edges})


@dataclass(frozen=True)
class TermDegree:
    term: str
    degree: int  # distinct features exercising the term (any role)
    roles: tuple[str, ...]  # roles observed for the term, sorted
    classification: str  # "SPINE" | "SHARED" | "IDENTITY"
    features: tuple[str, ...]
    total_count: int


@dataclass(frozen=True)
class RoleClass:
    class_id: str
    kind: str
    features: tuple[str, ...]
    terms: tuple[str, ...]
    distinguishing: bool


@dataclass(frozen=True)
class FeatureCoverage:
    feature: str
    reachable: tuple[str, ...]  # class_ids named by a term the feature uses
    unreachable: tuple[str, ...]  # class_ids no exercised term names
    coverage: float | None  # None when the feature touches no classes


# --------------------------------------------------------------------------- #
# Discovery + load
# --------------------------------------------------------------------------- #


def discover_fixture_files(roots: list[Path]) -> list[Path]:
    """Every ``fixtures.jsonl`` under the given roots, sorted for determinism."""
    found: set[Path] = set()
    for root in roots:
        root = root.expanduser().resolve()
        if root.is_file() and root.name == FIXTURES_FILENAME:
            found.add(root)
            continue
        found.update(p.resolve() for p in root.rglob(FIXTURES_FILENAME))
    return sorted(found)


def _locate_contract(fixtures_path: Path) -> Path | None:
    """Find the pack's adapter_contract.json.

    Checked in order: the pack dir itself, the parent dir, and the wave-0 layout
    where ``<prefix>-observe/fixtures.jsonl`` pairs with a sibling
    ``<prefix>-adapter_contract.json`` in the parent dir.
    """
    pack_dir = fixtures_path.parent
    candidates = [pack_dir / CONTRACT_FILENAME, pack_dir.parent / CONTRACT_FILENAME]
    name = pack_dir.name
    if "-observe" in name:
        prefix = name.split("-observe", 1)[0].split("-")[0]
        candidates.append(pack_dir.parent / f"{prefix}-{CONTRACT_FILENAME}")
    for c in candidates:
        if c.exists():
            return c
    return None


def build_incidence(roots: list[Path]) -> IncidenceGraph:
    """Read every pack under ``roots`` and assemble the incidence graph.

    Fixtures are deduplicated globally by ``fixture_id`` so partial-run packs
    (a strict re-recording subset of a full pack) never double-count.
    """
    profiles: dict[str, FeatureProfile] = {}
    packs: list[PackRecord] = []
    seen_fixture_ids: set[str] = set()

    for fpath in discover_fixture_files(roots):
        sealed = (fpath.parent / SEAL_FILENAME).exists()
        contract_path = _locate_contract(fpath)
        adapter_name: str | None = None
        if contract_path is not None:
            try:
                adapter_name = json.loads(
                    contract_path.read_text(encoding="utf-8")
                ).get("adapter_name")
            except (json.JSONDecodeError, OSError):
                adapter_name = None

        n_fixtures = 0
        n_new = 0
        pack_features: set[str] = set()
        for line in fpath.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            fx = json.loads(line)
            n_fixtures += 1
            fid = fx.get("fixture_id")
            if fid is not None:
                if fid in seen_fixture_ids:
                    continue
                seen_fixture_ids.add(fid)
            n_new += 1
            feature = fx.get("feature") or fpath.parent.name
            pack_features.add(feature)
            prof = profiles.setdefault(feature, FeatureProfile(feature=feature))
            prof.n_fixtures += 1
            if adapter_name:
                prof.adapter_names.add(adapter_name)
            for step in fx.get("then", []):
                term = step.get("assert")
                if term:
                    prof.assertion_terms[term] = prof.assertion_terms.get(term, 0) + 1
            for step in fx.get("when", []):
                term = step.get("action")
                if term:
                    prof.action_terms[term] = prof.action_terms.get(term, 0) + 1

        packs.append(
            PackRecord(
                path=fpath,
                sealed=sealed,
                contract_path=contract_path,
                adapter_name=adapter_name,
                n_fixtures=n_fixtures,
                n_new_fixtures=n_new,
                features=tuple(sorted(pack_features)),
            )
        )

    edges: list[TermEdge] = []
    for feature in sorted(profiles):
        prof = profiles[feature]
        for term in sorted(prof.assertion_terms):
            edges.append(TermEdge(feature, term, "assertion", prof.assertion_terms[term]))
        for term in sorted(prof.action_terms):
            edges.append(TermEdge(feature, term, "action", prof.action_terms[term]))

    return IncidenceGraph(
        features=sorted(profiles), edges=edges, profiles=profiles, packs=packs
    )


# --------------------------------------------------------------------------- #
# Degree classification
# --------------------------------------------------------------------------- #


def classify_terms(
    graph: IncidenceGraph, spine_threshold: float = DEFAULT_SPINE_THRESHOLD
) -> list[TermDegree]:
    """Classify every term by cross-feature degree.

    IDENTITY (degree 1, only meaningful with ≥2 features) is checked before
    SPINE so a single-feature run does not report its whole vocabulary as spine.
    """
    n = len(graph.features)
    by_term_features: dict[str, set[str]] = defaultdict(set)
    by_term_roles: dict[str, set[str]] = defaultdict(set)
    by_term_count: dict[str, int] = defaultdict(int)
    for e in graph.edges:
        by_term_features[e.term].add(e.feature)
        by_term_roles[e.term].add(e.role)
        by_term_count[e.term] += e.count

    out: list[TermDegree] = []
    for term in sorted(by_term_features):
        degree = len(by_term_features[term])
        if n >= 2 and degree == 1:
            cls = "IDENTITY"
        elif n >= 2 and degree >= spine_threshold * n:
            cls = "SPINE"
        else:
            cls = "SHARED"
        out.append(
            TermDegree(
                term=term,
                degree=degree,
                roles=tuple(sorted(by_term_roles[term])),
                classification=cls,
                features=tuple(sorted(by_term_features[term])),
                total_count=by_term_count[term],
            )
        )
    out.sort(key=lambda t: (-t.degree, t.term))
    return out


# --------------------------------------------------------------------------- #
# Identity coverage (role-classes)
# --------------------------------------------------------------------------- #


def load_role_classes(path: Path) -> list[RoleClass]:
    """Parse a role-classes.jsonl (see module docstring for the row shape)."""
    classes: list[RoleClass] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        # role-gaps dialect: skip non-class records (e.g. the trailing summary).
        record_type = row.get("record_type")
        if record_type is not None and record_type != "role_class":
            continue
        if "class_id" not in row:
            raise ValueError(f"{path}:{i}: role-class row missing 'class_id'")
        kind = row.get("kind")
        if kind is None:
            tag = str(row.get("tag", "domain"))
            kind = "framework" if tag == "framework-idiom" else tag
        terms = row.get("terms")
        if terms is None:
            terms = row.get("glossary_terms", [])
        classes.append(
            RoleClass(
                class_id=str(row["class_id"]),
                kind=str(kind),
                features=tuple(row.get("features", [])),
                terms=tuple(terms),
                distinguishing=bool(row.get("distinguishing", True)),
            )
        )
    return classes


def _touches(pack_feature: str, class_features: tuple[str, ...]) -> bool:
    """True when a role class's feature list covers a pack feature.

    Packs qualify feature names by family (``log.input``); the role sweep,
    already scoped to one family, does not (``input``). Equal names match, and
    so does a pack feature ending with ``"." + class_feature``.
    """
    return any(
        pack_feature == f or pack_feature.endswith("." + f) for f in class_features
    )


def identity_coverage(
    graph: IncidenceGraph, classes: list[RoleClass]
) -> dict[str, FeatureCoverage]:
    """Per feature: distinguishing domain classes named by an exercised term / all.

    Framework-kind and non-distinguishing classes are excluded from both sides
    of the ratio. A class with no naming terms is by definition unreachable —
    that is precisely the lexicon gap this metric surfaces.
    """
    out: dict[str, FeatureCoverage] = {}
    for feature in graph.features:
        exercised = graph.profiles[feature].terms
        relevant = [
            c
            for c in classes
            if c.kind == "domain" and c.distinguishing and _touches(feature, c.features)
        ]
        reachable = tuple(
            sorted(c.class_id for c in relevant if exercised.intersection(c.terms))
        )
        unreachable = tuple(
            sorted(c.class_id for c in relevant if not exercised.intersection(c.terms))
        )
        cov = len(reachable) / len(relevant) if relevant else None
        out[feature] = FeatureCoverage(
            feature=feature, reachable=reachable, unreachable=unreachable, coverage=cov
        )
    return out


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #


def edges_jsonl(graph: IncidenceGraph) -> str:
    """The term-incidence.jsonl payload: one edge object per line."""
    return (
        "\n".join(
            json.dumps(
                {"feature": e.feature, "term": e.term, "role": e.role, "count": e.count},
                sort_keys=True,
            )
            for e in graph.edges
        )
        + "\n"
    )


def _display_path(p: Path | None, relative_to: Path | None) -> str | None:
    """Render a path relative to ``relative_to`` when it lies underneath it.

    Committed summary artifacts must not embed the absolute path of whatever
    checkout produced them; consumers get repo-relative paths instead.
    """
    if p is None:
        return None
    if relative_to is not None:
        try:
            return str(p.resolve().relative_to(relative_to.resolve()))
        except ValueError:
            pass
    return str(p)


def summary_payload(
    graph: IncidenceGraph,
    degrees: list[TermDegree],
    coverage: dict[str, FeatureCoverage] | None,
    spine_threshold: float,
    relative_to: Path | None = None,
) -> dict:
    """Machine-readable summary (the --json shape; regression-checkable)."""
    split = {"SPINE": 0, "SHARED": 0, "IDENTITY": 0}
    for d in degrees:
        split[d.classification] += 1
    per_feature = {}
    for feature in graph.features:
        prof = graph.profiles[feature]
        fc = coverage.get(feature) if coverage is not None else None
        per_feature[feature] = {
            "n_fixtures": prof.n_fixtures,
            "n_assertion_terms": len(prof.assertion_terms),
            "n_action_terms": len(prof.action_terms),
            "assertion_terms": dict(sorted(prof.assertion_terms.items())),
            "action_terms": dict(sorted(prof.action_terms.items())),
            "adapters": sorted(prof.adapter_names),
            "identity_terms": sorted(
                d.term
                for d in degrees
                if d.classification == "IDENTITY" and d.features == (feature,)
            ),
            "identity_coverage": (
                "n/a (no role classes supplied)"
                if coverage is None
                else {
                    "coverage": fc.coverage,
                    "reachable_classes": list(fc.reachable),
                    "unreachable_classes": list(fc.unreachable),
                }
            ),
        }
    return {
        "features": graph.features,
        "n_features": len(graph.features),
        "spine_threshold": spine_threshold,
        "classification_split": split,
        "terms": [
            {
                "term": d.term,
                "degree": d.degree,
                "roles": list(d.roles),
                "classification": d.classification,
                "features": list(d.features),
                "total_count": d.total_count,
            }
            for d in degrees
        ],
        "per_feature": per_feature,
        "packs": [
            {
                "path": _display_path(p.path, relative_to),
                "sealed": p.sealed,
                "adapter_contract": _display_path(p.contract_path, relative_to),
                "adapter_name": p.adapter_name,
                "n_fixtures": p.n_fixtures,
                "n_new_fixtures": p.n_new_fixtures,
                "features": list(p.features),
            }
            for p in graph.packs
        ],
    }
