"""The probe-contract SCHEMA — instrument-side, target-free (MetaCoding-1gt).

What a probe binding *is* belongs to the instrument; *which* bindings exist
belongs to a lens. This module holds the former: the authority constants, the
:class:`Param` / :class:`ProbeSpec` / :class:`OperationSpec` shapes, and the
helpers that read a contract table. The tables themselves live in a lens (for
farmOS, :mod:`ctkr.oracle.probes`) and reach generic code through
:func:`ctkr.oracle.lens.active_probe_contract`.

Split out of ``probes.py`` unchanged — the dataclasses are byte-identical moves,
because :attr:`ProbeSpec.derivation_id` is hashed into every sealed pack and an
"improvement" here would re-id the corpus.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from blake3 import blake3

# --------------------------------------------------------------------------- #
# INVARIANT 1 — every value declares its authority                             #
# --------------------------------------------------------------------------- #
#: The source system STATES this value at its published interface. Reading it is
#: transcription: there is no place for us to be wrong about the semantics,
#: only about the transport.
BOUNDARY = "boundary"
#: WE compute this value — an adapter query, a fold, an inference over what the
#: boundary delivered. A derived value carries our beliefs about the source's
#: semantics, and a belief is not evidence until it is validated against the
#: source's OWN authority (its published service/module code, or a documented
#: behaviour of the source). `group_member` is the proof this matters: a
#: hand-written "latest done assignment wins" query stood in for farmOS's
#: GroupMembership.php, which recurses by default and gates on effective time,
#: and the judge consequently ranked a port that MATCHED farmOS below one that
#: diverged from it.
DERIVED = "derived"

AUTHORITIES: frozenset[str] = frozenset({BOUNDARY, DERIVED})


@dataclass(frozen=True)
class Param:
    """One argument of a probe call, taken from the ``then`` assertion.

    ``alias_noun`` non-empty marks the field as a **logical alias** that must be
    resolved to a run-time handle before the call; the noun is used in the error
    message when the alias was never created ("group alias 'G' was never
    created").
    """

    field_name: str
    alias_noun: str = ""

    @property
    def is_alias(self) -> bool:
        return bool(self.alias_noun)


@dataclass(frozen=True)
class ProbeSpec:
    """How one glossary assertion term is answered by an adapter."""

    assertion: str
    method: str
    #: Arguments after the subject handle, in call order.
    params: tuple[Param, ...] = ()
    #: What the ``subject`` alias denotes — an entity or a recorded event.
    subject_kind: str = "entity"  # "entity" | "event" | "attempt"
    #: This probe returns an INSTANT. Such a probe cannot appear in a flow whose
    #: effective times are relative offsets: the recorded value is an absolute
    #: instant computed from the recording run's wall clock, so re-running the
    #: fixture minutes later reads a different one and it cannot self-verify.
    #: (MetaCoding-bdy — w0b first self-verified at 63.6%, every failure a uniform
    #: +24s, the gap between the record run and the verify run.)
    returns_timestamp: bool = False
    doc: str = ""

    # ---- INVARIANT 1: authority ------------------------------------------- #
    #: :data:`BOUNDARY` or :data:`DERIVED`. There is no third option and no
    #: default: a probe added without stating its authority fails
    #: :func:`contract_gaps`, which the test suite runs.
    authority: str = ""
    #: For a DERIVED probe: the SOURCE's own authority this derivation was
    #: validated against — its module/service code, or a documented behaviour.
    #: Empty means the derivation is our unvalidated belief, and a value produced
    #: by it is **not evidence**: it can never score an implementation.
    validated_against: str = ""
    #: What we compute, in one sentence. Hashed into :attr:`derivation_id`, so
    #: changing the derivation invalidates every fixture recorded under the old
    #: one instead of silently re-labelling old values as current.
    derivation: str = ""

    @property
    def is_evidence(self) -> bool:
        """Whether a value from this probe may SCORE an implementation.

        A boundary value always may. A derived value may only once its
        derivation is validated against the source's own authority. This is the
        structural form of invariant 1 — not a check that runs somewhere, but
        the gate every scoring path passes through.
        """
        return self.authority == BOUNDARY or bool(self.validated_against)

    @property
    def derivation_id(self) -> str:
        """Content id of this probe's derivation — empty for a boundary probe.

        A recorded fixture stamps the derivation_id of every derived probe it
        used. When we CHANGE a derivation (as `group_member` was changed to
        recurse and to gate on effective time), every fixture recorded under the
        old id no longer matches and is marked INVALID at load. Corrections
        cannot quietly bless stale values.
        """
        if self.authority != DERIVED:
            return ""
        canonical = json.dumps(
            {"assertion": self.assertion, "derivation": self.derivation,
             "validated_against": self.validated_against},
            sort_keys=True,
        )
        return blake3(canonical.encode("utf-8")).hexdigest()[:16]

    @property
    def unvalidated_reason(self) -> str:
        """Why this probe's values are not evidence, or ``""`` when they are."""
        if self.is_evidence:
            return ""
        return (
            f"{self.assertion!r} is a DERIVED value: {self.derivation or 'computed by adapter logic'}. "
            f"No validation against the source's own authority is recorded, so it "
            f"states OUR belief about the source, not the source's answer. "
            f"NO VERDICT."
        )


@dataclass(frozen=True)
class OperationSpec:
    """How one glossary action term is performed by an adapter."""

    action: str
    #: Methods always required to perform the action.
    methods: tuple[str, ...] = ()
    #: Methods additionally required when the step carries an effective time.
    methods_when_timed: tuple[str, ...] = field(default_factory=tuple)
    doc: str = ""


# --------------------------------------------------------------------------- #
# Contract readers — generic over WHICH table                                  #
# --------------------------------------------------------------------------- #
# Each takes the table explicitly and falls back to the active lens's. The
# explicit parameter is the point: a caller that already knows its lens never
# consults ambient state, and the fallback keeps call sites that cannot thread
# one (pydantic validators) working without importing a target.
def _probes(contract: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if contract is not None:
        return contract
    from ctkr.oracle.lens import active_probe_contract

    return active_probe_contract()


def _operations(contract: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if contract is not None:
        return contract
    from ctkr.oracle.lens import active_operation_contract

    return active_operation_contract()


def methods_for_probe(assertion: str, *, contract: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    """Adapter methods a given assertion term requires (empty if unknown)."""
    spec = _probes(contract).get(assertion)
    return (spec.method,) if spec else ()


def methods_for_action(
    action: str, *, timed: bool = False, contract: Mapping[str, Any] | None = None
) -> tuple[str, ...]:
    """Adapter methods a ``when`` step of ``action`` requires.

    ``timed`` is True when the step carries an effective time, which for some
    actions (``record_log``) means an extra restatement call.
    """
    spec = _operations(contract).get(action)
    if spec is None:
        return ()
    return spec.methods + (spec.methods_when_timed if timed else ())


def current_derivations(*, contract: Mapping[str, Any] | None = None) -> dict[str, str]:
    """``{assertion: derivation_id}`` for every DERIVED probe, as of this table.

    Stamped into a recorded pack's provenance. A pack whose stamp disagrees with
    this map was recorded under a derivation we have since changed, and its
    values are stale by construction — see :mod:`ctkr.oracle.pack`.
    """
    return {
        t: s.derivation_id
        for t, s in _probes(contract).items()
        if s.authority == DERIVED
    }


def unvalidated_probes(*, contract: Mapping[str, Any] | None = None) -> list[str]:
    """Probes whose values are NOT evidence — derived, with no source authority."""
    return sorted(t for t, s in _probes(contract).items() if not s.is_evidence)
