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
    def create_asset(self, entity: str, name: str, descriptor: str = "") -> Handle:
        """Create an asset of a glossary ``entity`` kind; return its handle."""

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
