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
        lot_number: str = "",
        equipment_handles: list[Handle] | None = None,
        lab_received_date: str = "",
        lab_processed_date: str = "",
        lab_test_type: str = "",
        soil_texture: str = "",
        lab: str = "",
    ) -> Handle:
        """Record a log of ``kind`` against assets, with quantities; return handle.

        ``lot_number`` (MetaCoding-xdt) is an optional lot/batch identifier the
        log states. ``equipment_handles`` (MetaCoding-1cv) are the equipment
        assets the log states as used — the multi-valued ``equipment`` base
        field farm_equipment adds to every log. The ``lab_test`` bundle fields
        (MetaCoding-wgy) — two ISO-8601 date strings, the sample-type and
        soil-texture strings, and a laboratory NAME — are the fields
        farm_lab_test declares on the ``lab_test`` log. The interpreter only
        passes each when the step sets it, so adapters written before these
        fields existed keep working unchanged.
        """

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

    # --- taxonomy-term write surface (MetaCoding plant-type) ----------------- #
    def create_plant_type_term(
        self, name: str, maturity_days: int | None = None,
        harvest_days: int | None = None, crop_family: str = "",
        companions: list[str] | None = None,
    ) -> Handle:
        """Create a plant_type TERM carrying its planning fields; return its handle.

        The plant_type identity port asserts fields that live ON the term
        (farm_plant_type), so ``given`` must be able to instantiate one. The two
        day counts are integer term fields; ``crop_family`` is a crop_family term
        NAME and ``companions`` are plant_type term NAMES the adapter
        resolves/creates (each field's own auto_create is false, so the adapter
        ensures the referenced terms exist) — never per-run UUIDs. Non-abstract
        so an adapter for an implementation without the vocabulary can exist and
        say so loudly at the point of use, never fake a term.
        """
        raise self._unsupported("create_plant_type_term")

    def create_sensor_asset(
        self, name: str, data_streams: list[str] | None = None,
        private_key: str = "", public: bool | None = None,
    ) -> Handle:
        """Create a sensor ASSET carrying its bundle fields; return its handle.

        The sensor identity port (MetaCoding-ej0) asserts fields that live ON
        the asset (farm_sensor), so ``given`` must be able to instantiate one.
        ``data_streams`` are data_stream entity NAMES the adapter
        resolves/creates in stated order — never per-run UUIDs. ``private_key``
        is passed verbatim only when stated (an unstated key is minted by the
        implementation and can never reproduce). ``public`` is tri-state:
        ``None`` means unstated, never false. Non-abstract so an adapter for an
        implementation without sensors can exist and say so loudly at the point
        of use, never fake an asset.
        """
        raise self._unsupported("create_sensor_asset")

    def quantities_of(self, log_handle: Handle) -> list[Handle]:
        """The handles of the quantities a recorded log owns, in the order the
        log states them (which is the order ``record_log`` received them).

        A handle-resolution MECHANISM, not a probe: the interpreter calls it
        once after ``record_log`` to bind the quantity aliases a flow declares
        (MetaCoding-xdt), so ``delete_quantity`` can target one recorded
        quantity. It delivers no value an assertion could score.
        """
        raise self._unsupported("quantities_of")

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

    # --- generated: lot_number (assertion, PROVISIONAL) --- #
    def lot_number(self, subject_handle: Handle) -> Any:
        """Deliver the recorded lot number value for the subject record, or no value when no lot number was recorded.

        Generated stub — raises until an implementation exists. A stub
        that returned a constant could be mistaken for an observed value.
        """
        raise self._unsupported("lot_number")

    # --- generated: material_quantity (assertion, PROVISIONAL) --- #
    def material_quantity(self, subject_handle: Handle) -> Any:
        """Delivers the classification value of the measured quantity recorded on the log, so an assertion can determine whether that quantity is material.

        Generated stub — raises until an implementation exists. A stub
        that returned a constant could be mistaken for an observed value.
        """
        raise self._unsupported("material_quantity")

    # --- generated: delete_log (action, PROVISIONAL) --- #
    def delete_log(self, subject_handle: Handle) -> Any:
        """Perform the deletion of the recorded log at the source's write boundary; the log ceases to exist and no value is delivered.

        Generated stub — raises until an implementation exists. A stub
        that returned a constant could be mistaken for an observed value.
        """
        raise self._unsupported("delete_log")

    # --- generated: delete_quantity (action, PROVISIONAL) --- #
    def delete_quantity(self, subject_handle: Handle) -> Any:
        """Perform the deletion of the recorded quantity at the source's write boundary; the quantity ceases to exist and no value is delivered.

        Generated stub — raises until an implementation exists. A stub
        that returned a constant could be mistaken for an observed value.
        """
        raise self._unsupported("delete_quantity")

    # --- birth_mother (assertion, PROVISIONAL) — has_parent-shaped --- #
    def birth_mother(self, subject_handle: Handle, other_handle: Handle) -> bool:
        """Deliver whether ``other`` is the animal recorded as the mother on the birth log, so an assertion can confirm the recorded dam against an expected animal.

        Generated stub — raises until an implementation exists. A stub
        that returned a constant could be mistaken for an observed value.
        """
        raise self._unsupported("birth_mother")

    # --- generated: equipment_used (assertion, PROVISIONAL) --- #
    def equipment_used(self, subject_handle: Handle, other_handle: Handle) -> Any:
        """Deliver whether a given equipment asset is among the equipment the subject log records as used, so an assertion can confirm the recorded 'Equipment used' reference against an expected asset.

        Generated stub — raises until an implementation exists. A stub
        that returned a constant could be mistaken for an observed value.
        """
        raise self._unsupported("equipment_used")

    # --- generated: material_type_recorded (assertion, PROVISIONAL) --- #
    def material_type_recorded(self, subject_handle: Handle) -> Any:
        """Deliver the ordered material_type term names recorded on the first material-classified quantity of the subject log, or an empty list when the log carries no material quantity or the quantity records no material type — the observable of the quantity_presave denormalizing fold.

        Generated stub — raises until an implementation exists. A stub
        that returned a constant could be mistaken for an observed value.
        """
        raise self._unsupported("material_type_recorded")

    # --- generated: lab_sample_type (assertion, PROVISIONAL) --- #
    def lab_sample_type(self, subject_handle: Handle) -> Any:
        """Deliver the sample category recorded on the subject lab-test log (the lab_test_type value, e.g. soil, tissue, or water), or an empty value when none was recorded.

        Generated stub — raises until an implementation exists. A stub
        that returned a constant could be mistaken for an observed value.
        """
        raise self._unsupported("lab_sample_type")

    # --- generated: laboratory (assertion, PROVISIONAL) --- #
    def laboratory(self, subject_handle: Handle) -> Any:
        """Deliver the name of the laboratory recorded as having performed the subject lab test (the log's lab reference), or an empty value when none was recorded.

        Generated stub — raises until an implementation exists. A stub
        that returned a constant could be mistaken for an observed value.
        """
        raise self._unsupported("laboratory")

    # --- generated: lab_test_measurement (assertion, PROVISIONAL) --- #
    def lab_test_measurement(self, subject_handle: Handle) -> Any:
        """Deliver the ordered test_method term names recorded on the first test-classified quantity of the subject lab-test log, or an empty list when the log carries no test measurement or the measurement records no method.

        Generated stub — raises until an implementation exists. A stub
        that returned a constant could be mistaken for an observed value.
        """
        raise self._unsupported("lab_test_measurement")

    # --- generated: lab_processing_date (assertion, PROVISIONAL) --- #
    def lab_processing_date(self, subject_handle: Handle) -> Any:
        """Deliver the recorded date on which the laboratory processed the sample for the subject lab test (the log's lab_processed_date), or an empty value when none was recorded.

        Generated stub — raises until an implementation exists. A stub
        that returned a constant could be mistaken for an observed value.
        """
        raise self._unsupported("lab_processing_date")

    # --- generated: sample_received_date (assertion, PROVISIONAL) --- #
    def sample_received_date(self, subject_handle: Handle) -> Any:
        """Deliver the recorded date on which the laboratory received the sample for the subject lab test (the log's lab_received_date), or an empty value when none was recorded.

        Generated stub — raises until an implementation exists. A stub
        that returned a constant could be mistaken for an observed value.
        """
        raise self._unsupported("sample_received_date")

    # --- generated: soil_texture (assertion, PROVISIONAL) --- #
    def soil_texture(self, subject_handle: Handle) -> Any:
        """Deliver the soil texture string recorded on the subject lab test (the log's soil_texture), or an empty value when none was recorded.

        Generated stub — raises until an implementation exists. A stub
        that returned a constant could be mistaken for an observed value.
        """
        raise self._unsupported("soil_texture")

    # --- generated: days_to_maturity (assertion, PROVISIONAL) --- #
    def days_to_maturity(self, subject_handle: Handle) -> Any:
        """Deliver the integer days-to-maturity recorded on the subject plant_type TERM (the term's maturity_days integer field), or the empty value when none was recorded.

        Generated stub — raises until an implementation exists. A stub
        that returned a constant could be mistaken for an observed value.
        """
        raise self._unsupported("days_to_maturity")

    # --- generated: days_to_harvest (assertion, PROVISIONAL) --- #
    def days_to_harvest(self, subject_handle: Handle) -> Any:
        """Deliver the integer days-of-harvest recorded on the subject plant_type TERM (the term's harvest_days integer field), or the empty value when none was recorded.

        Generated stub — raises until an implementation exists. A stub
        that returned a constant could be mistaken for an observed value.
        """
        raise self._unsupported("days_to_harvest")

    # --- generated: companion_plants (assertion, PROVISIONAL) --- #
    def companion_plants(self, subject_handle: Handle) -> Any:
        """Deliver the ordered NAMES of the plant_type terms the subject plant_type TERM references as companions (its multi-valued companions reference), or the empty list when none were recorded.

        Generated stub — raises until an implementation exists. A stub
        that returned a constant could be mistaken for an observed value.
        """
        raise self._unsupported("companion_plants")

    # --- generated: crop_family (assertion, PROVISIONAL) --- #
    def crop_family(self, subject_handle: Handle) -> Any:
        """Deliver the NAME of the crop_family term the subject plant_type TERM references (its single-valued crop_family reference), or the empty value when none was recorded.

        Generated stub — raises until an implementation exists. A stub
        that returned a constant could be mistaken for an observed value.
        """
        raise self._unsupported("crop_family")

    # --- generated: sensor_data_stream (assertion, PROVISIONAL) --- #
    def sensor_data_stream(self, subject_handle: Handle) -> Any:
        """Deliver the ordered NAMES of the data_stream entities the subject sensor ASSET references (its multi-valued data_stream reference), or the empty value when none was recorded.

        Generated stub — raises until an implementation exists. A stub
        that returned a constant could be mistaken for an observed value.
        """
        raise self._unsupported("sensor_data_stream")

    # --- generated: sensor_private_key (assertion, PROVISIONAL) --- #
    def sensor_private_key(self, subject_handle: Handle) -> Any:
        """Deliver the sensor ASSET's private_key string verbatim as recorded. Only explicitly-recorded keys are scoreable: when no key was stated the oracle MINTS a random one, which is machine-generated per instance and therefore unanswerable, never an empty value.

        Generated stub — raises until an implementation exists. A stub
        that returned a constant could be mistaken for an observed value.
        """
        raise self._unsupported("sensor_private_key")

    # --- generated: publicly_readable (assertion, PROVISIONAL) --- #
    def publicly_readable(self, subject_handle: Handle) -> Any:
        """Deliver the sensor ASSET's public flag verbatim as recorded: true reads true, false reads false (false is a recorded value, distinct from absent), and an unstated flag is the empty value.

        Generated stub — raises until an implementation exists. A stub
        that returned a constant could be mistaken for an observed value.
        """
        raise self._unsupported("publicly_readable")
