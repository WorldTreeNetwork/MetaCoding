"""Spec-driven plumbing codegen for a new glossary term (bead MetaCoding-b5r).

MetaCoding-yph measured the cost of one new fixture-vocabulary term: an 8–9
file change (glossary set, probe/operation contract, adapter ABC, farmOS
adapter, port surface, runner dispatch, flowspec validation, tests), and 14 of
the first 25 terms arrived from just two features. This module generates that
plumbing from one TERM-SPEC v1, so the marginal cost of a term is a review of
one diff, not an archaeology of nine files.

What it generates, by kind (all as text edits against a TARGET TREE — the
``--root`` a caller names, never implicitly this repo):

* every kind — the glossary set entry, and a test skeleton that pins the term's
  registration and its loud-failure behaviour;
* ``assertion`` — a :class:`ProbeSpec` in ``probes._PROBES`` declared
  ``authority=DERIVED`` with the spec's probe semantics as the derivation and
  **no** ``validated_against``: honest by construction, its values cannot score
  until someone validates the derivation (``is_evidence`` is False), and the
  provenance row keeps it PROVISIONAL besides; adapter stubs on the ABC and the
  farmOS adapter; the ``_observe_probe`` dispatch arm in the recorder and the
  ``_ASSERT_REQUIRED`` row in fixtures (both were hand-wired on the first two
  live runs — MetaCoding-td9). A spec may declare ``params`` (extra probe
  fields, alias-resolved when ``alias_noun`` is set — the ``has_parent`` shape)
  and a non-default ``subject_kind``; both flow into the ProbeSpec, the stub
  signatures, the recorder call, and the required-fields row. A spec may also
  declare ``value_shape`` (``"scalar"`` default, or ``"list"``) which shapes the
  PORT-adapter dispatch alone;
* ``action`` — an :class:`OperationSpec` in ``probes._OPERATIONS``, the
  interpreter arm in ``steps.apply_when``, and the same adapter stubs;
* ``action``/``assertion`` also — the :class:`~ctkr.oracle.port_adapter.PortAdapter`
  dispatch method (MetaCoding-wob). Unlike every other adapter stub it does NOT
  raise and is NOT hand-implemented: it only forwards to the port's declared
  bridge op, gated on the declaration. The lab_test builder had to hand-write
  these six methods mid-build because the generator left this seam — the whole
  measurement chain from probe to bridge is now emitted, so a builder never
  touches the instrument.

**The fake-green rule, structurally.** Every generated adapter stub RAISES
(``AdapterError`` on the ABC, ``NotImplementedError`` on the farmOS adapter,
each carrying the spec's probe semantics) — a stub that returned a constant
would be a port that answers questions nobody implemented, which is the exact
defect the probe contract exists to make impossible.

Anchors are matched exactly and FAIL LOUDLY (:class:`CodegenError`) when the
target tree has drifted: a misplaced insertion is worse than none.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from pathlib import Path

from ctkr.oracle.glossary_provenance import validate_term_spec

GLOSSARY = "ctkr/oracle/glossary.py"
PROBES = "ctkr/oracle/probes.py"
STEPS = "ctkr/oracle/steps.py"
ADAPTER = "ctkr/oracle/adapter.py"
FARMOS = "ctkr/oracle/farmos_adapter.py"
RECORDER = "ctkr/oracle/recorder.py"
FIXTURES = "ctkr/oracle/fixtures.py"
PORT_ADAPTER = "ctkr/oracle/port_adapter.py"

_SET_FOR_KIND = {
    "entity": "ENTITY_TERMS",
    "action": "ACTION_TERMS",
    "assertion": "ASSERTION_TERMS",
}


class CodegenError(RuntimeError):
    """The spec is invalid or the target tree does not match the anchors."""


@dataclass(frozen=True)
class FileEdit:
    """One file's before/after under the target root. ``before == ""`` = new file."""

    rel_path: str
    before: str
    after: str

    @property
    def is_new(self) -> bool:
        return self.before == ""


def _read(root: Path, rel: str) -> str:
    p = root / rel
    if not p.is_file():
        raise CodegenError(f"target tree {root} has no {rel} — wrong --root?")
    return p.read_text(encoding="utf-8")


def _insert_before(source: str, anchor: str, text: str, rel: str) -> str:
    idx = source.find(anchor)
    if idx < 0:
        raise CodegenError(
            f"{rel}: anchor {anchor.splitlines()[0]!r}... not found — the "
            f"target tree has drifted from what this generator knows; refusing "
            f"to guess an insertion point"
        )
    if source.find(anchor, idx + 1) >= 0:
        raise CodegenError(f"{rel}: anchor is ambiguous ({anchor[:40]!r} twice)")
    return source[:idx] + text + source[idx:]


def _short(text: str, limit: int = 68) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _insert_at_class_end(source: str, anchor: str, text: str, rel: str) -> str:
    """Insert ``text`` at the true end of the class body that PRECEDES ``anchor``
    (the first module-level statement after the class).

    Inserting directly before the anchor put generated methods after the
    module-level section banner — textually at module scope, hand-relocated on
    both live runs (MetaCoding-td9). Walking back over blank lines and
    column-0 comments lands the method after the class's last statement.
    """
    idx = source.find(anchor)
    if idx < 0:
        raise CodegenError(
            f"{rel}: anchor {anchor.splitlines()[0]!r}... not found — the "
            f"target tree has drifted from what this generator knows; refusing "
            f"to guess an insertion point"
        )
    if source.find(anchor, idx + 1) >= 0:
        raise CodegenError(f"{rel}: anchor is ambiguous ({anchor[:40]!r} twice)")
    head = source[:idx]
    lines = head.split("\n")
    cut = len(lines)
    while cut > 0 and (lines[cut - 1].strip() == "" or lines[cut - 1].startswith("#")):
        cut -= 1
    # The walkback recognizes exactly blank lines and column-0 comments. If the
    # line it lands on is not indented, it is NOT a class-body statement (e.g. a
    # module-level assignment or docstring appeared between the class and the
    # anchor) and inserting an indented method there would emit invalid Python —
    # refuse loudly instead (review finding on MetaCoding-td9).
    if cut == 0 or not lines[cut - 1].startswith((" ", "\t")):
        raise CodegenError(
            f"{rel}: the statement preceding the anchor is at module scope, not "
            f"a class body — the tree has drifted from what this generator "
            f"knows; refusing to emit a mis-indented method"
        )
    body_end = "\n".join(lines[:cut])
    tail = head[len(body_end):] + source[idx:]
    return body_end + "\n" + text + tail


# --------------------------------------------------------------------------- #
# Probe shape (MetaCoding-td9): spec-declared params + subject_kind            #
# --------------------------------------------------------------------------- #
def _spec_params(spec: dict) -> tuple[tuple[str, str], ...]:
    """``(field_name, alias_noun)`` pairs, in call order after the subject."""
    return tuple(
        (p["field_name"], p.get("alias_noun", "")) for p in spec.get("params", [])
    )


def _stub_signature_tail(params: tuple[tuple[str, str], ...]) -> str:
    """The stub arguments after ``subject_handle`` — an alias param arrives
    resolved (a ``Handle``); a plain param arrives as the assertion's own
    string field."""
    return "".join(
        f", {f}_handle: Handle" if noun else f", {f}: str" for f, noun in params
    )


def _call_args(params: tuple[tuple[str, str], ...]) -> str:
    """How the recorder passes each param: alias fields resolve through
    ``handles`` (the same resolution ``has_parent`` uses); plain fields pass
    the assertion's field verbatim."""
    return "".join(
        f", handles[probe.{f}]" if noun else f", probe.{f}" for f, noun in params
    )


# --------------------------------------------------------------------------- #
# Per-file generators                                                          #
# --------------------------------------------------------------------------- #
def _glossary_edit(src: str, term: str, kind: str, description: str) -> str:
    if f'"{term}"' in src:
        raise CodegenError(f"term {term!r} is already in the glossary")
    set_name = _SET_FOR_KIND[kind]
    marker = f"{set_name}: frozenset[str] = frozenset("
    start = src.find(marker)
    if start < 0:
        raise CodegenError(f"{GLOSSARY}: cannot find the {set_name} set")
    close = src.find("\n    }", start)
    if close < 0:
        raise CodegenError(f"{GLOSSARY}: cannot find the end of {set_name}")
    line = f'\n        "{term}",  # {_short(description)} [PROVISIONAL]'
    return src[:close] + line + src[close:]


def _probe_entry(
    term: str,
    description: str,
    probe_semantics: str,
    params: tuple[tuple[str, str], ...],
    subject_kind: str,
) -> str:
    if params:
        params_src = "(" + ", ".join(
            f"Param({f!r}, {noun!r})" if noun else f"Param({f!r})"
            for f, noun in params
        ) + ",)"
    else:
        params_src = "()"
    kind_src = "" if subject_kind == "entity" else f' subject_kind="{subject_kind}",'
    return (
        f"    # --- generated by `ctkr add-term` (PROVISIONAL until bind-term) ----- #\n"
        f"    # DERIVED with no validated_against ON PURPOSE: the derivation below is\n"
        f"    # the spec's proposed semantics, which no source authority has validated\n"
        f"    # yet — so is_evidence is False and values cannot score until it is.\n"
        f'    ProbeSpec({term!r}, {term!r}, {params_src},{kind_src}\n'
        f"              doc={_short(description, 160)!r},\n"
        f"              authority=DERIVED,\n"
        f"              derivation={_short(probe_semantics, 240)!r}),\n"
    )


def _operation_entry(term: str, description: str) -> str:
    return (
        f"    # generated by `ctkr add-term` (PROVISIONAL until bind-term)\n"
        f"    OperationSpec({term!r}, ({term!r},),\n"
        f"                  doc={_short(description, 160)!r}),\n"
    )


def _steps_arm(term: str) -> str:
    return (
        f'    elif w.action == "{term}":\n'
        f"        # generated by `ctkr add-term` — review the argument mapping when\n"
        f"        # implementing the adapter; the default adapter method RAISES, so\n"
        f"        # this arm cannot fake a recorded flow before that happens.\n"
        f"        adapter.{term}(handles[w.ref])\n"
    )


def _adapter_stub(
    term: str, kind: str, probe_semantics: str,
    params: tuple[tuple[str, str], ...] = (),
) -> str:
    return (
        f"\n    # --- generated: {term} ({kind}, PROVISIONAL) --- #\n"
        f"    def {term}(self, subject_handle: Handle{_stub_signature_tail(params)}) -> Any:\n"
        f'        """{_short(probe_semantics, 300)}\n'
        f"\n"
        f"        Generated stub — raises until an implementation exists. A stub\n"
        f"        that returned a constant could be mistaken for an observed value.\n"
        f'        """\n'
        f'        raise self._unsupported("{term}")\n'
    )


def _farmos_stub(
    term: str, kind: str, probe_semantics: str,
    params: tuple[tuple[str, str], ...] = (),
) -> str:
    return (
        f"\n    # --- generated: {term} ({kind}, PROVISIONAL) --- #\n"
        f"    def {term}(self, subject_handle: Handle{_stub_signature_tail(params)}) -> Any:\n"
        f'        """{_short(probe_semantics, 300)}\n'
        f"\n"
        f"        Generated stub: implement against the live boundary, then record\n"
        f"        and `ctkr bind-term {term}`. Raises so an unimplemented probe can\n"
        f"        never be mistaken for an observed value.\n"
        f'        """\n'
        f"        raise NotImplementedError(\n"
        f"            {(_short(probe_semantics, 200) + ' — ' + term + ' is PROVISIONAL and unimplemented')!r}\n"
        f"        )\n"
    )


def _bridge_call_tail(params: tuple[tuple[str, str], ...]) -> str:
    """Keyword args after ``subject`` in the bridge call: an alias param passes
    its resolved handle, a plain param passes the assertion's own string field.
    Mirrors the hand-written ``equipment_used``/``material_type_recorded`` port
    methods so a generated dispatch is indistinguishable from a written one."""
    return "".join(
        f", {f}={f}_handle" if noun else f", {f}={f}" for f, noun in params
    )


def _port_adapter_stub(
    term: str, kind: str, probe_semantics: str,
    params: tuple[tuple[str, str], ...], value_shape: str,
) -> str:
    """The :class:`PortAdapter` dispatch method — the seam the FIRST live run of
    this generator missed (MetaCoding-wob): every other adapter stub RAISES and
    is hand-implemented, but the port adapter method only FORWARDS to the port's
    declared bridge op, so it is fully mechanical — and a human hand-writing it
    (as the lab_test builder had to, mid-build) is pure toil plus an instrument
    the builder should never touch. Unlike the ABC/farmOS stubs this does NOT
    raise: it gates on the port having declared the surface (``_need_probe`` /
    ``_need_operation``, which raise ``Unanswerable`` when it did not) and then
    speaks to the bridge. A ``list`` value_shape guards the wire shape so a
    bridge that answers a non-list is a BridgeError (NO VERDICT), never a silent
    wrong compare; a ``scalar`` shape forwards the value raw so a type mismatch
    surfaces as a real comparison, never masked by a coercion."""
    sig = _stub_signature_tail(params)
    call_tail = _bridge_call_tail(params)
    gate = "_need_operation" if kind == "action" else "_need_probe"
    ret = "list[str]" if value_shape == "list" else "Any"
    head = (
        f"\n    # --- generated: {term} ({kind}, PROVISIONAL) --- #\n"
        f"    def {term}(self, subject_handle: Handle{sig}) -> {ret}:\n"
        f'        """{_short(probe_semantics, 300)}\n'
        f"\n"
        f"        Generated dispatch: forwards to the port's declared bridge op,\n"
        f"        gated on the port having declared it. Nothing to implement — the\n"
        f"        bridge the build produced answers, or the gate raises.\n"
        f'        """\n'
        f'        self.{gate}("{term}")\n'
    )
    if value_shape == "list":
        return (
            head
            + f'        got = self._bridge.call("{term}", subject=subject_handle{call_tail})\n'
            + f"        if not isinstance(got, list):\n"
            + f"            raise BridgeError(\n"
            + f'                f"port bridge answered {term!r} with "\n'
            + f'                f"{{type(got).__name__}} {{got!r}}; expected a list of names"\n'
            + f"            )\n"
            + f"        return [str(n) for n in got]\n"
        )
    return (
        head
        + f'        return self._bridge.call("{term}", subject=subject_handle{call_tail})\n'
    )


def _recorder_arm(term: str, params: tuple[tuple[str, str], ...]) -> str:
    """The ``_observe_probe`` dispatch arm — the seam the first live run of this
    generator missed (MetaCoding-td9): everything else was wired, and the first
    recording died with 'unknown probe assertion'."""
    return (
        f'    # generated by `ctkr add-term` (PROVISIONAL until bind-term)\n'
        f'    if probe.assert_ == "{term}":\n'
        f"        return adapter.{term}(subject{_call_args(params)})\n"
    )


_ASSERT_REQUIRED_MARKER = "_ASSERT_REQUIRED: dict[str, tuple[str, ...]] = {"


def _assert_required_has_row(src: str, term: str) -> bool:
    """Whether ``term`` already has a row INSIDE the ``_ASSERT_REQUIRED`` table.

    Scoped to the table region so an identically named dict key elsewhere in
    fixtures.py (a GivenStep write-field, say) is not mistaken for a row."""
    start = src.find(_ASSERT_REQUIRED_MARKER)
    if start < 0:
        raise CodegenError(f"{FIXTURES}: cannot find the _ASSERT_REQUIRED table")
    close = src.find("\n}", start)
    if close < 0:
        raise CodegenError(f"{FIXTURES}: cannot find the end of _ASSERT_REQUIRED")
    return f'"{term}":' in src[start:close]


def _fixtures_edit(src: str, term: str, params: tuple[tuple[str, str], ...]) -> str:
    """Register the assertion's required fields in ``_ASSERT_REQUIRED`` so the
    validator demands exactly the fields the probe consumes (plus the observed
    value) — previously a hand edit after every generation."""
    marker = _ASSERT_REQUIRED_MARKER
    start = src.find(marker)
    if start < 0:
        raise CodegenError(f"{FIXTURES}: cannot find the _ASSERT_REQUIRED table")
    close = src.find("\n}", start)
    if close < 0:
        raise CodegenError(f"{FIXTURES}: cannot find the end of _ASSERT_REQUIRED")
    required = tuple(f for f, _ in params) + ("value",)
    fields_src = "(" + ", ".join(repr(f) for f in required) + (",)" if len(required) == 1 else ")")
    line = (
        f"\n    # generated by `ctkr add-term` (PROVISIONAL until bind-term)"
        f'\n    "{term}": {fields_src},'
    )
    return src[:close] + line + src[close:]


def _test_skeleton(term: str, kind: str, spec: dict) -> str:
    flow = json.dumps(spec["discriminating_flow"], indent=2, sort_keys=True)
    stub_args = "'H'" + "".join(
        f", {('X_' + f)!r}" for f, _ in _spec_params(spec)
    )
    lines = [
        f'"""Generated by `ctkr add-term` for PROVISIONAL {kind} term {term!r}.',
        "",
        "Pins what the plumbing guarantees BEFORE any implementation exists:",
        "the term is registered, the contract has no holes, and nothing can",
        "fake an answer for it. Replace the discriminating flow below with a",
        "recorded fixture once the term is bound.",
        '"""',
        "",
        "import json",
        "",
        "import pytest",
        "",
        "from ctkr.oracle import glossary",
        "from ctkr.oracle.probes import contract_gaps",
        "",
        f"TERM = {term!r}",
        "",
        "# The spec's discriminating flow — the scenario a recording must exercise",
        "# for `ctkr bind-term` to flip this term provisional -> bound.",
        f"DISCRIMINATING_FLOW = json.loads(r'''{flow}''')",
        "",
        "",
        f"def test_{term}_is_a_registered_glossary_term() -> None:",
        "    assert TERM in glossary.all_terms()",
        "    assert contract_gaps() == []",
        "",
    ]
    if kind in ("action", "assertion"):
        lines += [
            "",
            f"def test_{term}_unimplemented_stub_fails_loudly() -> None:",
            '    """The fake-green rule: an unimplemented surface RAISES, never answers."""',
            "    from ctkr.oracle.adapter import AdapterError, ImplementationAdapter",
            "",
            "    bare = type('_Bare', (ImplementationAdapter,), {})",
            "    bare.__abstractmethods__ = frozenset()",
            "    with pytest.raises(AdapterError):",
            f"        getattr(bare(), TERM)({stub_args})",
            "",
        ]
    if kind == "assertion":
        lines += [
            "",
            f"def test_{term}_is_not_yet_evidence() -> None:",
            '    """PROVISIONAL: derived, unvalidated — its values cannot score."""',
            "    from ctkr.oracle.probes import PROBE_CONTRACT",
            "",
            "    assert not PROBE_CONTRACT[TERM].is_evidence",
            "",
        ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Plan / render / apply                                                        #
# --------------------------------------------------------------------------- #
def plan_edits(spec: dict, root: str | Path) -> list[FileEdit]:
    """Every file edit the term needs, computed against the tree at ``root``.

    ``root`` is the directory that CONTAINS the ``ctkr`` package (and
    ``tests/``). Nothing is written; :func:`apply_edits` does that.
    """
    problems = validate_term_spec(spec)
    if problems:
        raise CodegenError("not a TERM-SPEC v1:\n  - " + "\n  - ".join(problems))
    root = Path(root)
    term, kind = spec["term"], spec["kind"]
    description, semantics = spec["description"], spec["probe_semantics"]
    params = _spec_params(spec)
    subject_kind = spec.get("subject_kind", "entity")
    value_shape = spec.get("value_shape", "scalar")

    edits: list[FileEdit] = []

    g = _read(root, GLOSSARY)
    edits.append(FileEdit(GLOSSARY, g, _glossary_edit(g, term, kind, description)))

    if kind == "assertion":
        p = _read(root, PROBES)
        p2 = _insert_before(
            p, "\n)\n\nPROBE_CONTRACT",
            "\n" + _probe_entry(term, description, semantics, params,
                                subject_kind).rstrip("\n"),
            PROBES)
        edits.append(FileEdit(PROBES, p, p2))
        r = _read(root, RECORDER)
        if f'probe.assert_ == "{term}"' in r:
            raise CodegenError(f"{RECORDER}: a dispatch arm for {term!r} already exists")
        r2 = _insert_before(
            r, '    raise ValueError(f"unknown probe assertion',
            _recorder_arm(term, params), RECORDER)
        edits.append(FileEdit(RECORDER, r, r2))
        x = _read(root, FIXTURES)
        # Scope the "already has a row" check to the _ASSERT_REQUIRED table: a
        # whole-file substring match on '"{term}":' also trips on an unrelated
        # dict key elsewhere in fixtures.py — e.g. a GivenStep write-field named
        # the same as a read-term (crop_family: a plant_type WRITE field and a
        # glossary READ term both exist, MetaCoding plant-type). The row lives
        # only inside the table.
        if _assert_required_has_row(x, term):
            raise CodegenError(f"{FIXTURES}: {term!r} already has a required-fields row")
        edits.append(FileEdit(FIXTURES, x, _fixtures_edit(x, term, params)))
    elif kind == "action":
        p = _read(root, PROBES)
        p2 = _insert_before(p, "\n)\n\nOPERATION_CONTRACT",
                            "\n" + _operation_entry(term, description).rstrip("\n"),
                            PROBES)
        edits.append(FileEdit(PROBES, p, p2))
        s = _read(root, STEPS)
        s2 = _insert_before(s, "    else:\n        raise AdapterError",
                            _steps_arm(term), STEPS)
        edits.append(FileEdit(STEPS, s, s2))

    if kind in ("action", "assertion"):
        a = _read(root, ADAPTER)
        if f"def {term}(" in a:
            raise CodegenError(f"{ADAPTER}: method {term!r} already exists")
        edits.append(FileEdit(ADAPTER, a, a.rstrip("\n") + "\n" + _adapter_stub(term, kind, semantics, params)))

        f = _read(root, FARMOS)
        if f"def {term}(" in f:
            raise CodegenError(f"{FARMOS}: method {term!r} already exists")
        f2 = _insert_at_class_end(f, "\ndef _iso(",
                                  _farmos_stub(term, kind, semantics, params), FARMOS)
        edits.append(FileEdit(FARMOS, f, f2))

        # The port-side dispatch method (MetaCoding-wob). PortAdapter is the last
        # class in the file and nothing module-level follows it, so the stub is
        # appended at end-of-file exactly like the ABC's — a class-body method.
        pa = _read(root, PORT_ADAPTER)
        if f"def {term}(" in pa:
            raise CodegenError(f"{PORT_ADAPTER}: method {term!r} already exists")
        edits.append(FileEdit(
            PORT_ADAPTER, pa,
            pa.rstrip("\n") + "\n"
            + _port_adapter_stub(term, kind, semantics, params, value_shape)))

    test_rel = f"tests/test_term_{term}.py"
    if (root / test_rel).exists():
        raise CodegenError(f"{test_rel} already exists")
    edits.append(FileEdit(test_rel, "", _test_skeleton(term, kind, spec)))
    return edits


def render_diffs(edits: list[FileEdit]) -> str:
    """The full unified diff a --dry-run prints."""
    out: list[str] = []
    for e in edits:
        out.extend(
            difflib.unified_diff(
                e.before.splitlines(keepends=True),
                e.after.splitlines(keepends=True),
                fromfile=f"a/{e.rel_path}" if not e.is_new else "/dev/null",
                tofile=f"b/{e.rel_path}",
            )
        )
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
    return "".join(out)


def apply_edits(edits: list[FileEdit], root: str | Path) -> list[Path]:
    """Write every edit under ``root``; refuses if any file moved since planning."""
    root = Path(root)
    for e in edits:  # verify the WHOLE plan before touching anything
        p = root / e.rel_path
        current = p.read_text(encoding="utf-8") if p.exists() else ""
        if current != e.before:
            raise CodegenError(
                f"{e.rel_path} changed between planning and applying — re-plan"
            )
    written: list[Path] = []
    for e in edits:
        p = root / e.rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(e.after, encoding="utf-8")
        written.append(p)
    return written
