"""The farmOS LENS — the one registered lens today.

This module is the *only* place that knows farmOS's vocabulary, probe contract
and adapter belong together. Everything it names still lives physically under
``ctkr/oracle/`` (``glossary.py``, ``probes.py``, ``farmos_adapter.py``,
``glossary_provenance.jsonl``) — relocating those files into a ``farmos_lens``
package outside this repo is a later slice of MetaCoding-1gt. What changed is
the DIRECTION: the instrument no longer imports any of them. This module
imports them and hands them over as a :class:`~ctkr.oracle.lens.Lens`.

It is a LENS FILE, not instrument code: ``tests/test_lens_boundary.py`` lists it
among the files allowed to import farmOS material.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ctkr.oracle import glossary
from ctkr.oracle.lens import Lens, Vocabulary
from ctkr.oracle.probes import OPERATION_CONTRACT, PROBE_CONTRACT


def build_client(
    base_url: str, username: str, password: str, *, recording: bool = True,
    client_id: str = "farm", client_secret: str = "", timeout: float = 30.0,
) -> Any:
    """Construct a (recording) farmOS client for the CLI + tests."""
    from ctkr.oracle.farmos_adapter import FarmOSClient, RecordingClient

    cls = RecordingClient if recording else FarmOSClient
    return cls(base_url, username, password, client_id=client_id,
               client_secret=client_secret, timeout=timeout)


def build_adapter(client: Any) -> Any:
    """Wrap a farmOS client in the value-level adapter the runner drives."""
    from ctkr.oracle.farmos_adapter import FarmOSAdapter

    return FarmOSAdapter(client)


#: Where ``add-term`` writes each kind of generated code for this lens. The
#: eight paths were hardcoded in ``term_codegen`` until MetaCoding-1gt; they are
#: the lens's business, because a second target's terms must land in a second
#: target's files.
CODEGEN_TARGETS: dict[str, str] = {
    "glossary": "ctkr/oracle/glossary.py",
    "probes": "ctkr/oracle/probes.py",
    "steps": "ctkr/oracle/steps.py",
    "adapter": "ctkr/oracle/adapter.py",
    "adapter_impl": "ctkr/oracle/farmos_adapter.py",
    "recorder": "ctkr/oracle/recorder.py",
    "fixtures": "ctkr/oracle/fixtures.py",
    "port_adapter": "ctkr/oracle/port_adapter.py",
}


LENS = Lens(
    name="farmos",
    vocabulary=Vocabulary.from_module(glossary),
    probe_contract=PROBE_CONTRACT,
    operation_contract=OPERATION_CONTRACT,
    build_client=build_client,
    build_adapter=build_adapter,
    provenance_path=Path(__file__).with_name("glossary_provenance.jsonl"),
    codegen_targets=CODEGEN_TARGETS,
    glossary_module="ctkr.oracle.glossary",
)
