"""Pydantic models for Layer-1 (mechanical) CTKR artifacts.

Every L1 technique writes its outputs under ``.metacoding/ctkr/`` against
the shapes defined here. Downstream code (L1 sibling techniques, L3
labelers, the CLI) imports from this module rather than redefining
shapes — this is the single source of truth.

Versioning rule: any field rename, type widen, or semantic change must
bump ``SCHEMA_VERSION`` and the per-artifact ``schema_version`` column.
Old artifacts can be re-validated against an older version of this
module by checking out the appropriate git revision.

The artifacts themselves live on disk as Parquet (columnar; fast for the
ML lane) plus a couple of opaque blob directories for index files that
aren't naturally tabular (FAISS / hnswlib).

Artifact directory layout::

    .metacoding/ctkr/
    ├── embeddings.parquet           # rows: EmbeddingRow
    ├── motifs.parquet               # rows: MotifRow
    ├── motif_instances.parquet      # rows: MotifInstanceRow
    ├── shape_pds.parquet            # rows: ShapePDRow (one per repo × dim)
    ├── wasserstein_h1.parquet       # rows: WassersteinH1Row (one per repo-pair)
    ├── centrality.parquet           # rows: CentralityRow
    ├── spectral_clusters.parquet    # rows: SpectralClusterRow
    ├── nn_index/
    │   ├── nn_index.bin             # FAISS/hnswlib serialized index
    │   └── nn_index.meta.json       # rows: NNIndexMeta (single object)
    └── manifest.json                # rows: ArtifactManifest (single object)

See ``docs/design/ctkr-artifacts.md`` for full prose; this docstring is the
short version.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, PositiveInt

SCHEMA_VERSION: int = 1

# Edge kinds mirror MetaCoding's TypeScript EdgeKind union (src/store/types.ts).
# Kept as a Literal so static type checkers + pydantic catch typos.
EdgeKind = Literal[
    "CALLS",
    "REFERENCES",
    "EXTENDS",
    "IMPLEMENTS",
    "OVERRIDES",
    "INJECTS",
    "CONTAINS",
    "IMPORTS",
    "ANNOTATES",
    "TYPE_OF",
]


# ----- Row-level models (one row per parquet record) -----


class EmbeddingRow(BaseModel):
    """One symbol's embedding vector.

    Produced by L1/C1 (node2vec / GraphSAGE). All vectors in a single
    ``embeddings.parquet`` MUST share a dimension; that dimension is
    recorded in ``ArtifactManifest.embedding_dim``.
    """

    symbol_id: str
    repo: str
    qualified_name: str
    vec: list[float]  # float32 in parquet; pydantic carries float
    schema_version: int = SCHEMA_VERSION


class MotifRow(BaseModel):
    """One frequent typed subgraph discovered by L1/C2.

    ``signature`` is the canonical serialization of the motif's graph
    structure (a typed-edge-list string, deterministic across runs of
    the miner). It is the join key into ``motif_instances.parquet``.
    """

    motif_id: str
    signature: str
    size_nodes: PositiveInt
    size_edges: NonNegativeInt
    support: PositiveInt  # how many instances exist corpus-wide
    repo_coverage: list[str]  # repos in which the motif appears at least once
    edge_kinds: list[EdgeKind]  # distinct edge kinds present in the motif
    schema_version: int = SCHEMA_VERSION


class MotifInstanceRow(BaseModel):
    """One concrete occurrence of a motif in the corpus.

    Multiple rows per ``motif_id``; links back to the originating
    symbol(s) so an evidence-fetcher (L3/F3) can pull snippets.
    """

    motif_id: str
    symbol_id: str  # the "anchor" symbol — usually the first node by signature order
    repo: str
    file: str
    line: PositiveInt
    schema_version: int = SCHEMA_VERSION


class ShapePDRow(BaseModel):
    """Persistent-homology shape signature for one (repo, homology-dim) pair.

    Produced by L1/S1. ``persistence_pairs`` is encoded as flat parallel
    lists rather than a list-of-tuples because Parquet's list<list<...>>
    support varies across readers.
    """

    repo: str
    dim: NonNegativeInt  # H_0, H_1, H_2 typically
    birth: list[float]
    death: list[float]
    schema_version: int = SCHEMA_VERSION


class HomProfileRow(BaseModel):
    """One symbol's hom-profile — raw integer edge counts by (kind, direction).

    Produced by L1 (``ctkr hom-profiles``, MetaCoding-23q.1). The vector
    is stored at **maximal precision** as unsigned integer counts (no
    L1-normalisation, no quantisation, no kinds_filter baked into the
    numbers). Per ``docs/notes/entropy-as-dial.md`` granularity is a
    caller-tunable knob, so downstream tools re-normalise / discretize
    at query time rather than the writer baking a choice into the bytes.

    Vector dimension is ``2 * len(EDGE_KINDS)`` from
    ``ctkr.graph_loader.EDGE_KINDS`` (currently 28). Ordering convention:
    for each ``ek in EDGE_KINDS``, the ``(ek, "in")`` slot precedes the
    ``(ek, "out")`` slot. The canonical ``_DIMS`` list in
    ``ctkr.hom_profiles`` is the single source of truth for the order.
    """

    symbol_id: str
    repo: str
    qualified_name: str
    profile_vec: list[NonNegativeInt]
    schema_version: int = SCHEMA_VERSION


class NNIndexMeta(BaseModel):
    """Metadata sidecar for the opaque ``nn_index/`` directory.

    The binary index itself (FAISS or hnswlib) is not a parquet table.
    This sidecar records what's inside so callers don't have to
    introspect the binary.
    """

    backend: Literal["faiss", "hnswlib"]
    metric: Literal["cosine", "l2", "ip"]
    embedding_dim: PositiveInt
    n_symbols: NonNegativeInt
    built_at: datetime
    embeddings_source: str = Field(
        description=(
            "Relative path to the embeddings.parquet this index was built from. "
            "Used to detect staleness when embeddings are regenerated."
        ),
    )
    schema_version: int = SCHEMA_VERSION


class CentralityRow(BaseModel):
    """Per-symbol centrality scores produced by L1/S2.

    All three measures are normalized to [0, 1] within the source graph.
    ``betweenness`` is approximate when computed with sampling
    (``k < |N|``) — recorded as the same column for consistency, with
    the sampling factor noted in :attr:`ArtifactManifest.notes`.
    """

    symbol_id: str
    repo: str
    qualified_name: str
    pagerank: float = Field(ge=0.0)
    betweenness: float = Field(ge=0.0)
    eigenvector: float = Field(ge=0.0)
    # Cut-vertex flag (MetaCoding subsystem-extraction §2.1). True when removing
    # this symbol disconnects the undirected collapse of its connected
    # component — the "real seam" signal the design's boundary detection uses.
    # Additive column (default False) so parquets written before it round-trip;
    # readers that predate it simply ignore the field.
    articulation: bool = False
    schema_version: int = SCHEMA_VERSION


class SubsystemRow(BaseModel):
    """One extracted subsystem — a full subcategory on a disjoint object set.

    Produced by ``ctkr subsystems`` (subsystem-extraction §2, Stage A —
    DECOMPOSE). One row per ``(run_config, subsystem_id)``. The partition is a
    consensus over a Louvain resolution sweep: ``persistence_score`` is the mean
    pairwise co-association of the subsystem's members across the sweep (1.0 =
    the members always co-cluster; low = a fragile grouping). ``config`` is the
    JSON blob of the partition parameters + runtime metadata so a re-cut is
    reproducible and the subsystem_id is verifiable.
    """

    subsystem_id: str  # blake3(repo + config + sorted-member digest)
    repo: str
    n_members: PositiveInt
    resolution: float  # the default resolution the emitted partition was cut at
    persistence_score: float = Field(ge=0.0, le=1.0)
    config: str  # JSON blob of the partition config + runtime metadata
    generated_at: str  # ISO 8601
    schema_version: int = SCHEMA_VERSION


class SubsystemMemberRow(BaseModel):
    """One symbol's membership in a subsystem (subsystem-extraction §2.4).

    One row per ``(subsystem_id, symbol_id)``. ``boundary_confidence`` ∈ [0,1]
    is how strongly the symbol belongs to its subsystem: the mean co-association
    (across the resolution sweep) with the other members of its assigned
    subsystem. 1.0 = interior; low = a boundary/judgment-call assignment a
    re-implementer must scrutinise. ``placement`` records whether the assignment
    came from structure (``"structural"`` — the symbol carries typed-edge
    signal) or from file locality (``"locality"`` — a zero-profile symbol placed
    by its CONTAINS/directory home, per §2.3, because structure could not place
    it).
    """

    subsystem_id: str  # FK → subsystems.parquet
    symbol_id: str
    repo: str
    qualified_name: str
    boundary_confidence: float = Field(ge=0.0, le=1.0)
    placement: Literal["structural", "locality"]
    schema_version: int = SCHEMA_VERSION


class InterfaceRow(BaseModel):
    """One cross-boundary contract morphism (subsystem-extraction §3, Stage B).

    A subsystem's interface contract is not written down anywhere — it *is* the
    set of morphisms crossing its boundary. One row per aggregated
    ``(subsystem_id, direction, internal_symbol_id, external_symbol_id,
    edge_kind)``:

    - ``direction="provides"`` — an external symbol references an internal one
      (the API surface); ``internal_symbol_id`` is the export, ``edge_kind`` its
      usage mode (``REFERENCES``/``CALLS`` in = invoked, ``IMPLEMENTS`` in =
      extension point, ``TYPE_OF``/``RETURNS_TYPE`` in = used as a type,
      ``CONSTRUCTS`` in = instantiated).
    - ``direction="consumes"`` — an internal symbol references an external one
      (the dependency surface); ``external_subsystem_id`` gives the
      subsystem-level topology (null = external package / unpartitioned).

    ``CONTAINS`` scaffolding is excluded (§6.1 tier-A). ``internal_export_*``
    rolls the (possibly nested) internal symbol up to its top-level declaration
    — the re-implementer's actual export surface — computed name-blind from the
    qualified-name path. The raw ``internal_symbol_id`` stays maximal-precision.
    """

    subsystem_id: str  # FK → subsystems.parquet (the subsystem this row is for)
    repo: str
    direction: Literal["provides", "consumes"]
    edge_kind: str  # the crossing morphism's kind (usage mode)
    edge_count: NonNegativeInt  # summed multiplicity of this crossing
    internal_symbol_id: str  # the member of this subsystem
    internal_qualified_name: str
    internal_export_symbol_id: str | None  # top-level owner (roll-up); None if unresolved
    internal_export_qualified_name: str
    external_symbol_id: str  # the symbol on the other side of the boundary
    external_qualified_name: str
    external_subsystem_id: str | None  # its subsystem; None = external/unpartitioned
    schema_version: int = SCHEMA_VERSION


class DataShapeRow(BaseModel):
    """One field of a type in the boundary/internal data vocabulary (§3).

    One row per ``(subsystem_id, type_symbol_id, field)``. A type is a
    **boundary** shape (``boundary=True``) when it crosses the interface (a
    port must reproduce it semantically) or **internal** otherwise (a port may
    restructure it — accidental-unless-persistent, §6.1). ``read_by_*`` /
    ``written_by_*`` record per-field flow direction: a field written only by
    the subsystem and read externally is an *output* contract; written
    externally and read internally is an *input*. Fieldless boundary types get a
    single row with null ``field_*`` so the type is still recorded.

    Recovered from ``READS_FIELD`` / ``WRITES_FIELD`` (flow), ``TYPE_OF`` (a
    field's declared type), ``CONSTRUCTS`` (``constructed_by``) — the
    MetaCoding-e54/3s5/9le data alphabet. Coverage is per-lane uneven; the run's
    ``ArtifactManifest.alphabet_coverage`` note says whether a thin shapes
    section is an extractor gap rather than an absent data model.
    """

    subsystem_id: str  # FK → subsystems.parquet
    repo: str
    type_symbol_id: str  # the type (class / interface / type_alias / struct / …)
    type_qualified_name: str
    boundary: bool  # crosses the interface (True) vs private/internal (False)
    field_symbol_id: str | None  # null for a fieldless-type summary row
    field_name: str | None
    field_type: str | None  # qualified name of the field's declared type, if known
    read_by_internal: bool
    read_by_external: bool
    written_by_internal: bool
    written_by_external: bool
    constructed_by: list[str]  # qualified names of symbols that CONSTRUCT the type
    schema_version: int = SCHEMA_VERSION


class PresentationRow(BaseModel):
    """One role class of a subsystem's presentation — a generator (§4.1, T3).

    The role inventory quotients a subsystem's members by hom-profile
    equivalence (**depth 1** — the role-*surfacing* dial per MetaCoding-4ty: at
    depth 1 you *want* the automorphism orbits, so 14 concrete validators
    collapse to one ``Validator`` generator). One row per
    ``(subsystem_id, view, role_id)``.

    Two views are always emitted (the design's "orbit-exact vs
    similarity-cluster both emitted"):

    - ``view="orbit"`` — the **conservative** quotient: members with a
      *byte-identical* depth-1 profile vector share a class (exact
      Weisfeiler-Leman orbits, the WL classes from the 2-hop work). No
      threshold; ``granularity="exact"``; ``persistence=1.0`` (exact classes
      are definitional, not swept).
    - ``view="similarity"`` — the **working** quotient: cosine-threshold
      connected-components over the max-precision profile vectors at a default
      threshold, with a threshold sweep supplying ``persistence`` (mean
      within-class co-association across the sweep, exactly the subsystems.py
      robustness story). ``granularity`` records the default threshold.

    ``role_id`` is content-addressed (blake3 of subsystem_id + view + config +
    sorted-member digest) so re-runs over the same partition are byte-identical
    and ``generated_at`` never enters the id. ``profile_centroid`` is the mean
    depth-1 profile of the members (the role's hom-profile centroid);
    ``exemplar_symbol_id`` is the member nearest that centroid (max cosine;
    ties by min symbol_id) — every role has an exemplar (a re-implementer needs
    the *Validator* role + one concrete instance, not all 14). Zero-profile
    (edgeless) members share a single "isolated" class per view — the honest
    structural floor (§2.3): structure cannot discriminate them, so they are
    not exploded into singletons.

    ``interface_participation`` is the subset of ``{"provides","consumes"}`` any
    member of the class occupies in the subsystem's interface (join against
    ``interfaces.parquet``, T2). The re-implementer's first question about any
    role is whether it is public; empty when interfaces were not extracted or
    the class is purely internal.
    """

    subsystem_id: str  # FK → subsystems.parquet
    repo: str
    role_id: str  # blake3(subsystem_id + view + config + sorted-member digest)
    view: Literal["orbit", "similarity"]
    granularity: str  # "exact" (orbit) or the default cosine threshold (similarity)
    cardinality: PositiveInt  # number of members in the class
    members: list[str]  # member symbol_ids, sorted
    exemplar_symbol_id: str  # member nearest the centroid (max cosine; ties min id)
    exemplar_qualified_name: str
    profile_centroid: list[float]  # mean depth-1 profile vector of the members
    profile_depth: int  # 1 (role-surfacing dial); recorded for provenance
    interface_participation: list[str]  # subset of {"provides","consumes"}; may be empty
    persistence: float = Field(ge=0.0, le=1.0)  # sweep co-association; 1.0 for orbit
    config: str  # JSON blob of the run config + runtime metadata
    generated_at: str  # ISO 8601
    schema_version: int = SCHEMA_VERSION


class OperadRow(BaseModel):
    """One recovered composition operation of a subsystem — a relation (§4.3, T4).

    Phase 2d operad recovery, scoped single-repo and per-subsystem. The role
    inventory (``presentations.parquet``, T3) gives a subsystem's *generators*
    (role classes); this artifact gives its *relations* — the composition
    algebra a re-implementer most needs and most lacks: not the pieces, but how
    they combine. One row per ``(subsystem_id, view, operation_id)``.

    Operations are mined by projecting the subsystem's actual typed call/
    reference paths onto role classes (``parseConfig → validateSchema →
    applyDefaults`` becomes the role-path ``Loader ∘ Validator ∘ Defaulter``)
    and keeping the role-paths that recur with ``support ≥ k``. Three
    ``op_kind`` families:

    - ``"path"`` — a recurring linear role-path (sequential composition). The
      terminal role is ``output_role``; the preceding roles are ``input_roles``
      (order preserved); ``arity`` = number of composition steps = len(path)-1.
      An arity-1 path is a single generator ``R_i → R_j``.
    - ``"fan_in"`` — an n-ary combination: a target role invoked/produced by
      combining ``arity`` distinct source roles (the multi-fan-in / wiring-
      diagram reading, Fong & Spivak ch. 6). ``input_roles`` is the sorted set
      of source roles; ``output_role`` the target; ``arity`` = |input_roles|.
    - ``"non_operadic"`` — a recorded *law violation*, not a valid operation
      (ct-pipeline §2d: "non-operadic composition is interesting in itself" —
      recorded, never discarded). ``violation_kind`` says which law broke:
      ``"missing_composite"`` (two generators ``R_i→R_j`` and ``R_j→R_k`` both
      recur, so they compose at role level, but the predicted 2-step composite
      ``R_i→R_j→R_k`` is never actually observed — role-composability without
      instance-composition) or ``"back_call_cycle"`` (both ``R_i→R_j`` and
      ``R_j→R_i`` recur — an observed 2-cycle, the "Worker never calls
      Orchestrator back except through Callback" non-law).

    ``support`` is the number of concrete instances backing the operation.
    ``edge_kinds`` are the distinct typed-edge kinds along the composition.
    ``exemplar_paths`` are up to a few concrete qualified-name paths (``a -> b
    -> c``) so a re-implementer sees the operation, not just its role types.

    ``is_boundary_op`` (the T4 boundary flag) is True when any of the
    operation's roles participates in the subsystem's interface (a role with
    non-empty ``interface_participation`` in ``presentations.parquet``, which in
    turn joins ``interfaces.parquet``, T2). Boundary operations are the
    subsystem's **protocol** — the order-of-operations contract external callers
    depend on (init-before-use, acquire-then-release), the composition laws a
    port breaks first and silently.

    ``associative_observed`` records the empirical associativity/closure law for
    ``path`` ops of arity ≥ 2: True when every composable generator pair whose
    middle role is shared realizes its predicted 2-step composite as an observed
    operation. ``law_violations`` counts the composable generator pairs at this
    operation whose composite is *missing* (0 for a fully-closed op). For
    ``fan_in`` ops the law fields are trivially satisfied
    (``associative_observed=True``, ``law_violations=0``); for ``non_operadic``
    rows ``associative_observed=False`` and ``law_violations=1``.

    ``view`` selects which role quotient (``"orbit"`` = exact-profile WL classes,
    conservative; ``"similarity"`` = cosine-threshold working classes) the
    role-paths were projected through — the same dial as ``presentations.parquet``.
    ``invariance_tier`` is ``"I"`` (composition laws over roles are tier-I per
    §6.1 — a port must preserve them). ``operation_id`` is content-addressed
    (blake3 of subsystem_id + view + op_kind + role signature + config) so
    re-runs over the same partition + roles are byte-identical and
    ``generated_at`` never enters the id.
    """

    subsystem_id: str  # FK → subsystems.parquet
    repo: str
    operation_id: str  # blake3(subsystem_id + view + op_kind + role signature + config)
    view: Literal["orbit", "similarity"]  # which role quotient the paths were projected through
    op_kind: Literal["path", "fan_in", "non_operadic"]
    arity: NonNegativeInt  # number of input roles (composition steps / fan-in width)
    input_roles: list[str]  # role_ids feeding the operation (ordered for path, sorted for fan_in)
    output_role: str  # role_id of the terminal / target
    edge_kinds: list[str]  # distinct typed-edge kinds along the composition
    support: NonNegativeInt  # number of concrete instances backing the operation
    is_boundary_op: bool  # any role participates in the subsystem's interface (a protocol op)
    associative_observed: bool  # empirical associativity/closure law (path arity≥2); True if n/a
    law_violations: NonNegativeInt  # count of composable generator pairs whose composite is missing
    violation_kind: str  # "" for real ops; "missing_composite" | "back_call_cycle" for non_operadic
    exemplar_paths: list[str]  # up to a few concrete qualified-name paths ("a -> b -> c")
    invariance_tier: str  # "I" — composition laws over roles are port-invariant (§6.1)
    config: str  # JSON blob of the run config + runtime metadata
    generated_at: str  # ISO 8601
    schema_version: int = SCHEMA_VERSION


class IntentionSignalRow(BaseModel):
    """One harvested intention indicator (ct-intention-extraction.md §9.1, T5a).

    The mechanical harvest's ground truth: one row per ``(element_id,
    indicator_kind, content, file, line_range)``. Everything downstream (T5b
    synthesis, the port brief) cites ``signal_id``. Produced deterministically
    from the exported graph + source-text slices + FTS — no LM (§8 "harvest
    free"). ``indicator_kind`` is the §1 catalog code (S1–S4, A1–A6, B1/B3);
    ``tier`` is its rank (S/A/B/C); ``portability_tier`` is the §7.2 intent tag
    (``I`` universal, ``N`` convention-encoded, ``A`` idiom-specific).

    ``element_kind`` says which frozen structural element (§2) the signal
    attaches to (``interface-export`` | ``role-class`` | ``data-shape`` |
    ``subsystem`` | ``symbol``); ``element_id`` is that element's id (a
    symbol_id, role_id, or subsystem_id). ``file``/``line_range`` point at the
    signal's *source* provenance, which may differ from the element (a test that
    links an export lives in the test file). ``line_range`` is ``""`` |
    ``"L"`` | ``"L1-L2"``. ``signal_id`` is content-addressed (blake3 of
    element_id + indicator_kind + content + file + line_range) so re-runs over
    the same inputs are byte-identical and ``generated_at`` never enters a row.
    """

    signal_id: str  # blake3(element_id + indicator_kind + content + file + line_range)
    element_id: str
    element_kind: str  # interface-export | role-class | data-shape | subsystem | symbol
    indicator_kind: str  # §1 catalog code: S1..S4 | A1..A6 | B1 | B3
    tier: str  # S | A | B | C (the §1 rank of indicator_kind)
    content: str  # the harvested text (name, docstring, error string, marker, …)
    file: str  # repo-relative source of the signal (provenance)
    line_range: str  # "" | "L" | "L1-L2"
    portability_tier: str  # §7.2 intent tag: I (universal) | N (convention) | A (idiom)
    schema_version: int = SCHEMA_VERSION


class IntentionLoadRow(BaseModel):
    """The §5 intention-load indicator for one structural element (T5a).

    Where does structure alone underdetermine the spec? Two orthogonal,
    mechanical, dial-parameterized scores (§5.2): ``structural_determinacy`` D ∈
    [0,1] (how much the shape pins the behavior) and ``intention_richness`` R ∈
    [0,1] (how much tier-weighted signal the harvest found). ``load_class`` is
    the §5.1 triage: ``structure-clear`` (implement the shape, skim the intent),
    ``intention-critical`` (the names/tests ARE the spec — read the evidence), or
    ``ambiguous`` (flag for human review). One override (§5.2): an unresolved
    port-critical conflict forces the element out of ``structure-clear``.

    ``drivers`` lists the sub-signals that produced the scores (§5.3 — ship the
    drivers so the number is auditable; D/R are triage heuristics calibrated by
    ports, not theorems). ``port_critical_conflict`` records whether the override
    fired. Deterministic; no ``generated_at`` in the row.
    """

    element_id: str
    element_kind: str  # interface-export | role-class
    structural_determinacy: float = Field(ge=0.0, le=1.0)
    intention_richness: float = Field(ge=0.0, le=1.0)
    load_class: Literal["structure-clear", "intention-critical", "ambiguous"]
    port_critical_conflict: bool
    drivers: list[str]
    schema_version: int = SCHEMA_VERSION


class IntentionConflictRow(BaseModel):
    """One mechanical structure↔intention conflict candidate (§6.1 stage 1, T5a).

    A curated, high-precision detector (``data/conflict_detectors.json``) found a
    strong intention signal (a name, docstring claim, or decorator) contradicting
    a tier-I structural fact (crossing edges, field-flow, caller counts).
    ``severity`` is ``port-critical`` (the claim contradicts observed behavior an
    external caller depends on — the port must keep the ugly truth, §6.2) or
    ``advisory`` (softer: deprecated-but-used, stale docs). These are
    *candidates* for T5b's LM adjudication (§6.1 stage 2) to confirm — the table
    proposes, the strong model disposes; the mechanical layer never emits a final
    verdict. ``claim`` is what the intention asserts; ``structural_fact`` is what
    the graph observes. ``conflict_id`` is content-addressed for byte-identical
    re-runs.
    """

    conflict_id: str  # blake3(element_id + detector_id + claim + structural_fact)
    element_id: str
    element_kind: str
    detector_id: str  # FK → conflict_detectors.json entry id
    severity: Literal["port-critical", "advisory"]
    claim: str  # what the name/doc/decorator asserts
    structural_fact: str  # what the graph observes
    file: str
    line_range: str
    schema_version: int = SCHEMA_VERSION


class SpectralClusterRow(BaseModel):
    """Per-symbol cluster assignment produced by L1/S2.

    Clusters are scoped to one repo at a time — ``cluster_id`` is only
    meaningful within ``repo``. The intent is "modules-as-emergent": a
    sub-system that the symbol's structural neighbors form, regardless
    of declared package boundaries.
    """

    symbol_id: str
    repo: str
    qualified_name: str
    cluster_id: NonNegativeInt
    cluster_size: PositiveInt
    schema_version: int = SCHEMA_VERSION


class WassersteinH1Row(BaseModel):
    """One pairwise topological-distance entry between two repos.

    Produced by ``ctkr shape`` (L1/S1) alongside ``shape_pds.parquet``.
    Despite the file name, the underlying metric is the **bottleneck
    distance** (L∞-Wasserstein) between H₁ persistence diagrams —
    chosen over full p-Wasserstein because it ships with the lighter
    ``topo`` extra (gudhi, no ``pot`` dependency). The file name is
    retained for historical / external-caller compatibility.

    Stored upper-triangle only (``repo_a < repo_b`` lexicographically);
    the metric is symmetric, so the lower triangle is implied.
    """

    repo_a: str
    repo_b: str
    distance: float = Field(ge=0.0)
    schema_version: int = SCHEMA_VERSION


class FunctorRow(BaseModel):
    """One discovered (approximate) functor ``F : C_src → C_dst`` — Phase 2b.

    Produced by the TS functor-discovery runner (``src/ctkr/functorRunner.ts``,
    MetaCoding §6 Task 3). One row per ``(repo_src, repo_dst, config)`` — a
    *directed* pair, so both directions of a repo pair appear as separate rows.
    Python never writes these (TS owns Phase 2 per MetaCoding-p4b); this model
    is the canonical schema authority so the codegen'd TS mirror and any
    Python-side L3/analysis readers agree on shape and column order.

    Null semantics (§1.3): metrics with no evidence are stored as the sentinel
    ``-1.0`` (a real float on disk — Parquet floats are not nullable in the
    ``-1`` convention this artifact set uses) and surfaced as ``null`` by
    consumers. ``fidelity`` is ``-1`` when ``n_edges_internal == 0`` (an
    edgeless domain preserves nothing and proves nothing — it must fail any
    ``min_fidelity > 0`` filter, NOT read as perfect 1.0). ``path_fidelity_2``
    is ``-1`` when the 2-path composition diagnostic was not computed.
    ``cycle_consistency`` is ``-1`` when the reverse-direction functor was not
    computed under the same config.
    """

    functor_id: str  # content-addressed: hash of (repo_src, repo_dst, config, mapping)
    repo_src: str  # source repo (domain category C_A)
    repo_dst: str  # target repo (codomain C_B)
    n_objects_src: NonNegativeInt  # |O(C_A)| — denominator of coverage
    n_mapped: NonNegativeInt  # |dom(F)|
    coverage: float  # n_mapped / n_objects_src, in [0, 1]
    fidelity: float  # n_edges_preserved / n_edges_internal; -1 when internal == 0
    n_edges_internal: NonNegativeInt  # typed edges of C_A with both ends in dom(F)
    n_edges_preserved: NonNegativeInt  # of those, edges with a same-kind witness in C_B
    path_fidelity_2: float  # sampled 2-path composition diagnostic; -1 if not computed
    cycle_consistency: float  # fraction of s with G(F(s)) = s; -1 if reverse not computed
    # Fraction of committed mappings that are coin-flip ties (margin < delta_amb;
    # MetaCoding-265). High (~0.9 on real name-blind typed-edge profiles) means
    # the per-symbol correspondence is an AGGREGATE-ONLY signal: coverage/
    # fidelity/cycle_consistency stay meaningful, individual mappings do not.
    # Additive column (default 0.0) so functors written before it round-trip.
    ambiguity_mass: float = 0.0
    config: str  # JSON blob of the search config + runtime metadata
    generated_at: str  # ISO 8601
    schema_version: int = SCHEMA_VERSION


class FunctorEdgeRow(BaseModel):
    """One object↦object correspondence — a weighted meta-graph edge (Phase 2c).

    Produced alongside ``FunctorRow`` by the functor-discovery runner. This is
    the Phase 2c meta-graph edge stream (MetaCoding-at0): Louvain's nodes are
    ``(repo, symbol_id)`` across the corpus and each row here is one weighted
    meta-edge. ``functor_id`` is the FK back into ``functors.parquet``.

    Null semantics: ``pair_fidelity`` is ``-1`` when the source has no internal
    incident edges (no structural evidence — consumers must NOT read this as
    1.0). ``margin`` is the σ gap to the best unaccepted alternative for this
    source; low margin = the assignment was a near-coin-flip among lookalikes
    (expected often under BORDERLINE seeds).
    """

    functor_id: str  # FK into functors.parquet
    src_symbol_id: str  # matches Symbol.id in the source repo
    src_repo: str  # denormalized (Louvain builds the meta-graph without a join)
    src_qualified_name: str  # denormalized for human-readable output
    dst_symbol_id: str
    dst_repo: str
    dst_qualified_name: str
    similarity: float  # converged (pre-normalization) propagation score σ
    margin: float  # σ gap to best unaccepted alternative for this source
    # Coin-flip flag (MetaCoding-265): the accepted candidate was a near-tie among
    # structural lookalikes (margin < delta_amb, or < commit_min_margin when the
    # honest-acceptance gate is armed). The row is KEPT (never dropped) so a
    # consumer can see and discount the per-symbol claim. Additive column
    # (default False) so edges written before it round-trip.
    is_ambiguous: bool = False
    pair_fidelity: float  # preserved/total internal incident edges; -1 = no evidence
    n_edges_incident: NonNegativeInt  # internal typed edges incident to src (evidence mass)
    n_edges_preserved: NonNegativeInt  # of those, preserved
    schema_version: int = SCHEMA_VERSION


class ArtifactManifest(BaseModel):
    """Top-level pointer file for the ``.metacoding/ctkr/`` directory.

    Lives at ``.metacoding/ctkr/manifest.json``. Records which artifacts
    are present, when they were generated, and what version of this
    schema they were validated against. Cheap to read; tooling should
    consult it before assuming an artifact exists.
    """

    # ``extra="allow"`` so a manifest written by a future ctkr schema
    # version (with unknown fields) round-trips through an older writer
    # without those fields being silently dropped. Multiple writers
    # share this file, so forward-compat preservation matters even
    # within a single schema version.
    model_config = ConfigDict(extra="allow")

    schema_version: int = SCHEMA_VERSION
    generated_at: datetime
    metacoding_data_dir: str  # absolute path to the .metacoding/ that fed us
    embeddings: bool = False
    motifs: bool = False
    motif_instances: bool = False
    shape_pds: bool = False
    wasserstein_h1: bool = False
    centrality: bool = False
    spectral_clusters: bool = False
    nn_index: bool = False
    hom_profiles: bool = False
    # Subsystem-extraction Stage A artifacts (subsystem-extraction §2.4, T1).
    subsystems: bool = False
    subsystem_members: bool = False
    # Subsystem-extraction Stage B artifacts (subsystem-extraction §3, T2).
    interfaces: bool = False
    data_shapes: bool = False
    # Subsystem-extraction Stage C role inventory (subsystem-extraction §4.1, T3).
    presentations: bool = False
    # Subsystem-extraction Stage C composition laws / operad recovery (§4.3, T4).
    operads: bool = False
    # Subsystem-extraction Stage D+E — the fused per-subsystem spec deck
    # (subsystem_cards.jsonl, §8.1, T5). The JSONL cards are derived (regenerable
    # from the Parquet artifacts above + an L3 labeler run); this flag records
    # that a deck was generated for this data dir.
    subsystem_cards: bool = False
    # Intention-extraction Stage T5a — the LM-free mechanical harvest
    # (ct-intention-extraction.md §9.2): the harvested signals, the §5 load
    # scores, and the §6.1 mechanical conflict candidates.
    intention_signals: bool = False
    intention_load: bool = False
    intention_conflicts: bool = False
    # Phase 2b functor-discovery artifacts (MetaCoding §6 Task 3).
    functors: bool = False
    functor_edges: bool = False
    embedding_dim: int | None = None
    profile_vec_dim: int | None = None
    # Per-edge-kind weights applied to hom-profile dimensions (MetaCoding-23q.1
    # weighting variant). None/absent means raw UInt32 counts (the maximal-
    # precision default). A non-empty mapping means the profile_vec was scaled
    # by these multipliers and is therefore a Float64 variant, NOT raw counts.
    kind_weights: dict[str, float] | None = None
    # Neighborhood depth of the hom-profile artifact. 1 (default) = raw
    # per-symbol typed-edge counts; 2 = one Weisfeiler-Leman refinement
    # round (self ++ per-(kind,dir)-block neighbor-mean). None on manifests
    # written before this field existed (treat as 1).
    profile_depth: int | None = None
    n_symbols: NonNegativeInt = 0
    n_motifs: NonNegativeInt = 0
    n_motif_instances: NonNegativeInt = 0
    n_hom_profiles: NonNegativeInt = 0
    n_functors: NonNegativeInt = 0
    n_functor_edges: NonNegativeInt = 0
    n_subsystems: NonNegativeInt = 0
    n_interfaces: NonNegativeInt = 0
    n_data_shapes: NonNegativeInt = 0
    # Intention-harvest row counts (T5a). Per-indicator / per-portability splits
    # live in the run's stderr/JSON summary, not the manifest.
    n_intention_signals: NonNegativeInt = 0
    n_intention_load: NonNegativeInt = 0
    n_intention_conflicts: NonNegativeInt = 0
    # Role-inventory row count (both views summed; §4.1 T3). Per-view split +
    # compression ratio live in the run's stderr/JSON summary, not the manifest.
    n_presentations: NonNegativeInt = 0
    # Operad row count (all op_kinds + views summed; §4.3 T4). Per-kind split +
    # boundary/violation counts live in the run's stderr/JSON summary.
    n_operads: NonNegativeInt = 0
    # Subsystem-card (spec deck) count — one card per subsystem (§8.1, T5).
    n_subsystem_cards: NonNegativeInt = 0
    # Per-repo-lane data-alphabet coverage note (subsystem-extraction §3): which
    # data-edge kinds are present + the scip/tree-sitter source mix, so a thin
    # data_shapes section reads as an extractor gap, not an absent data model.
    alphabet_coverage: dict[str, dict] | None = None
    notes: str | None = None


# ----- Parquet column orderings -----
# Parquet doesn't care about column order, but downstream tooling (e.g.
# `duckdb` ad-hoc queries) reads more nicely with a stable layout.
# Tests pin against these so accidental field reorderings fail loudly.

EMBEDDINGS_COLUMNS: tuple[str, ...] = (
    "symbol_id",
    "repo",
    "qualified_name",
    "vec",
    "schema_version",
)

MOTIFS_COLUMNS: tuple[str, ...] = (
    "motif_id",
    "signature",
    "size_nodes",
    "size_edges",
    "support",
    "repo_coverage",
    "edge_kinds",
    "schema_version",
)

MOTIF_INSTANCES_COLUMNS: tuple[str, ...] = (
    "motif_id",
    "symbol_id",
    "repo",
    "file",
    "line",
    "schema_version",
)

SHAPE_PDS_COLUMNS: tuple[str, ...] = (
    "repo",
    "dim",
    "birth",
    "death",
    "schema_version",
)

CENTRALITY_COLUMNS: tuple[str, ...] = (
    "symbol_id",
    "repo",
    "qualified_name",
    "pagerank",
    "betweenness",
    "eigenvector",
    "articulation",
    "schema_version",
)

SUBSYSTEMS_COLUMNS: tuple[str, ...] = (
    "subsystem_id",
    "repo",
    "n_members",
    "resolution",
    "persistence_score",
    "config",
    "generated_at",
    "schema_version",
)

SUBSYSTEM_MEMBERS_COLUMNS: tuple[str, ...] = (
    "subsystem_id",
    "symbol_id",
    "repo",
    "qualified_name",
    "boundary_confidence",
    "placement",
    "schema_version",
)

INTERFACES_COLUMNS: tuple[str, ...] = (
    "subsystem_id",
    "repo",
    "direction",
    "edge_kind",
    "edge_count",
    "internal_symbol_id",
    "internal_qualified_name",
    "internal_export_symbol_id",
    "internal_export_qualified_name",
    "external_symbol_id",
    "external_qualified_name",
    "external_subsystem_id",
    "schema_version",
)

DATA_SHAPES_COLUMNS: tuple[str, ...] = (
    "subsystem_id",
    "repo",
    "type_symbol_id",
    "type_qualified_name",
    "boundary",
    "field_symbol_id",
    "field_name",
    "field_type",
    "read_by_internal",
    "read_by_external",
    "written_by_internal",
    "written_by_external",
    "constructed_by",
    "schema_version",
)

PRESENTATIONS_COLUMNS: tuple[str, ...] = (
    "subsystem_id",
    "repo",
    "role_id",
    "view",
    "granularity",
    "cardinality",
    "members",
    "exemplar_symbol_id",
    "exemplar_qualified_name",
    "profile_centroid",
    "profile_depth",
    "interface_participation",
    "persistence",
    "config",
    "generated_at",
    "schema_version",
)

OPERADS_COLUMNS: tuple[str, ...] = (
    "subsystem_id",
    "repo",
    "operation_id",
    "view",
    "op_kind",
    "arity",
    "input_roles",
    "output_role",
    "edge_kinds",
    "support",
    "is_boundary_op",
    "associative_observed",
    "law_violations",
    "violation_kind",
    "exemplar_paths",
    "invariance_tier",
    "config",
    "generated_at",
    "schema_version",
)

INTENTION_SIGNALS_COLUMNS: tuple[str, ...] = (
    "signal_id",
    "element_id",
    "element_kind",
    "indicator_kind",
    "tier",
    "content",
    "file",
    "line_range",
    "portability_tier",
    "schema_version",
)

INTENTION_LOAD_COLUMNS: tuple[str, ...] = (
    "element_id",
    "element_kind",
    "structural_determinacy",
    "intention_richness",
    "load_class",
    "port_critical_conflict",
    "drivers",
    "schema_version",
)

INTENTION_CONFLICTS_COLUMNS: tuple[str, ...] = (
    "conflict_id",
    "element_id",
    "element_kind",
    "detector_id",
    "severity",
    "claim",
    "structural_fact",
    "file",
    "line_range",
    "schema_version",
)

SPECTRAL_CLUSTERS_COLUMNS: tuple[str, ...] = (
    "symbol_id",
    "repo",
    "qualified_name",
    "cluster_id",
    "cluster_size",
    "schema_version",
)

WASSERSTEIN_H1_COLUMNS: tuple[str, ...] = (
    "repo_a",
    "repo_b",
    "distance",
    "schema_version",
)

HOM_PROFILES_COLUMNS: tuple[str, ...] = (
    "symbol_id",
    "repo",
    "qualified_name",
    "profile_vec",
    "schema_version",
)

FUNCTORS_COLUMNS: tuple[str, ...] = (
    "functor_id",
    "repo_src",
    "repo_dst",
    "n_objects_src",
    "n_mapped",
    "coverage",
    "fidelity",
    "n_edges_internal",
    "n_edges_preserved",
    "path_fidelity_2",
    "cycle_consistency",
    "ambiguity_mass",
    "config",
    "generated_at",
    "schema_version",
)

FUNCTOR_EDGES_COLUMNS: tuple[str, ...] = (
    "functor_id",
    "src_symbol_id",
    "src_repo",
    "src_qualified_name",
    "dst_symbol_id",
    "dst_repo",
    "dst_qualified_name",
    "similarity",
    "margin",
    "is_ambiguous",
    "pair_fidelity",
    "n_edges_incident",
    "n_edges_preserved",
    "schema_version",
)


# ----- Drupal declarative-config intention lane (MetaCoding-77x, port-loop
# Phase 0). Appended additively at the end to minimise merge conflict with the
# concurrently-edited structural lane above. -----


class FeatureRow(BaseModel):
    """One feature of the D1 Feature Inventory (decomposition-schema.md §2).

    Produced by the Drupal declarative lane (``ctkr drupal-harvest``), one row
    per module (**module ≈ feature**; §11): the module's ``.info.yml`` gives the
    label + description and — for free — the feature-level dependency graph
    (``depends_on``); routing / permission YAML give the counts; config/install
    filenames give the owned config entity types. ``source_basis`` is the honesty
    gauge: ``"declarative"`` when read from a manifest (the strong case),
    ``"structural"`` when proposed from subsystem boundaries (lower confidence).

    ``feature_id`` is content-addressed (blake3 of repo + module machine name) so
    re-runs over the same tree are byte-identical and no timestamp enters a row.
    ``subsystem_ids`` / ``interface_refs`` are the M:N joins into the structural
    lane (empty here — this lane runs without the Louvain partition; a later join
    populates them). ``member_globs`` are the module-subtree path globs a port
    uses to scope a feature's files.
    """

    feature_id: str  # blake3(repo, module machine name)
    repo: str
    name: str  # module machine name (declarative key), e.g. farm_harvest
    label: str  # human name from .info.yml `name`
    description: str  # .info.yml `description` — the one-line capability statement
    source_basis: Literal["declarative", "structural"]
    declarative_ref: str  # repo-relative path to the .info.yml (or "")
    package: str | None  # .info.yml `package` grouping, if any
    core_requirement: str | None  # .info.yml `core_version_requirement`, if any
    depends_on: list[str]  # feature_ids of in-corpus module dependencies
    config_entity_types: list[str]  # config entity types the module owns (asset.type …)
    routes_count: NonNegativeInt  # rows in the module's *.routing.yml
    permissions_count: NonNegativeInt  # rows in the module's *.permissions.yml
    member_globs: list[str]  # module-subtree path globs (e.g. modules/log/harvest/**)
    schema_version: int = SCHEMA_VERSION


class ConfigShapeRow(BaseModel):
    """One config-entity type or field, from Drupal ``config/schema`` (D3-style).

    Produced by the Drupal declarative lane, the data-shape analogue for
    *declarative* config entities: read from ``config/schema/*.schema.yml``
    mapping definitions rather than the structural ``READS_FIELD``/``WRITES_FIELD``
    edges (which this lane does not have). One row per ``(config_type,
    field_name)``; a ``field_name is None`` row is the type-summary. ``config_type``
    is the schema key (e.g. ``asset.type.*``); ``entity_kind`` is the schema
    ``type:`` (``config_entity`` / ``mapping`` / …); ``field_type`` is the Drupal
    typed-data type (``string`` / ``label`` / ``sequence`` / ``boolean`` / …).
    Keyed to the owning ``module`` (nearest ancestor ``.info.yml``). Content-
    addressed ``shape_id`` (blake3 of repo + config_type + field_name) → byte-
    identical re-runs, no timestamps.
    """

    shape_id: str  # blake3(repo, config_type, field_name or "")
    repo: str
    module: str  # owning module machine name (may be "" for site-level schema)
    config_type: str  # schema key, e.g. "asset.type.*"
    entity_kind: str  # schema `type:` — config_entity | mapping | …
    field_name: str | None  # None for the type-summary row
    field_type: str | None  # Drupal typed-data type of the field, if given
    field_label: str | None  # field/type label from the schema, if given
    source_file: str  # repo-relative config/schema path (provenance)
    schema_version: int = SCHEMA_VERSION


FEATURES_COLUMNS: tuple[str, ...] = (
    "feature_id",
    "repo",
    "name",
    "label",
    "description",
    "source_basis",
    "declarative_ref",
    "package",
    "core_requirement",
    "depends_on",
    "config_entity_types",
    "routes_count",
    "permissions_count",
    "member_globs",
    "schema_version",
)

CONFIG_SHAPES_COLUMNS: tuple[str, ...] = (
    "shape_id",
    "repo",
    "module",
    "config_type",
    "entity_kind",
    "field_name",
    "field_type",
    "field_label",
    "source_file",
    "schema_version",
)


__all__ = [
    "SCHEMA_VERSION",
    "EdgeKind",
    "EmbeddingRow",
    "MotifRow",
    "MotifInstanceRow",
    "ShapePDRow",
    "WassersteinH1Row",
    "CentralityRow",
    "SpectralClusterRow",
    "SubsystemRow",
    "SubsystemMemberRow",
    "InterfaceRow",
    "DataShapeRow",
    "IntentionSignalRow",
    "IntentionLoadRow",
    "IntentionConflictRow",
    "PresentationRow",
    "OperadRow",
    "HomProfileRow",
    "FunctorRow",
    "FunctorEdgeRow",
    "NNIndexMeta",
    "ArtifactManifest",
    "EMBEDDINGS_COLUMNS",
    "MOTIFS_COLUMNS",
    "MOTIF_INSTANCES_COLUMNS",
    "SHAPE_PDS_COLUMNS",
    "WASSERSTEIN_H1_COLUMNS",
    "CENTRALITY_COLUMNS",
    "SPECTRAL_CLUSTERS_COLUMNS",
    "SUBSYSTEMS_COLUMNS",
    "SUBSYSTEM_MEMBERS_COLUMNS",
    "INTERFACES_COLUMNS",
    "DATA_SHAPES_COLUMNS",
    "INTENTION_SIGNALS_COLUMNS",
    "INTENTION_LOAD_COLUMNS",
    "INTENTION_CONFLICTS_COLUMNS",
    "PRESENTATIONS_COLUMNS",
    "OPERADS_COLUMNS",
    "HOM_PROFILES_COLUMNS",
    "FUNCTORS_COLUMNS",
    "FUNCTOR_EDGES_COLUMNS",
    "FeatureRow",
    "ConfigShapeRow",
    "FEATURES_COLUMNS",
    "CONFIG_SHAPES_COLUMNS",
]
