#!/usr/bin/env python3
"""Layer 2 on the RECORDING lane — MetaCoding-hy6.66's other half.

    uv run --group dev pytest ctkr/tests/test_recorder_wave_gate.py

WHY THIS FILE EXISTS. Layer 2 shipped on 2026-08-13 in `farmos-port/tools/
ledger.py` and made an open wave a precondition of probing. Measured across wave
2's 13 observing builds the same day, the two observation lanes are DISJOINT:

    sealed pack, port-verify can score it   4 builds — NONE use the ledger
    ledger (preflight, cleanup, floors)     7 builds — NONE produce a pack

So the gate landed on exactly the lane whose output nothing downstream scores,
and the lane producing every scoreable pack was ungated. A guard covering the
half of the work nobody reads is not a guard. Instrument tier: every check
exercises a refusing outcome AND its contrast.
"""

from __future__ import annotations

import json

import pytest

from ctkr.oracle import recorder as R


def waves(tmp_path, rows):
    d = tmp_path / "port_runs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "WAVES.jsonl").write_text(
        "".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows))
    return tmp_path


def point_at(monkeypatch, path):
    monkeypatch.setattr("ctkr.elenchus.port_workspace", lambda *a, **k: str(path))


def test_recording_OUTSIDE_any_open_wave_REFUSES(tmp_path, monkeypatch):
    point_at(monkeypatch, waves(tmp_path, [
        {"record": "open", "wave": "wave2", "opened_at": "1"},
        {"record": "close", "wave": "wave2", "closed_at": "2"}]))
    with pytest.raises(R.WaveNotOpen) as exc:
        R.require_open_wave()
    assert "no wave is open" in str(exc.value)
    assert "wave.py open" in str(exc.value), "a refusal must say how to satisfy it"


def test_recording_INSIDE_an_open_wave_proceeds(tmp_path, monkeypatch):
    """The contrast. Without it the refusal is satisfied by a gate that refuses
    unconditionally, which is an outage rather than a guard."""
    point_at(monkeypatch, waves(tmp_path, [
        {"record": "open", "wave": "wave2", "opened_at": "1"},
        {"record": "close", "wave": "wave2", "closed_at": "2"},
        {"record": "open", "wave": "wave3", "opened_at": "3"}]))
    assert R.require_open_wave() == "wave3"


def test_the_gate_runs_BEFORE_the_adapter_is_opened(tmp_path, monkeypatch):
    """An unregistered run must reach the shared oracle with ZERO requests — the
    same property `Ledger.preflight()` holds, for the same reason: the refusal
    must precede the first byte or "nothing followed this line" is false.

    Drives the REAL `record_session_result`, not the gate alone, because the
    thing under test is the ORDER of two calls inside it.
    """
    point_at(monkeypatch, waves(tmp_path, []))
    touched = []

    class Adapter:
        client = None

        def open(self):
            touched.append("open")

    with pytest.raises(R.WaveNotOpen):
        R.record_session_result(Adapter(), flows=[])
    assert touched == [], "the adapter was opened before the wave gate refused"


def test_an_UNREADABLE_wave_row_refuses_rather_than_being_skipped(tmp_path, monkeypatch):
    """A row nobody can parse is not a row to skip — it decides whether the
    shared oracle may be touched at all."""
    point_at(monkeypatch, waves(tmp_path, [
        {"record": "open", "wave": "wave3", "opened_at": "1"}, "{not json"]))
    with pytest.raises(R.WaveNotOpen) as exc:
        R.require_open_wave()
    assert "unreadable" in str(exc.value)


def test_comments_and_blank_lines_are_skipped(tmp_path, monkeypatch):
    point_at(monkeypatch, waves(tmp_path, [
        "// WAVES.jsonl — append-only wave transitions.", "",
        {"record": "open", "wave": "wave3", "opened_at": "1"}]))
    assert R.require_open_wave() == "wave3"


def test_a_MISSING_ledger_refuses_rather_than_defaulting_open(tmp_path, monkeypatch):
    """The direction of the default is the whole question. A missing ledger read
    as "fine, proceed" would make the gate absent on exactly the workspaces that
    never registered anything."""
    point_at(monkeypatch, tmp_path)
    with pytest.raises(R.WaveNotOpen):
        R.require_open_wave()


def test_a_REOPENED_wave_counts_as_open(tmp_path, monkeypatch):
    """Append-only: a wave closed with debt and re-opened is two rows, not an
    edit. The LAST row per wave decides — the same fold `ledger.open_wave` and
    `ctkr.wave.load_waves` use, and this pins the three readers together."""
    point_at(monkeypatch, waves(tmp_path, [
        {"record": "open", "wave": "wave3", "opened_at": "1"},
        {"record": "close", "wave": "wave3", "closed_at": "2"},
        {"record": "open", "wave": "wave3", "opened_at": "3"}]))
    assert R.require_open_wave() == "wave3"


def test_this_reader_AGREES_with_the_ledgers_reader(tmp_path, monkeypatch):
    """Two independent implementations of "which wave is open" now exist — this
    one and `farmos-port/tools/ledger.py`'s — because the recording path must not
    take a dependency on the decision menu to answer a question this small. Two
    readers that disagree are worse than one: a build would be gated by whichever
    lane it happened to use. Pinned here rather than assumed.
    """
    import importlib.util
    import os
    p = "/Users/dukejones/work/WorldTree/farmos-port/tools/ledger.py"
    if not os.path.isfile(p):
        pytest.skip("port workspace not present")
    import sys
    spec = importlib.util.spec_from_file_location("_led", p)
    led = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: `ledger.py` uses `from __future__ import annotations`
    # with dataclasses, and `dataclasses` resolves string annotations through
    # `sys.modules[cls.__module__]` — absent, it raises on an unrelated line.
    sys.modules["_led"] = led
    spec.loader.exec_module(led)

    for rows, expected in (
        ([{"record": "open", "wave": "w3", "opened_at": "1"}], "w3"),
        ([{"record": "open", "wave": "w3", "opened_at": "1"},
          {"record": "close", "wave": "w3", "closed_at": "2"}], None),
        ([{"record": "open", "wave": "w2", "opened_at": "1"},
          {"record": "close", "wave": "w2", "closed_at": "2"},
          {"record": "open", "wave": "w3", "opened_at": "3"}], "w3"),
    ):
        d = tmp_path / f"case{len(rows)}{expected}"
        waves(d, rows)
        point_at(monkeypatch, d)
        theirs = led.open_wave(str(d))
        if expected is None:
            assert theirs is None
            with pytest.raises(R.WaveNotOpen):
                R.require_open_wave()
        else:
            assert theirs == expected == R.require_open_wave()
