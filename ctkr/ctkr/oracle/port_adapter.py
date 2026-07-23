"""Drive a BUILT PORT through a line-delimited JSON bridge process.

The port is not Python. It is whatever the build produced — a Bun/TypeScript
module, a Rust binary, a Go service. So the adapter for a port is a *process*
adapter: it starts the port's own bridge (declared in ``port.manifest.json``),
speaks one JSON object per line over stdin/stdout, and maps
:class:`~ctkr.oracle.adapter.ImplementationAdapter` calls onto it. The bridge is
part of the port, written once by whoever built it, and is the only code that
knows the port's internals.

Protocol — request, one line of JSON on stdin::

    {"id": 7, "op": "stock_on_hand", "asset": "h1", "measure": "weight",
     "unit": "kilograms"}

Response, one line of JSON on stdout::

    {"id": 7, "ok": true, "value": 3.0}
    {"id": 7, "ok": false, "error": "...", "unsupported": true}

Three ops are protocol-level rather than domain-level: ``describe`` (the port
states its capabilities at run time), ``reset`` (drop all state — fixtures are
independent), and ``close``.

**The honesty rule this module enforces:** a method whose glossary term the port
did not declare is never called and never guessed. It raises
:class:`Unanswerable`, which ``port-verify`` records as a declared gap. A method
the port DID declare but whose bridge answers ``unsupported`` is a different and
worse thing — a false declaration — and raises :class:`FalseDeclaration`, which
is a failure, not a gap.
"""

from __future__ import annotations

import json
import queue
import subprocess
import threading
from datetime import datetime
from typing import Any

from ctkr.oracle.adapter import AdapterError, Handle, ImplementationAdapter
from ctkr.oracle.fixtures import QuantitySpec
from ctkr.oracle.port_contract import PortCapabilities, PortManifest
from ctkr.oracle.probes import PROBE_CONTRACT

#: The reader-side ceiling on ``BridgeSpec.timeout``, in seconds. The manifest's
#: timeout is written by the port; a port may ask the reader to wait LESS than
#: this, never more (MetaCoding-i48). 30s is the BridgeSpec default and an order
#: of magnitude above every observed honest bridge answer.
PATIENCE_CAP = 30.0


class Unanswerable(RuntimeError):
    """The port declared no surface able to answer this — a gap, never a pass.

    Deliberately NOT an :class:`AdapterError`: an adapter error is a failure of
    an operation the implementation claims to support, while this is the absence
    of a claim. Conflating them is exactly how thirteen unanswerable assertions
    became part of a "24/30".
    """


class FalseDeclaration(AdapterError):
    """The port declared a capability its bridge then refused to perform."""


class BridgeError(AdapterError):
    """The bridge process died, timed out, or spoke nonsense."""


def _epoch_ms(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return int(value.timestamp() * 1000)
    if isinstance(value, (int, float)):
        return int(value)
    raise BridgeError(f"cannot express effective time {value!r} as an instant")


class PortBridge:
    """A line-delimited JSON conversation with the port's bridge process."""

    def __init__(self, manifest: PortManifest) -> None:
        self.manifest = manifest
        self._proc: subprocess.Popen[str] | None = None
        self._next_id = 0
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._reader: threading.Thread | None = None
        #: Set once a deadline expires. INVARIANT 3: a bridge that stopped
        #: answering is not answering *later*, it is NO VERDICT — and every
        #: subsequent call must say so immediately rather than waiting again.
        self._dead: str = ""

    def start(self) -> None:
        if self._dead:
            raise BridgeError(self._dead)
        if self._proc is not None:
            return
        spec = self.manifest.bridge
        try:
            self._proc = subprocess.Popen(  # noqa: S603 — command is declared data
                spec.command,
                cwd=str(self.manifest.bridge_cwd()),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=self._env(),
            )
        except OSError as exc:
            raise BridgeError(
                f"could not start port bridge {spec.command!r} in "
                f"{self.manifest.bridge_cwd()}: {exc}"
            ) from exc
        self._reader = threading.Thread(
            target=self._pump, args=(self._proc.stdout,), daemon=True
        )
        self._reader.start()

    def _pump(self, stdout: Any) -> None:
        """Read the bridge's lines off-thread so a read can carry a DEADLINE.

        ``proc.stdout.readline()`` has no timeout, and ``BridgeSpec.timeout`` was
        applied only to ``proc.wait()`` at shutdown. A bridge that accepted a
        request and then slept consumed the caller's entire tool timeout and
        produced NO verdict — the worst outcome for an orchestrator waiting on N
        results, because a missing answer is indistinguishable from a slow one.
        """
        try:
            for line in iter(stdout.readline, ""):
                self._lines.put(line)
        except Exception:  # noqa: BLE001 — the pipe closing is not an error here
            pass
        finally:
            self._lines.put(None)

    def _env(self) -> dict[str, str] | None:
        if not self.manifest.bridge.env:
            return None
        import os

        return {**os.environ, **self.manifest.bridge.env}

    def call(self, op: str, **payload: Any) -> Any:
        self.start()
        proc = self._proc
        assert proc is not None and proc.stdin is not None and proc.stdout is not None
        self._next_id += 1
        req = {"id": self._next_id, "op": op, **payload}
        try:
            proc.stdin.write(json.dumps(req) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, ValueError) as exc:
            raise BridgeError(f"port bridge closed its input during {op!r}: {exc}") from exc
        deadline = self._deadline()
        try:
            line = self._lines.get(timeout=deadline)
        except queue.Empty:
            self._kill(
                f"port bridge did not answer {op!r} within {deadline}s "
                f"(BridgeSpec.timeout, capped at {PATIENCE_CAP}s reader-side). "
                f"A silent bridge is NO VERDICT, not a pending one — the reader "
                f"does not wait on the party it reads."
            )
            raise BridgeError(self._dead) from None
        if line is None:
            err = proc.stderr.read() if proc.stderr else ""
            raise BridgeError(
                f"port bridge produced no answer to {op!r} "
                f"(exit={proc.poll()}): {err.strip()[:2000]}"
            )
        try:
            resp = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BridgeError(f"port bridge answered {op!r} with non-JSON: {line!r}") from exc
        # Correlation is MANDATORY. Accepting `id: None` made correlation
        # opt-out by the defendant: a bridge that omits the field may answer out
        # of order, including replaying a previous fixture's correct answer.
        if resp.get("id") != req["id"]:
            raise BridgeError(
                f"port bridge answered id {resp.get('id')!r} to request "
                f"{req['id']} — every response must echo its request id; an "
                f"uncorrelated answer could belong to any question"
            )
        if not resp.get("ok"):
            msg = str(resp.get("error", "unspecified bridge error"))
            if resp.get("unanswerable"):
                # PER-CALL gap: the port implements this probe in general but
                # cannot answer THIS input (e.g. it has no row for an asset that
                # was never adjusted, where the source reports 0.0). Without this
                # channel the only unpunished move was to FABRICATE a value —
                # every honest alternative scored as a failure or a false
                # declaration — which reproduced, one level down, exactly the
                # silent-pass this tool exists to eliminate.
                raise Unanswerable(f"{op}: {msg}")
            if resp.get("unsupported"):
                raise FalseDeclaration(
                    f"port declared {op!r} but its bridge refuses it: {msg}"
                )
            raise AdapterError(f"{op}: {msg}")
        return resp.get("value")

    def _deadline(self) -> float:
        """The reader's patience: the port may ask for LESS, never for more.

        ``BridgeSpec.timeout`` lives in the port's own manifest. Uncapped, the
        reader's patience was a parameter written by the party being read — a
        bridge declaring ``"timeout": 86400.0`` reproduced the original
        hang-forever (exit 124, no verdict) that the deadline exists to prevent
        (MetaCoding-i48). The cap is the reader's, not the manifest's.
        """
        return min(self.manifest.bridge.timeout, PATIENCE_CAP)

    def _kill(self, reason: str) -> None:
        """Kill the child and remember why. No further call waits on it."""
        self._dead = reason
        proc, self._proc = self._proc, None
        if proc is not None:
            proc.kill()
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream:
                    try:
                        stream.close()
                    except Exception:  # noqa: BLE001
                        pass

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                try:
                    proc.stdin.write(json.dumps({"op": "close"}) + "\n")
                    proc.stdin.flush()
                except (BrokenPipeError, ValueError):
                    pass
                proc.stdin.close()
            proc.wait(timeout=self._deadline())
        except subprocess.TimeoutExpired:
            proc.kill()
        finally:
            for stream in (proc.stdout, proc.stderr):
                if stream:
                    stream.close()


class PortAdapter(ImplementationAdapter):
    """An :class:`ImplementationAdapter` over a declared, bridged port.

    Every method first asks the declaration "did the port claim this?" and, when
    it did not, raises :class:`Unanswerable` *without touching the bridge*. There
    is no code path from an undeclared capability to a value.
    """

    def __init__(self, manifest: PortManifest, bridge: Any | None = None) -> None:
        self.manifest = manifest
        self.name = f"port:{manifest.port}"
        self._bridge = bridge if bridge is not None else PortBridge(manifest)
        self._declared: PortCapabilities = manifest.capabilities
        self.runtime_capabilities: PortCapabilities | None = None

    # ---- lifecycle --------------------------------------------------------- #
    def open(self) -> None:  # noqa: A003
        described = self._bridge.call("describe")
        if not isinstance(described, dict):
            # A bridge that cannot describe itself is unusable — fail as a bridge
            # error rather than an AttributeError three frames deep.
            raise BridgeError(
                f"port bridge answered 'describe' with {type(described).__name__} "
                f"{described!r}; expected an object with 'operations' and 'probes'"
            )
        runtime = PortCapabilities.model_validate(
            {
                "operations": list(described.get("operations", [])),
                "probes": list(described.get("probes", [])),
            }
        )
        unknown = runtime.unknown_terms()
        if unknown:
            raise BridgeError(
                f"port bridge describes terms outside the glossary: {'; '.join(unknown)}"
            )
        m_ops, m_probes = self._declared.as_sets()
        r_ops, r_probes = runtime.as_sets()
        if (m_ops, m_probes) != (r_ops, r_probes):
            raise BridgeError(
                "port manifest and running bridge disagree about the probe surface "
                f"(manifest operations={sorted(m_ops)} probes={sorted(m_probes)}; "
                f"bridge operations={sorted(r_ops)} probes={sorted(r_probes)}). "
                "Refusing to pick one: a capability claim must be unambiguous."
            )
        self.runtime_capabilities = runtime

    def close(self) -> None:
        self._bridge.stop()

    def reset(self) -> None:
        """Drop all port state — called between fixtures so they cannot interact."""
        self._bridge.call("reset")

    # ---- declaration gate --------------------------------------------------- #
    def declares_operation(self, action: str) -> bool:
        return action in set(self._declared.operations)

    def declares_probe(self, assertion: str) -> bool:
        return assertion in set(self._declared.probes)

    def _need_operation(self, action: str) -> None:
        if not self.declares_operation(action):
            raise Unanswerable(
                f"port {self.manifest.port!r} declares no operation {action!r}"
            )

    def _need_probe(self, assertion: str) -> None:
        if self.declares_probe(assertion):
            return
        spec = PROBE_CONTRACT.get(assertion)
        needs = f" (would need adapter method {spec.method!r})" if spec else ""
        raise Unanswerable(
            f"port {self.manifest.port!r} declares no probe {assertion!r}{needs}"
        )

    # ---- given / when ------------------------------------------------------- #
    def create_asset(
        self, entity: str, name: str, descriptor: str = "", sex: str = ""
    ) -> Handle:
        # create_asset backs every `given`; a port that cannot make entities
        # cannot be verified at all, so this is not gated on an action term.
        return str(
            self._bridge.call(
                "create_asset", entity=entity, name=name,
                descriptor=descriptor, sex=sex,
            )
        )

    def create_plant_type_term(
        self, name: str, maturity_days: int | None = None,
        harvest_days: int | None = None, crop_family: str = "",
        companions: list[str] | None = None,
    ) -> Handle:
        # Backs a plant_type `given` (MetaCoding plant-type). Like create_asset,
        # not gated on a declared term: a port that cannot make plant_type terms
        # cannot be verified on this feature at all, so it fails the call loudly
        # at the point of use rather than being silently skipped. The planning
        # fields ride only when stated, so a bridge sees a stable payload.
        return str(self._bridge.call(
            "create_plant_type_term", name=name,
            **({"maturity_days": maturity_days} if maturity_days is not None else {}),
            **({"harvest_days": harvest_days} if harvest_days is not None else {}),
            **({"crop_family": crop_family} if crop_family else {}),
            **({"companions": list(companions)} if companions else {}),
        ))

    def create_sensor_asset(
        self, name: str, data_streams: list[str] | None = None,
        private_key: str = "", public: bool | None = None,
    ) -> Handle:
        # Backs a sensor `given` (MetaCoding-ej0). Like create_plant_type_term,
        # not gated on a declared term: a port that cannot make sensor assets
        # cannot be verified on this feature at all, so it fails the call
        # loudly at the point of use rather than being silently skipped. The
        # bundle fields ride only when STATED — public is tri-state, so False
        # rides (a recorded value, distinct from absent) and only None stays
        # off the wire; dropping that distinction here would collapse the
        # pack's false-vs-"" contrast. The fresh reading of the first build
        # caught this method missing entirely (fixtures 0/14, every given
        # dying at the base _unsupported before the bridge was consulted).
        return str(self._bridge.call(
            "create_sensor_asset", name=name,
            **({"data_streams": list(data_streams)} if data_streams else {}),
            **({"private_key": private_key} if private_key else {}),
            **({"public": public} if public is not None else {}),
        ))

    def record_log(
        self, kind: str, name: str, status: str,
        asset_handles: list[Handle], quantities: list[QuantitySpec],
        lot_number: str = "",
        equipment_handles: list[Handle] | None = None,
        lab_received_date: str = "",
        lab_processed_date: str = "",
        lab_test_type: str = "",
        soil_texture: str = "",
        lab: str = "",
    ) -> Handle:
        self._need_operation("record_log")
        # lab_test bundle fields (MetaCoding-wgy) — only on the wire when
        # stated (test_method rides inside each quantity's model_dump).
        lab_fields = {
            k: v for k, v in (
                ("lab_received_date", lab_received_date),
                ("lab_processed_date", lab_processed_date),
                ("lab_test_type", lab_test_type),
                ("soil_texture", soil_texture),
                ("lab", lab),
            ) if v
        }
        return str(self._bridge.call(
            "record_log", kind=kind, name=name, status=status,
            assets=list(asset_handles),
            quantities=[q.model_dump() for q in quantities],
            # Only on the wire when stated, so bridges written before these
            # fields existed see the exact payload they always saw
            # (MetaCoding-xdt lot_number; MetaCoding-1cv equipment).
            **({"lot_number": lot_number} if lot_number else {}),
            **({"equipment": list(equipment_handles)}
               if equipment_handles else {}),
            **lab_fields,
        ))

    def quantities_of(self, log_handle: Handle) -> list[Handle]:
        # A handle-resolution mechanism (like create_asset), not a glossary
        # term: invoked only when a flow declares quantity aliases; a bridge
        # without the op fails the call loudly at the point of use.
        got = self._bridge.call("quantities_of", log=log_handle)
        if not isinstance(got, list):
            raise BridgeError(
                f"port bridge answered 'quantities_of' with "
                f"{type(got).__name__} {got!r}; expected a list of handles"
            )
        return [str(h) for h in got]

    def delete_log(self, subject_handle: Handle) -> Any:
        self._need_operation("delete_log")
        return self._bridge.call("delete_log", log=subject_handle)

    def equipment_used(self, subject_handle: Handle, other_handle: Handle) -> bool:
        self._need_probe("equipment_used")
        return bool(self._bridge.call(
            "equipment_used", log=subject_handle, other=other_handle))

    def material_type_recorded(self, subject_handle: Handle) -> list[str]:
        self._need_probe("material_type_recorded")
        got = self._bridge.call("material_type_recorded", log=subject_handle)
        if not isinstance(got, list):
            raise BridgeError(
                f"port bridge answered 'material_type_recorded' with "
                f"{type(got).__name__} {got!r}; expected a list of names"
            )
        return [str(n) for n in got]

    # --- lab_test bundle-field probes (MetaCoding-wgy) ---------------------- #
    # Five scalar readbacks (four boundary transcriptions plus the laboratory
    # NAME) and one ordered-names fold, dispatched to the port bridge exactly
    # like material_type_recorded. The base ImplementationAdapter raises
    # _unsupported for these; a PortAdapter answers them from its declared,
    # bridged surface.
    def lab_sample_type(self, subject_handle: Handle) -> str:
        self._need_probe("lab_sample_type")
        return str(self._bridge.call("lab_sample_type", log=subject_handle))

    def laboratory(self, subject_handle: Handle) -> str:
        self._need_probe("laboratory")
        return str(self._bridge.call("laboratory", log=subject_handle))

    def lab_processing_date(self, subject_handle: Handle) -> str:
        self._need_probe("lab_processing_date")
        return str(self._bridge.call("lab_processing_date", log=subject_handle))

    def sample_received_date(self, subject_handle: Handle) -> str:
        self._need_probe("sample_received_date")
        return str(self._bridge.call("sample_received_date", log=subject_handle))

    def soil_texture(self, subject_handle: Handle) -> str:
        self._need_probe("soil_texture")
        return str(self._bridge.call("soil_texture", log=subject_handle))

    def lab_test_measurement(self, subject_handle: Handle) -> list[str]:
        self._need_probe("lab_test_measurement")
        got = self._bridge.call("lab_test_measurement", log=subject_handle)
        if not isinstance(got, list):
            raise BridgeError(
                f"port bridge answered 'lab_test_measurement' with "
                f"{type(got).__name__} {got!r}; expected a list of names"
            )
        return [str(n) for n in got]

    def delete_quantity(self, subject_handle: Handle) -> Any:
        self._need_operation("delete_quantity")
        return self._bridge.call("delete_quantity", quantity=subject_handle)

    def set_log_status(self, log_handle: Handle, status: str) -> None:
        self._need_operation("set_log_status")
        self._bridge.call("set_log_status", log=log_handle, status=status)

    def assign_to_group(self, asset_handle: Handle, group_handle: Handle) -> None:
        self._need_operation("assign_to_group")
        self._bridge.call("assign_to_group", asset=asset_handle, group=group_handle)

    def archive_asset(self, asset_handle: Handle) -> None:
        self._need_operation("archive_asset")
        self._bridge.call("archive_asset", asset=asset_handle)

    def record_inventory_adjustment(
        self, adjustment: str, name: str, status: str,
        asset_handles: list[Handle], quantities: list[QuantitySpec],
        effective_time: Any = None,
    ) -> Handle:
        self._need_operation("record_inventory_adjustment")
        return str(self._bridge.call(
            "record_inventory_adjustment", adjustment=adjustment, name=name,
            status=status, assets=list(asset_handles),
            quantities=[q.model_dump() for q in quantities],
            effective_time=_epoch_ms(effective_time),
        ))

    def set_effective_time(self, log_handle: Handle, effective_time: Any) -> None:
        self._need_operation("set_effective_time")
        self._bridge.call(
            "set_effective_time", log=log_handle,
            effective_time=_epoch_ms(effective_time),
        )

    def record_birth(
        self, child_handle: Handle, parent_handles: list[Handle],
        name: str, status: str, effective_time: Any = None,
    ) -> Handle:
        self._need_operation("record_birth")
        return str(self._bridge.call(
            "record_birth", child=child_handle, parents=list(parent_handles),
            name=name, status=status, effective_time=_epoch_ms(effective_time),
        ))

    def correct_birth(
        self, birth_handle: Handle, parent_handles: list[Handle] | None = None,
        effective_time: Any = None,
    ) -> None:
        self._need_operation("correct_birth")
        self._bridge.call(
            "correct_birth", birth=birth_handle,
            parents=None if parent_handles is None else list(parent_handles),
            effective_time=_epoch_ms(effective_time),
        )

    def set_parents(self, animal_handle: Handle, parent_handles: list[Handle]) -> None:
        self._need_operation("set_parents")
        self._bridge.call("set_parents", animal=animal_handle,
                          parents=list(parent_handles))

    def set_nicknames(self, animal_handle: Handle, names: list[str]) -> None:
        self._need_operation("set_nicknames")
        self._bridge.call("set_nicknames", animal=animal_handle, names=list(names))

    # ---- then: probes ------------------------------------------------------- #
    def asset_yield_total(self, asset_handle: Handle, measure: str, unit: str) -> float:
        self._need_probe("yield_total")
        return float(self._bridge.call(
            "yield_total", asset=asset_handle, measure=measure, unit=unit))

    def log_status(self, log_handle: Handle) -> str:
        self._need_probe("log_status")
        return str(self._bridge.call("log_status", log=log_handle))

    def log_count(self, asset_handle: Handle, kind: str) -> int:
        self._need_probe("log_count")
        return int(self._bridge.call("log_count", asset=asset_handle, kind=kind))

    def asset_active(self, asset_handle: Handle) -> bool:
        self._need_probe("asset_active")
        return bool(self._bridge.call("asset_active", asset=asset_handle))

    def group_member(self, asset_handle: Handle, group_handle: Handle) -> bool:
        self._need_probe("group_member")
        return bool(self._bridge.call(
            "group_member", asset=asset_handle, group=group_handle))

    def quantity_recorded(self, log_handle: Handle, measure: str, unit: str) -> float:
        self._need_probe("quantity_recorded")
        return float(self._bridge.call(
            "quantity_recorded", log=log_handle, measure=measure, unit=unit))

    def stock_on_hand(self, asset_handle: Handle, measure: str, unit: str) -> float:
        self._need_probe("stock_on_hand")
        return float(self._bridge.call(
            "stock_on_hand", asset=asset_handle, measure=measure, unit=unit))

    def stock_pair_count(self, asset_handle: Handle) -> int:
        self._need_probe("stock_pair_count")
        return int(self._bridge.call("stock_pair_count", asset=asset_handle))

    def adjustment_count(self, asset_handle: Handle) -> int:
        self._need_probe("adjustment_count")
        return int(self._bridge.call("adjustment_count", asset=asset_handle))

    def animal_sex(self, animal_handle: Handle) -> str:
        self._need_probe("animal_sex")
        return str(self._bridge.call("animal_sex", animal=animal_handle))

    def nicknames(self, animal_handle: Handle) -> list[str]:
        self._need_probe("nicknames")
        return [str(n) for n in self._bridge.call("nicknames", animal=animal_handle)]

    def birth_date(self, animal_handle: Handle) -> str:
        self._need_probe("birth_date")
        return str(self._bridge.call("birth_date", animal=animal_handle))

    def parent_count(self, animal_handle: Handle) -> int:
        self._need_probe("parent_count")
        return int(self._bridge.call("parent_count", animal=animal_handle))

    def has_parent(self, animal_handle: Handle, parent_handle: Handle) -> bool:
        self._need_probe("has_parent")
        return bool(self._bridge.call(
            "has_parent", animal=animal_handle, parent=parent_handle))

    def birth_record_count(self, animal_handle: Handle) -> int:
        self._need_probe("birth_record_count")
        return int(self._bridge.call("birth_record_count", animal=animal_handle))

    # --- generated: days_to_maturity (assertion, PROVISIONAL) --- #
    def days_to_maturity(self, subject_handle: Handle) -> Any:
        """Deliver the integer days-to-maturity recorded on the subject plant_type TERM (the term's maturity_days integer field), or the empty value when none was recorded.

        Generated dispatch: forwards to the port's declared bridge op,
        gated on the port having declared it. Nothing to implement — the
        bridge the build produced answers, or the gate raises.
        """
        self._need_probe("days_to_maturity")
        return self._bridge.call("days_to_maturity", subject=subject_handle)

    # --- generated: days_to_harvest (assertion, PROVISIONAL) --- #
    def days_to_harvest(self, subject_handle: Handle) -> Any:
        """Deliver the integer days-of-harvest recorded on the subject plant_type TERM (the term's harvest_days integer field), or the empty value when none was recorded.

        Generated dispatch: forwards to the port's declared bridge op,
        gated on the port having declared it. Nothing to implement — the
        bridge the build produced answers, or the gate raises.
        """
        self._need_probe("days_to_harvest")
        return self._bridge.call("days_to_harvest", subject=subject_handle)

    # --- generated: companion_plants (assertion, PROVISIONAL) --- #
    def companion_plants(self, subject_handle: Handle) -> list[str]:
        """Deliver the ordered NAMES of the plant_type terms the subject plant_type TERM references as companions (its multi-valued companions reference), or the empty list when none were recorded.

        Generated dispatch: forwards to the port's declared bridge op,
        gated on the port having declared it. Nothing to implement — the
        bridge the build produced answers, or the gate raises.
        """
        self._need_probe("companion_plants")
        got = self._bridge.call("companion_plants", subject=subject_handle)
        if not isinstance(got, list):
            raise BridgeError(
                f"port bridge answered 'companion_plants' with "
                f"{type(got).__name__} {got!r}; expected a list of names"
            )
        return [str(n) for n in got]

    # --- generated: crop_family (assertion, PROVISIONAL) --- #
    def crop_family(self, subject_handle: Handle) -> Any:
        """Deliver the NAME of the crop_family term the subject plant_type TERM references (its single-valued crop_family reference), or the empty value when none was recorded.

        Generated dispatch: forwards to the port's declared bridge op,
        gated on the port having declared it. Nothing to implement — the
        bridge the build produced answers, or the gate raises.
        """
        self._need_probe("crop_family")
        return self._bridge.call("crop_family", subject=subject_handle)

    # --- generated: sensor_data_stream (assertion, PROVISIONAL) --- #
    def sensor_data_stream(self, subject_handle: Handle) -> Any:
        """Deliver the ordered NAMES of the data_stream entities the subject sensor ASSET references (its multi-valued data_stream reference), or the empty value when none was recorded.

        Generated dispatch: forwards to the port's declared bridge op,
        gated on the port having declared it. Nothing to implement — the
        bridge the build produced answers, or the gate raises.
        """
        self._need_probe("sensor_data_stream")
        return self._bridge.call("sensor_data_stream", subject=subject_handle)

    # --- generated: sensor_private_key (assertion, PROVISIONAL) --- #
    def sensor_private_key(self, subject_handle: Handle) -> Any:
        """Deliver the sensor ASSET's private_key string verbatim as recorded. Only explicitly-recorded keys are scoreable: when no key was stated the oracle MINTS a random one, which is machine-generated per instance and therefore unanswerable, never an empty value.

        Generated dispatch: forwards to the port's declared bridge op,
        gated on the port having declared it. Nothing to implement — the
        bridge the build produced answers, or the gate raises.
        """
        self._need_probe("sensor_private_key")
        return self._bridge.call("sensor_private_key", subject=subject_handle)

    # --- generated: publicly_readable (assertion, PROVISIONAL) --- #
    def publicly_readable(self, subject_handle: Handle) -> Any:
        """Deliver the sensor ASSET's public flag verbatim as recorded: true reads true, false reads false (false is a recorded value, distinct from absent), and an unstated flag is the empty value.

        Generated dispatch: forwards to the port's declared bridge op,
        gated on the port having declared it. Nothing to implement — the
        bridge the build produced answers, or the gate raises.
        """
        self._need_probe("publicly_readable")
        return self._bridge.call("publicly_readable", subject=subject_handle)

    # --- generated: structure_kind (assertion, PROVISIONAL) --- #
    def structure_kind(self, subject_handle: Handle) -> Any:
        """Deliver the structure ASSET's structure_type machine id verbatim as recorded (one of the closed set). Through the given write surface the value is never absent: the field is required at the boundary and an unstated descriptor falls back to 'other' in the adapter.

        Generated dispatch: forwards to the port's declared bridge op,
        gated on the port having declared it. Nothing to implement — the
        bridge the build produced answers, or the gate raises.
        """
        self._need_probe("structure_kind")
        return self._bridge.call("structure_kind", subject=subject_handle)
