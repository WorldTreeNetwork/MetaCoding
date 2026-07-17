"""Schema + validator + storage-leak tests for the semantic-fixture oracle.

No Docker, no network — pure data validation over canned fixtures.
"""

from __future__ import annotations

from ctkr.oracle.fixtures import (
    GivenStep,
    Provenance,
    QuantitySpec,
    SemanticFixture,
    ThenAssertion,
    WhenStep,
    load_fixtures,
    validate_fixture,
    write_fixtures,
)


def _valid_fixture() -> SemanticFixture:
    return SemanticFixture(
        title="Recording a harvest gives the asset a yield total",
        feature="harvest-logging",
        glossary_terms=["land", "harvest", "weight", "yield_total"],
        given=[GivenStep(entity="land", alias="A", name="North Field")],
        when=[
            WhenStep(
                action="record_log", alias="L", kind="harvest", status="done",
                name="Harvest", against=["A"],
                quantities=[QuantitySpec(measure="weight", value=5, unit="kilogram",
                                         label="yield")],
            )
        ],
        then=[
            ThenAssertion(assert_="yield_total", subject="A", measure="weight",
                          unit="kilogram", op="==", value=5),
            ThenAssertion(assert_="log_count", subject="A", kind="harvest",
                          op="==", value=1),
        ],
        provenance=Provenance(source_system="farmOS", source_version="4.x",
                              flow="harvest-yield-single"),
    )


def test_valid_fixture_has_no_issues():
    assert validate_fixture(_valid_fixture()) == []


def test_content_id_is_stable_and_provenance_independent():
    fx1 = _valid_fixture()
    fx2 = _valid_fixture()
    fx2 = fx2.model_copy(update={
        "provenance": Provenance(source_system="farmOS", flow="different",
                                 recorded_at="2099-01-01T00:00:00Z")
    })
    # Same scenario body -> same id regardless of provenance timestamps/flow.
    assert fx1.content_id() == fx2.content_id()


def test_unknown_entity_term_is_error():
    fx = _valid_fixture()
    fx.given[0].entity = "spaceship"
    issues = validate_fixture(fx)
    assert any(i.severity == "error" and "entity" in i.where for i in issues)


def test_unknown_subject_alias_is_error():
    fx = _valid_fixture()
    fx.then[0].subject = "ZZZ"
    issues = validate_fixture(fx)
    assert any("subject" in i.where for i in issues)


def test_record_log_against_unknown_asset_is_error():
    fx = _valid_fixture()
    fx.when[0].against = ["NOPE"]
    issues = validate_fixture(fx)
    assert any("against" in i.where for i in issues)


def test_missing_required_assert_field_is_error():
    fx = _valid_fixture()
    # log_count requires `kind`
    fx.then[1].kind = ""
    issues = validate_fixture(fx)
    assert any(i.where == "then[1].kind" for i in issues)


def test_storage_leak_lint_catches_table_and_column():
    fx = _valid_fixture()
    fx.title = "row inserted into field_data_quantity table"
    issues = validate_fixture(fx)
    leaks = [i for i in issues if i.severity == "leak"]
    assert leaks, "expected the storage-leak lint to fire"
    assert any("field_data_" in i.message for i in leaks)


def test_storage_leak_lint_catches_id_and_sql():
    fx = _valid_fixture()
    fx.when[0].name = "SELECT entity_id FROM log"
    issues = validate_fixture(fx)
    assert any(i.severity == "leak" for i in issues)


def test_clean_scenario_passes_leak_lint():
    # Domain prose that merely resembles storage words must not false-positive.
    fx = _valid_fixture()
    fx.when[0].name = "Harvest from the north field on Tuesday"
    assert [i for i in validate_fixture(fx) if i.severity == "leak"] == []


def test_jsonl_round_trip(tmp_path):
    fx = _valid_fixture()
    path = tmp_path / "fixtures.jsonl"
    n = write_fixtures([fx], path)
    assert n == 1
    loaded = load_fixtures(path)
    assert len(loaded) == 1
    assert loaded[0].fixture_id == fx.content_id()
    assert loaded[0].then[0].assert_ == "yield_total"
    assert loaded[0].then[0].value == 5
    # the on-disk form uses the `assert` key
    raw = path.read_text()
    assert '"assert"' in raw
