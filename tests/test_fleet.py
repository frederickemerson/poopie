"""Fleet data layer: mapping, null handling, normalization, and the no-synthesis guard."""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from contracts.contract import ContractViolation, node_types, validate_node  # noqa: E402
from engine.graph import normalize  # noqa: E402
from engine.graph.aircraft_nodes import merge_nodes, node_line, write_aircraft_nodes  # noqa: E402
from engine.ingest import fleet  # noqa: E402
from engine.ingest.fleet_select import select_demo_fleet  # noqa: E402

FIXTURE = ROOT / "data" / "fixtures" / "aircraftDatabase_sample.csv"
BUILD_NODES = ROOT / "data" / "build" / "nodes.aircraft.jsonl"
RAW_CSV = fleet.RAW_PATH


@pytest.fixture(scope="module")
def raw_rows() -> list[dict[str, str]]:
    with FIXTURE.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.fixture(scope="module")
def mapped(raw_rows):
    return [r for r in (fleet.map_row(row) for row in raw_rows) if r is not None]


# ---- column mapping ---------------------------------------------------------

def test_column_map_targets_are_contract_aircraft_fields():
    contract_fields = set(node_types()["Aircraft"]["fields"])
    assert set(fleet.COLUMN_MAP) | {"source"} == contract_fields


def test_row_maps_each_column_onto_its_contract_field():
    row = {"icao24": "a1e14a", "registration": "N220CY", "manufacturername": "Boeing", "model": "767-383ER",
           "typecode": "B763", "serialnumber": "24729", "operator": "Abx Air", "owner": "Cargo Co",
           "built": "1992-03-01", "engines": "P & W PW4060"}
    assert fleet.map_row(row) == {
        "tail_number": "N220CY", "icao24": "a1e14a", "manufacturer": "Boeing", "model": "767-383ER",
        "typecode": "B763", "serial_number": "24729", "operator": "Abx Air", "owner": "Cargo Co",
        "built_year": 1992, "engines": "P & W PW4060", "source": "opensky",
    }


def test_mapped_fixture_records_validate_against_contract(mapped):
    assert mapped
    for rec in mapped:
        validate_node("Aircraft", rec)


# ---- empty -> null ------------------------------------------------------------

def test_empty_and_whitespace_cells_become_none_never_empty_string(raw_rows, mapped):
    for rec in mapped:
        for name, value in rec.items():
            assert value != "", f"{rec['tail_number']}.{name} is an empty string"
            assert not (isinstance(value, str) and value != value.strip())
    sparse = next(r for r in mapped if r["serial_number"] is None)
    assert sparse["serial_number"] is None and sparse["tail_number"]


def test_row_without_registration_is_skipped_and_counted(raw_rows):
    stats: Counter[str] = Counter()
    assert fleet.map_row(raw_rows[0], stats) is None
    assert stats["skipped_no_registration"] == 1


def test_clean_handles_none_blank_and_padding():
    assert fleet.clean(None) is None and fleet.clean("") is None and fleet.clean("  \t") is None
    assert fleet.clean("  x ") == "x"


def test_engines_html_break_is_stripped_but_nothing_else_changed():
    assert fleet.clean_engines("2 x INTERNATIONAL AERO ENGINE V2527-A5<br>") == "2 x INTERNATIONAL AERO ENGINE V2527-A5"
    assert fleet.clean_engines("<br>") is None


# ---- built_year ---------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("2005-01-01", 2005), ("1984-11-23", 1984), ("2019", 2019), ("", None), (None, None), ("  ", None),
    ("0001-01-01", None),
])
def test_parse_built_year(raw, expected):
    assert fleet.parse_built_year(raw) == expected


@pytest.mark.parametrize("raw", ["not-a-date", "2005-13-45", "1850-01-01", "9999-01-01"])
def test_parse_built_year_rejects_malformed_or_implausible(raw):
    with pytest.raises(fleet.MalformedBuilt):
        fleet.parse_built_year(raw)


def test_malformed_built_is_null_and_counted_not_swallowed(capsys):
    stats: Counter[str] = Counter()
    rec = fleet.map_row({"registration": "N1", "built": "garbage"}, stats)
    assert rec["built_year"] is None and stats["malformed_built"] == 1
    assert "garbage" in capsys.readouterr().err


# ---- normalization table ------------------------------------------------------

@pytest.mark.parametrize("raw,canonical", [
    ("The Boeing Company", "Boeing"), ("Boeing", "Boeing"), ("  the  BOEING company ", "Boeing"),
    ("Airbus SAS", "Airbus"), ("Airbus Industrie", "Airbus"), ("Airbus", "Airbus"),
    ("Embraer S.A.", "Embraer"), ("Embraer S A", "Embraer"),
    ("Bombardier Inc.", "De Havilland Canada"), ("De Havilland Canada", "De Havilland Canada"),
    ("Avions De Transport Regional", "ATR"),
])
def test_manufacturer_aliases_resolve_to_canonical(raw, canonical):
    assert normalize.normalize_manufacturer(raw) == canonical


@pytest.mark.parametrize("raw", [None, "", "  ", "Yabora Industria Aeronautica S", "Cessna", "737-8as (w)"])
def test_unlisted_manufacturer_is_unmapped_not_guessed(raw):
    assert normalize.normalize_manufacturer(raw) is None


def test_ad_make_and_opensky_name_join_both_ways():
    assert normalize.manufacturer_matches_ad("Boeing", "The Boeing Company") is True
    assert normalize.manufacturer_matches_ad("Airbus Industrie", "Airbus SAS") is True
    assert normalize.manufacturer_matches_ad("Boeing", "Airbus SAS") is False
    assert normalize.manufacturer_matches_ad("Boeing", "Some Unknown Maker") is None
    assert normalize.manufacturer_matches_ad(None, "Boeing") is None


def test_model_and_typecode_join():
    assert normalize.typecodes_for_ad_model("737-800") == ["B738"]
    assert normalize.typecodes_for_ad_model("737-800 Series") == ["B738"]
    assert normalize.typecodes_for_ad_model("737-8") == ["B38M"]
    assert normalize.typecodes_for_ad_model("A330-900") == ["A339"]
    assert normalize.typecodes_for_ad_model("DHC-8-400") == ["DH8D"]
    assert normalize.typecodes_for_ad_model("999-1") == []
    assert normalize.type_info("b738")["family"] == "737"
    assert normalize.type_info("C172") is None


def test_manufacturer_contradicting_typecode_is_flagged():
    assert normalize.manufacturer_conflicts_with_type("Airbus", "B738") is True
    assert normalize.manufacturer_conflicts_with_type("Boeing", "B738") is False
    assert normalize.manufacturer_conflicts_with_type(None, "B738") is False
    assert normalize.manufacturer_conflicts_with_type("Unlisted Co", "B738") is False


def test_table_is_internally_consistent():
    tbl = normalize.table()
    for code, info in tbl["types"].items():
        assert info["manufacturer"] in tbl["manufacturers"], code
        assert info["ad_models"] and info["family"], code
    assert normalize._alias_index()  # raises if an alias maps to two manufacturers


# ---- selection ------------------------------------------------------------------

def test_selection_on_fixture_obeys_every_stated_filter_and_is_deterministic():
    a = select_demo_fleet(FIXTURE, min_per_operator=1)
    b = select_demo_fleet(FIXTURE, min_per_operator=1)
    assert a.fleet == b.fleet and a.fleet
    for rec in a.fleet:
        assert rec["serial_number"] and rec["operator"]
        assert "a00000" <= str(rec["icao24"]) <= "adf7c7"
        assert normalize.type_info(str(rec["typecode"])) is not None
    assert len({r["tail_number"] for r in a.fleet}) == len(a.fleet)


# ---- nodes file / merge -----------------------------------------------------------

def test_write_emits_only_validated_aircraft_lines(tmp_path, mapped):
    out = tmp_path / "nodes.aircraft.jsonl"
    n = write_aircraft_nodes(mapped, out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert n == len(lines) == len(mapped)
    assert {json.loads(ln)["_type"] for ln in lines} == {"Aircraft"}


def test_node_line_rejects_fields_outside_the_contract():
    with pytest.raises(ContractViolation):
        node_line({"tail_number": "N1", "category": "transport"})


def test_merge_preserves_foreign_lines_byte_for_byte_and_is_idempotent(tmp_path, mapped):
    air = tmp_path / "nodes.aircraft.jsonl"
    nodes = tmp_path / "nodes.jsonl"
    write_aircraft_nodes(mapped[:3], air)
    foreign = ['{"_type": "AD", "ad_number": "2026-21-13"}', '{"_type":"Docket","docket_id":"FAA-2026-0001"}']
    stale = '{"_type": "Aircraft", "tail_number": "OLD1"}'
    nodes.write_text("\n".join([foreign[0], stale, foreign[1]]) + "\n", encoding="utf-8")
    merge_nodes(air, nodes)
    first = nodes.read_text(encoding="utf-8")
    lines = first.splitlines()
    assert lines[:2] == foreign and "OLD1" not in first
    assert sum(json.loads(ln)["_type"] == "Aircraft" for ln in lines) == 3
    merge_nodes(air, nodes)
    assert nodes.read_text(encoding="utf-8") == first


# ---- guard: no synthesized values ---------------------------------------------------

def _verbatim(raw: str) -> str:
    return raw.replace("<br>", " ").strip()


def test_every_fixture_derived_value_appears_verbatim_in_its_source_row(raw_rows, mapped):
    by_tail = {r["registration"]: r for r in raw_rows if r["registration"]}
    for rec in mapped:
        src = by_tail[str(rec["tail_number"])]
        for field_name, column in fleet.COLUMN_MAP.items():
            value = rec[field_name]
            if value is None or field_name == "built_year":
                continue
            assert str(value) in _verbatim(src[column]) or str(value) == src[column].strip(), (field_name, value)
        if rec["built_year"] is not None:
            assert src["built"].startswith(str(rec["built_year"]))
        else:
            assert fleet.clean(src["built"]) in (None, fleet.BUILT_UNKNOWN_SENTINEL)


def test_null_source_cells_never_get_filled(raw_rows, mapped):
    by_tail = {r["registration"]: r for r in raw_rows if r["registration"]}
    for rec in mapped:
        src = by_tail[str(rec["tail_number"])]
        for field_name, column in fleet.COLUMN_MAP.items():
            if not src[column].strip():
                assert rec[field_name] is None, (rec["tail_number"], field_name)


def test_every_serial_in_fixture_selection_is_a_source_serial(raw_rows):
    source_serials = {r["serialnumber"].strip() for r in raw_rows if r["serialnumber"].strip()}
    for rec in select_demo_fleet(FIXTURE, min_per_operator=1).fleet:
        assert rec["serial_number"] in source_serials


@pytest.mark.skipif(not (BUILD_NODES.exists() and RAW_CSV.exists()), reason="full build output / raw CSV not present")
def test_built_fleet_serials_and_tails_exist_verbatim_in_full_source():
    wanted = [json.loads(ln) for ln in BUILD_NODES.read_text(encoding="utf-8").splitlines()]
    pairs = {(str(w["tail_number"]), str(w["serial_number"])) for w in wanted if w["serial_number"] is not None}
    found: set[tuple[str, str]] = set()
    with RAW_CSV.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            key = (row["registration"].strip(), row["serialnumber"].strip())
            if key in pairs:
                found.add(key)
    assert found == pairs


# ------------------------------------------------- variant-level model index
# The series table carries type-level names ("737-800") and says so in its own
# note, pointing at Aircraft.model for variants. These cover that second half:
# without it, 423 of the 478 built aircraft carried a model string the engine
# did not recognise, and the graph filter silently stopped narrowing by type.


def test_variant_index_is_empty_rather_than_guessing_when_the_fleet_is_absent(monkeypatch):
    normalize.variant_model_index.cache_clear()
    monkeypatch.setattr(normalize, "BUILD", Path("/nonexistent-build-dir"))
    try:
        assert normalize.variant_model_index() == {}
    finally:
        normalize.variant_model_index.cache_clear()


@pytest.mark.skipif(not BUILD_NODES.exists(), reason="fleet not built")
def test_every_built_aircraft_model_resolves_to_a_typecode():
    from engine.retrieval.entities import _model_index

    index = _model_index()
    models = [
        json.loads(line)["model"]
        for line in BUILD_NODES.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("_type") == "Aircraft"
        and (json.loads(line).get("model") or "").strip()
    ]
    unresolved = sorted({m for m in models if normalize._model_key(m) not in index})
    assert not unresolved, (
        f"{len(unresolved)} fleet model strings resolve to no type, so a question "
        f"naming one cannot be narrowed: {unresolved[:10]}"
    )


@pytest.mark.skipif(not BUILD_NODES.exists(), reason="fleet not built")
def test_a_variant_resolves_to_the_series_typecode_not_to_itself():
    from engine.retrieval.entities import extract_entities

    found = extract_entities("Which ADs apply to my Airbus A330-941?")
    assert found.typecodes == ["A339"]
    assert found.manufacturers == ["Airbus"]
    assert not found.ambiguous, "a known variant must not also be reported as ambiguous"


@pytest.mark.skipif(not BUILD_NODES.exists(), reason="fleet not built")
def test_every_series_name_still_reaches_its_own_typecode():
    """No source may displace a series name's own type. The fleet is added after
    the table and only ever extends an entry, so a variant cannot overwrite the
    vocabulary the documents are written in."""
    from engine.retrieval.entities import _model_index

    index = _model_index()
    for typecode, spec in normalize.table()["types"].items():
        for model in spec["ad_models"]:
            typecodes, manufacturer = index[normalize._model_key(model)]
            assert typecode in typecodes
            assert manufacturer == spec["manufacturer"]


def test_a_designation_naming_two_types_keeps_both():
    """"ERJ 170-200" is both E75L and E75S -- the long- and short-wing Embraer
    175. The table lists it under both, and dropping either silently answers
    for half the type. The graph filter unions typecodes, so both belong."""
    from engine.retrieval.entities import _model_index, extract_entities

    typecodes, manufacturer = _model_index()[normalize._model_key("ERJ 170-200")]
    assert set(typecodes) == {"E75L", "E75S"}
    assert manufacturer == "Embraer"
    assert set(extract_entities("ADs for the ERJ 170-200").typecodes) == {"E75L", "E75S"}


@pytest.mark.skipif(not BUILD_NODES.exists(), reason="fleet not built")
def test_every_variant_maps_to_a_typecode_the_table_knows():
    for variant, (typecode, manufacturer) in normalize.variant_model_index().items():
        assert typecode in normalize.table()["types"], (
            f"{variant} claims typecode {typecode}, which the series table does not define"
        )
        assert manufacturer, f"{variant} resolved to no manufacturer"
