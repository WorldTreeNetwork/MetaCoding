"""The implementation adapter contract (port-loop Phase 2).

The oracle runs the *same* semantic fixtures against *any* implementation
through a thin per-implementation adapter. The adapter is the only code that
knows the target's data model — it maps glossary verbs (``record a harvest
log``) onto whatever the implementation actually is (farmOS JSON:API resources;
later, the local-first event log). Everything above this line is data-model-free.

An adapter deals in **opaque handles**: it mints a real identity for each entity
it creates and hands back a string handle the runner threads through the
scenario. A fixture never sees a real id — that is the value-line discipline.

The read side (``asset_yield_total`` etc.) returns **values**, computed from the
implementation's boundary however that implementation must — for farmOS, by
querying logs and summing quantities at the JSON:API level. A local-first port
would answer the same question from a materialized view. Both satisfy the same
fixture: same value delivered, different data model.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ctkr.oracle.fixtures import QuantitySpec

# An opaque, implementation-minted entity handle. Never inspected by the runner.
Handle = str


class AdapterError(RuntimeError):
    """Raised when an adapter operation fails (auth, HTTP, unsupported action)."""


class ImplementationAdapter(ABC):
    """Drive one implementation of the farmOS domain in glossary terms.

    The runner calls, per fixture: :meth:`open`, then the create/act methods for
    ``given`` and ``when`` steps, then the read methods for ``then`` assertions,
    then :meth:`close`. Handles bind logical aliases to real identities within a
    single fixture run and are not reused across fixtures.
    """

    name: str = "abstract"

    # ---- lifecycle --------------------------------------------------------- #
    def open(self) -> None:  # noqa: A003, B027 — optional hook, default no-op
        """Prepare the adapter (authenticate, warm caches). Default: no-op."""

    def close(self) -> None:  # noqa: B027 — optional hook, default no-op
        """Release resources. Default: no-op."""

    # ---- given / when: mutate domain state --------------------------------- #
    @abstractmethod
    def create_asset(
        self, entity: str, name: str, descriptor: str = "", sex: str = ""
    ) -> Handle:
        """Create an asset of a glossary ``entity`` kind; return its handle.

        ``sex`` is an optional domain trait (glossary ``ANIMAL_SEXES``); adapters
        for implementations without the notion ignore it.
        """

    @abstractmethod
    def record_log(
        self,
        kind: str,
        name: str,
        status: str,
        asset_handles: list[Handle],
        quantities: list[QuantitySpec],
    ) -> Handle:
        """Record a log of ``kind`` against assets, with quantities; return handle."""

    @abstractmethod
    def set_log_status(self, log_handle: Handle, status: str) -> None:
        """Transition a recorded log's lifecycle status (pending <-> done)."""

    @abstractmethod
    def assign_to_group(self, asset_handle: Handle, group_handle: Handle) -> None:
        """Make ``asset`` a member of ``group`` (domain membership)."""

    @abstractmethod
    def archive_asset(self, asset_handle: Handle) -> None:
        """Retire an asset from the active set."""

    # ---- then: read back delivered VALUES ---------------------------------- #
    @abstractmethod
    def asset_yield_total(
        self, asset_handle: Handle, measure: str, unit: str
    ) -> float:
        """Σ of ``measure`` across all recorded logs referencing the asset."""

    @abstractmethod
    def log_status(self, log_handle: Handle) -> str:
        """The lifecycle status delivered for a recorded log."""

    @abstractmethod
    def log_count(self, asset_handle: Handle, kind: str) -> int:
        """How many logs of ``kind`` reference the asset."""

    @abstractmethod
    def asset_active(self, asset_handle: Handle) -> bool:
        """Whether the asset is in the active (non-archived) set."""

    @abstractmethod
    def group_member(self, asset_handle: Handle, group_handle: Handle) -> bool:
        """Whether the asset is currently a member of the group."""

    @abstractmethod
    def quantity_recorded(
        self, log_handle: Handle, measure: str, unit: str
    ) -> float:
        """The value of a ``measure`` quantity recorded on a specific log."""

    # ---- extension surface -------------------------------------------------- #
    # Operations beyond the original core. They are NOT abstract on purpose: an
    # adapter for an implementation that does not offer a capability must be able
    # to exist and say so loudly at the point of use, rather than fail to
    # instantiate. Every default here raises, so an unimplemented capability can
    # never be mistaken for an observed value.
    def _unsupported(self, op: str) -> AdapterError:
        return AdapterError(f"adapter {self.name!r} does not support {op!r}")

    # --- stock / inventory --------------------------------------------------- #
    def record_inventory_adjustment(
        self,
        adjustment: str,
        name: str,
        status: str,
        asset_handles: list[Handle],
        quantities: list[QuantitySpec],
        effective_time: Any = None,
    ) -> Handle:
        """Adjust the stock held by assets (``increment``/``decrement``/``reset``)."""
        raise self._unsupported("record_inventory_adjustment")

    def set_effective_time(self, log_handle: Handle, effective_time: Any) -> None:
        """Restate when a recorded event took effect."""
        raise self._unsupported("set_effective_time")

    def stock_on_hand(self, asset_handle: Handle, measure: str, unit: str) -> float:
        """The stock the asset currently holds for one (measure, unit) pair."""
        raise self._unsupported("stock_on_hand")

    def stock_pair_count(self, asset_handle: Handle) -> int:
        """How many (measure, unit) pairs the asset reports stock for."""
        raise self._unsupported("stock_pair_count")

    def adjustment_count(self, asset_handle: Handle) -> int:
        """How many stock adjustments are readable against the asset."""
        raise self._unsupported("adjustment_count")

    # --- lineage ------------------------------------------------------------- #
    def record_birth(
        self,
        child_handle: Handle,
        parent_handles: list[Handle],
        name: str,
        status: str,
        effective_time: Any = None,
    ) -> Handle:
        """Register the birth of an animal, optionally issuing from a parent."""
        raise self._unsupported("record_birth")

    def correct_birth(
        self,
        birth_handle: Handle,
        parent_handles: list[Handle] | None = None,
        effective_time: Any = None,
    ) -> None:
        """Restate an already-recorded birth (its time and/or its parent)."""
        raise self._unsupported("correct_birth")

    def set_parents(
        self, animal_handle: Handle, parent_handles: list[Handle]
    ) -> None:
        """State an animal's parentage directly (full replacement)."""
        raise self._unsupported("set_parents")

    def set_nicknames(self, animal_handle: Handle, names: list[str]) -> None:
        """State an animal's ordered informal names (full replacement)."""
        raise self._unsupported("set_nicknames")

    def animal_sex(self, animal_handle: Handle) -> str:
        """The sex delivered for an animal ("" when none is delivered)."""
        raise self._unsupported("animal_sex")

    def nicknames(self, animal_handle: Handle) -> list[str]:
        """The ordered informal names delivered for an animal."""
        raise self._unsupported("nicknames")

    def birth_date(self, animal_handle: Handle) -> str:
        """The date of birth delivered for an animal ("" when none)."""
        raise self._unsupported("birth_date")

    def parent_count(self, animal_handle: Handle) -> int:
        """How many parents the animal is delivered with."""
        raise self._unsupported("parent_count")

    def has_parent(self, animal_handle: Handle, parent_handle: Handle) -> bool:
        """Whether one animal is delivered as another's parent."""
        raise self._unsupported("has_parent")

    def birth_record_count(self, animal_handle: Handle) -> int:
        """How many birth records claim this animal as issue."""
        raise self._unsupported("birth_record_count")
