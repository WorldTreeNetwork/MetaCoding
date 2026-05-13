"""Pydantic models for Layer-3 (LLM-bridged) CTKR artifacts.

L3 takes L1's mechanical outputs (motifs, role clusters, cross-repo
analogies) and labels them with natural-language descriptions via an
LLM. The labeled artifacts live at ``.metacoding/ctkr/`` alongside the
L1 outputs but in JSONL form rather than Parquet:

    .metacoding/ctkr/
    ├── patterns.jsonl       # rows: PatternRow
    └── evidence.jsonl       # rows: EvidenceRow

JSONL was chosen over Parquet here because L3 rows are produced one at
a time during LLM streaming, and natural-language fields don't benefit
from columnar storage. JSONL is also tractable to ``git diff`` —
useful when labels need human review.

Versioning rule: ``schema_version`` versions THIS module; ``prompt_version``
versions the prompt that produced the label. Re-running with a new prompt
should invalidate (not regenerate-in-place) old labels, so prompts are
treated as a first-class versioning dimension.

See ``docs/design/ctkr-l3-artifacts.md`` for full prose.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, NonNegativeFloat, NonNegativeInt, PositiveInt

SCHEMA_VERSION: int = 1

SourceKind = Literal["motif", "role-cluster", "analogy"]


class LineRange(BaseModel):
    """Inclusive line span in a source file."""

    start: PositiveInt
    end: PositiveInt


class EvidenceRow(BaseModel):
    """One snippet of source evidence for a labeled pattern.

    Multiple rows per ``pattern_id``: each row points to a concrete
    location in some repo whose code instantiates the pattern. The
    snippet itself is materialized so the JSONL is self-contained for
    review — no re-resolution needed against the indexed sources.
    """

    pattern_id: str
    repo: str
    file: str  # repo-relative path
    line_range: LineRange
    snippet: str  # inclusive of line_range; trimmed to ~80 char wide
    context: str | None = Field(
        default=None,
        description=(
            "Optional surrounding-symbol qualified_name (e.g. the enclosing "
            "class or function). Lets reviewers orient without opening the file."
        ),
    )
    schema_version: int = SCHEMA_VERSION


class PatternRow(BaseModel):
    """One labeled structural element produced by an L3 labeler.

    ``source_ref`` is a foreign key into the L1 artifact named by
    ``source_kind``:

    - ``source_kind == "motif"``       → ``source_ref`` is a ``motif_id``
    - ``source_kind == "role-cluster"`` → ``source_ref`` is a cluster id
    - ``source_kind == "analogy"``      → ``source_ref`` is an analogy-pair id

    ``instances`` lists the concrete symbol_ids that participate; for
    motifs these are the anchor symbols (matching
    ``MotifInstanceRow.symbol_id`` in schema.py). The corresponding
    code-evidence snippets live in ``evidence.jsonl``.

    Mandatory provenance fields — ``llm_model``, ``llm_temperature``,
    ``prompt_version``, ``schema_version`` — make every label
    invalidatable on prompt or model changes without re-running L1.
    """

    pattern_id: str
    source_kind: SourceKind
    source_ref: str
    label: str = Field(
        description=(
            "Short canonical name (~3 words). Reused as a pattern key in "
            "downstream cross-instantiation synthesis."
        ),
    )
    description: str = Field(
        description="One-paragraph explanation of what the pattern does and why it recurs.",
    )
    instances: list[str] = Field(
        description="Symbol IDs (anchor symbols) participating in this pattern.",
    )
    evidence_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Optional explicit list of evidence row keys (pattern_id is the "
            "primary join; this field is for cases where evidence rows are "
            "themselves uniquely keyed). May be empty if the join is purely "
            "by pattern_id."
        ),
    )
    confidence: NonNegativeFloat = Field(
        ge=0.0, le=1.0, description="LLM-reported or post-hoc confidence in [0, 1]."
    )
    llm_model: str  # MANDATORY
    llm_temperature: float  # MANDATORY (may be 0.0 for deterministic mode)
    prompt_version: str  # MANDATORY  (e.g. "motif-labeler:v3")
    schema_version: int = SCHEMA_VERSION  # MANDATORY
    generated_at: datetime


__all__ = [
    "SCHEMA_VERSION",
    "SourceKind",
    "LineRange",
    "EvidenceRow",
    "PatternRow",
]
