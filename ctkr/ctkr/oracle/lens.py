"""The LENS — a target's vocabulary, probe contract and adapter, supplied *to*
the instrument rather than imported *by* it.

The dependency arrow
--------------------

Before this module the arrow pointed the wrong way: generic oracle machinery
imported ``ctkr.oracle.glossary`` (the closed sets), ``ctkr.oracle.probes``
(the probe dispatch table) and ``ctkr.oracle.farmos_adapter`` (a live farmOS
client) directly. The target's vocabulary was **ambient module-level state the
core read at import time**, so adding one farmOS word edited eight files of the
instrument and a second port would have written its vocabulary into the same
eight files as the first.

A :class:`Lens` is that target-specific material as *data*:

* :attr:`Lens.vocabulary` — the closed sets a fixture may speak (:class:`Vocabulary`)
* :attr:`Lens.probe_contract` / :attr:`Lens.operation_contract` — the binding
  from glossary term to adapter method
* :attr:`Lens.build_adapter` / :attr:`Lens.build_client` — how to reach the
  target's live boundary
* :attr:`Lens.provenance_path` — the lens's own ledger of bound terms
* :attr:`Lens.codegen_targets` — the files ``add-term`` writes vocabulary into

**ctkr never imports a lens module.** A lens registers itself; the instrument
discovers it. ``tests/test_lens_boundary.py`` is the fitness test that fails the
moment that is breached.

Discovery
---------

Two channels, no configuration:

1. ``importlib.metadata`` entry points in the group :data:`ENTRY_POINT_GROUP`
   (``"ctkr.lenses"``). A lens package living **outside this repo** registers by
   declaring one entry point; zero instrument edits.
2. :data:`BUILTIN_LENSES` — the in-repo ``farmos`` lens, whose files still live
   under ``ctkr/oracle/`` (relocation is a later slice, MetaCoding-1gt). It is
   named by *string* and imported lazily, so this generic module never imports a
   lens module at import time.

Resolving THE ACTIVE LENS
-------------------------

Most call paths thread a lens explicitly. Some cannot — notably the pydantic
validators in :mod:`ctkr.oracle.fixtures`, which run inside model validation
with no place to pass one. Those call :func:`active_lens`, whose rule is
deliberately small, explicit and testable — *not* a second ambient global under
a new name:

* an explicitly bound lens wins (:func:`use_lens`, a ``ContextVar`` — scoped,
  thread-safe, and always released);
* otherwise, if exactly ONE lens is registered, it is the active one — the
  single-target case, which is every case today;
* otherwise it is an ERROR naming the candidates. Ambiguity is refused, never
  guessed.

There is deliberately **no environment variable and no flag** for this: the
whole point of MetaCoding-1gt is to *reduce* configuration surface, and a
``METACODING_LENS`` env var would be the ninth path-ish knob the design doc
names as the mistake with a longer name.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from importlib import import_module
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

#: Entry-point group an out-of-repo lens package registers under.
ENTRY_POINT_GROUP = "ctkr.lenses"

#: In-repo lenses, named as ``"module:attribute"`` strings so that importing
#: THIS module never imports a lens module. The farmOS lens's files still live
#: inside ``ctkr/oracle/``; this mapping is what makes them a *registered lens*
#: rather than an ambient import.
BUILTIN_LENSES: Mapping[str, str] = {
    "farmos": "ctkr.oracle.farmos_lens:LENS",
}


class LensError(RuntimeError):
    """A lens could not be resolved, or the resolution was ambiguous."""


# --------------------------------------------------------------------------- #
# The vocabulary                                                              #
# --------------------------------------------------------------------------- #
#: The closed sets that make up a target's vocabulary. The names are the
#: instrument's, not any target's: a lens must supply every one of them.
VOCABULARY_SETS: tuple[str, ...] = (
    "ENTITY_TERMS",
    "ACTION_TERMS",
    "LOG_KINDS",
    "ADJUSTMENT_KINDS",
    "ANIMAL_SEXES",
    "LOG_STATUSES",
    "MEASURES",
    "LAND_TYPES",
    "STRUCTURE_TYPES",
    "ASSERTION_TERMS",
)

#: The sets whose members are TERMS — the union :meth:`Vocabulary.all_terms`
#: returns. ``COMPARISON_OPS``, the FORBIDDEN_* sets and ``ANIMAL_SEXES`` are
#: vocabulary but NOT terms, exactly as ``glossary.all_terms()`` had it (a sex
#: is a trait value carried by a given step, never a term a step may name).
TERM_SETS: tuple[str, ...] = tuple(
    n for n in VOCABULARY_SETS if n != "ANIMAL_SEXES"
)


@dataclass(frozen=True)
class Vocabulary:
    """A target's closed sets — what a semantic fixture is allowed to say.

    Attribute names match the module-level names the glossary used, so a
    ``getattr(vocab, "LOG_STATUSES")`` lookup (the enum-provenance channel does
    exactly this) keeps working unchanged.
    """

    ENTITY_TERMS: frozenset[str]
    ACTION_TERMS: frozenset[str]
    LOG_KINDS: frozenset[str]
    ADJUSTMENT_KINDS: frozenset[str]
    ANIMAL_SEXES: frozenset[str]
    LOG_STATUSES: frozenset[str]
    MEASURES: frozenset[str]
    LAND_TYPES: frozenset[str]
    STRUCTURE_TYPES: frozenset[str]
    ASSERTION_TERMS: frozenset[str]
    COMPARISON_OPS: frozenset[str]
    FORBIDDEN_SUBSTRINGS: tuple[str, ...]
    FORBIDDEN_WORDS: frozenset[str]

    def all_terms(self) -> frozenset[str]:
        """Every legal term across all roles (for validator membership)."""
        out: frozenset[str] = frozenset()
        for name in TERM_SETS:
            out = out | getattr(self, name)
        return out

    @classmethod
    def from_module(cls, module: Any) -> Vocabulary:
        """Build a vocabulary from a module carrying the closed sets by name.

        The farmOS lens uses this over ``ctkr.oracle.glossary``: the sets stay
        where they are (and where ``add-term`` writes them), and the lens simply
        *carries* them instead of the instrument importing them.
        """
        kwargs: dict[str, Any] = {}
        for name in (*VOCABULARY_SETS, "COMPARISON_OPS", "FORBIDDEN_WORDS"):
            value = getattr(module, name)
            kwargs[name] = frozenset(value)
        kwargs["FORBIDDEN_SUBSTRINGS"] = tuple(module.FORBIDDEN_SUBSTRINGS)
        return cls(**kwargs)


# --------------------------------------------------------------------------- #
# The lens                                                                    #
# --------------------------------------------------------------------------- #
#: The logical names of the files ``add-term`` generates code into. A lens
#: declares a path per name, so ``add-term`` for a future target writes into
#: THAT target's files.
CODEGEN_TARGETS: tuple[str, ...] = (
    "glossary",
    "probes",
    "steps",
    "adapter",
    "adapter_impl",
    "recorder",
    "fixtures",
    "port_adapter",
)


@dataclass(frozen=True)
class Lens:
    """Everything target-specific the instrument needs, supplied as data.

    ``probe_contract`` / ``operation_contract`` are typed loosely on purpose:
    their element types (``ProbeSpec``, ``OperationSpec``) live in a lens module
    today, and this generic module may not import one.
    """

    #: The lens's name — what ``--adapter`` accepts and packs record.
    name: str
    vocabulary: Vocabulary
    probe_contract: Mapping[str, Any]
    operation_contract: Mapping[str, Any] = field(default_factory=dict)
    #: ``build_client(base_url, username, password, *, recording, client_id,
    #: client_secret, timeout)`` → a transport for the target's boundary.
    build_client: Callable[..., Any] | None = None
    #: ``build_adapter(client)`` → an :class:`~ctkr.oracle.adapter.ImplementationAdapter`.
    build_adapter: Callable[..., Any] | None = None
    #: The lens's ledger of bound terms (``glossary_provenance.jsonl``).
    provenance_path: Path | None = None
    #: Logical name → repo-relative path, for every name in :data:`CODEGEN_TARGETS`.
    codegen_targets: Mapping[str, str] = field(default_factory=dict)
    #: Optional: the module carrying the closed sets, for tools that must WRITE
    #: vocabulary (``add-term``) rather than read it.
    glossary_module: str = ""

    def __post_init__(self) -> None:
        missing = [t for t in CODEGEN_TARGETS if t not in self.codegen_targets]
        if self.codegen_targets and missing:
            raise LensError(
                f"lens {self.name!r} declares codegen targets but omits "
                f"{missing} — add-term would have nowhere to write them"
            )

    def codegen_target(self, name: str) -> str:
        try:
            return self.codegen_targets[name]
        except KeyError:
            raise LensError(
                f"lens {self.name!r} declares no codegen target {name!r} "
                f"(known: {sorted(self.codegen_targets)})"
            ) from None


# --------------------------------------------------------------------------- #
# The registry                                                                #
# --------------------------------------------------------------------------- #
_cache: dict[str, Lens] = {}


def _entry_point_loaders() -> dict[str, Callable[[], Any]]:
    """Lens loaders discovered through ``importlib.metadata`` entry points."""
    loaders: dict[str, Callable[[], Any]] = {}
    try:
        eps = entry_points(group=ENTRY_POINT_GROUP)
    except TypeError:  # pragma: no cover - Python < 3.10 selection API
        eps = entry_points().get(ENTRY_POINT_GROUP, ())  # type: ignore[assignment]
    for ep in eps:
        loaders[ep.name] = ep.load
    return loaders


def _builtin_loader(spec: str) -> Callable[[], Any]:
    def load() -> Any:
        module_name, _, attr = spec.partition(":")
        return getattr(import_module(module_name), attr)

    return load


def _loaders() -> dict[str, Callable[[], Any]]:
    """All lens loaders. Entry points win over builtins of the same name."""
    loaders = {name: _builtin_loader(spec) for name, spec in BUILTIN_LENSES.items()}
    loaders.update(_entry_point_loaders())
    return loaders


def lens_names() -> tuple[str, ...]:
    """Every registered lens name, sorted. This is what ``--adapter`` offers."""
    return tuple(sorted(_loaders()))


def get_lens(name: str) -> Lens:
    """Load a registered lens by name."""
    cached = _cache.get(name)
    if cached is not None:
        return cached
    loaders = _loaders()
    if name not in loaders:
        raise LensError(
            f"unknown lens {name!r} (registered: {sorted(loaders)}). A lens "
            f"registers through the {ENTRY_POINT_GROUP!r} entry-point group."
        )
    loaded = loaders[name]()
    lens = loaded() if callable(loaded) and not isinstance(loaded, Lens) else loaded
    if not isinstance(lens, Lens):
        raise LensError(
            f"lens {name!r} resolved to {type(lens).__name__}, not a Lens"
        )
    _cache[name] = lens
    return lens


def clear_lens_cache() -> None:
    """Drop memoised lenses (tests that register a lens mid-run)."""
    _cache.clear()


# --- the active lens -------------------------------------------------------- #
#: The explicitly bound lens, if any. A ContextVar rather than a module global
#: so binding is scoped and thread/task-safe — see the module docstring for why
#: this is not "a second ambient global under a new name".
_active: ContextVar[Lens | None] = ContextVar("ctkr_active_lens", default=None)


def active_lens() -> Lens:
    """The lens the instrument should speak through right now.

    Rule (see module docstring): an explicitly bound lens wins; otherwise the
    single registered lens; otherwise refuse.
    """
    bound = _active.get()
    if bound is not None:
        return bound
    names = lens_names()
    if len(names) == 1:
        return get_lens(names[0])
    if not names:
        raise LensError(
            f"no lens is registered — a target supplies one through the "
            f"{ENTRY_POINT_GROUP!r} entry-point group"
        )
    raise LensError(
        f"{len(names)} lenses are registered ({list(names)}) and none is bound. "
        f"Bind one explicitly with ctkr.oracle.lens.use_lens(name)."
    )


def set_active_lens(lens: Lens | str | None) -> Any:
    """Bind the active lens. Returns the ContextVar token for :func:`reset`."""
    if isinstance(lens, str):
        lens = get_lens(lens)
    return _active.set(lens)


def reset_active_lens(token: Any) -> None:
    _active.reset(token)


@contextlib.contextmanager
def use_lens(lens: Lens | str) -> Iterator[Lens]:
    """Bind ``lens`` as active for the duration of the block."""
    token = set_active_lens(lens)
    try:
        yield _active.get()  # type: ignore[misc]
    finally:
        _active.reset(token)


def active_vocabulary() -> Vocabulary:
    """The active lens's closed sets — the glossary, de-ambientised."""
    return active_lens().vocabulary


def active_probe_contract() -> Mapping[str, Any]:
    """The active lens's probe dispatch table."""
    return active_lens().probe_contract


def active_operation_contract() -> Mapping[str, Any]:
    """The active lens's action → adapter-method table."""
    return active_lens().operation_contract
