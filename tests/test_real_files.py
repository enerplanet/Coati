"""Files that the frameworks themselves have written.

The files under ``tests/data`` hold a small model of each framework, solved by
the framework; ``tests/data/README.md`` tells how they were made. Next to a
file lie its *facts*: what the framework says about the model through its own
interface, written down by the script that solved it. A results document must
say the same, although it is made from the file alone.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import netCDF4
import numpy as np
import pytest
from jsonschema import Draft202012Validator

import coati
from coati import cf
from coati.cli import main
from support.compare import against_facts, as_json, differences

DATA = Path(__file__).parent / "data"

#: The files, with the framework that Coati finds in each and the version that the file states.
FILES = {
    "adopt-net0-0.1.10.h5": ("adopt-net0-v0-1", None),
    "adopt-net0-0.1.10-periods.h5": ("adopt-net0-v0-1", None),
    "adopt-net0-0.1.10-typical-days.h5": ("adopt-net0-v0-1", None),
    "calliope-0.6.10.nc": ("calliope-v0-6-10", "0.6.10"),
    "calliope-0.6.10-spores.nc": ("calliope-v0-6-10", "0.6.10"),
    "calliope-0.7.0.dev7.nc": ("calliope-v0-7-0-dev7", "0.7.0.dev7"),
    "calliope-0.7.0.dev7-spores.nc": ("calliope-v0-7-0-dev7", "0.7.0.dev7"),
    "calliope-0.7.0.nc": ("calliope-v0-7", None),
    "calliope-0.7.0-spores.nc": ("calliope-v0-7", None),
    "pypsa-0.25.2.nc": ("pypsa-v0-25-2", "0.25.2"),
    "pypsa-0.25.2.h5": ("pypsa-v0-25-2", "0.25.2"),
    "pypsa-0.35.2.nc": ("pypsa-v0-35-2", "0.35.2"),
    "pypsa-0.35.2.h5": ("pypsa-v0-35-2", "0.35.2"),
    "pypsa-1.2.4.nc": ("pypsa-v1-2-4", "1.2.4"),
    "pypsa-1.2.4.h5": ("pypsa-v1-2-4", "1.2.4"),
    "pypsa-1.2.4-stochastic.nc": ("pypsa-v1-2-4", "1.2.4"),
    "pypsa-1.2.4-unsolved.nc": ("pypsa-v1-2-4", "1.2.4"),
    "pypsa-1.3.0.nc": ("pypsa-v1-3-0", "1.3.0"),
    "pypsa-1.3.0.h5": ("pypsa-v1-3-0", "1.3.0"),
}

#: The identifier that names the version, for the files that do not state it.
NAMED = {
    "adopt-net0-0.1.10.h5": ("adopt-net0-v0-1-10", "0.1.10"),
    "adopt-net0-0.1.10-periods.h5": ("adopt-net0-v0-1-10", "0.1.10"),
    "adopt-net0-0.1.10-typical-days.h5": ("adopt-net0-v0-1-10", "0.1.10"),
    "calliope-0.7.0.nc": ("calliope-v0-7-0", "0.7.0"),
    "calliope-0.7.0-spores.nc": ("calliope-v0-7-0", "0.7.0"),
}

SOLVED = sorted(name for name in FILES if "unsolved" not in name)

#: How many times the models have.
STEPS = {"pypsa-1.2.4-stochastic.nc": 4, "adopt-net0-0.1.10-typical-days.h5": 144}


def stem(name: str) -> str:
    return name.rsplit(".", 1)[0]


def facts_of(name: str) -> dict[str, Any]:
    return json.loads((DATA / f"{stem(name)}.facts.json").read_text(encoding="utf-8"))


def with_facts() -> list[str]:
    return sorted(name for name in FILES if (DATA / f"{stem(name)}.facts.json").exists())


def document_of(path: Path, framework: str = "auto") -> dict[str, Any]:
    return as_json(coati.results_document(path, framework))


def test_every_file_is_tested() -> None:
    packed = sorted(path.name.removesuffix(".xz") for path in DATA.glob("*.xz"))
    assert packed == sorted(FILES)
    described = sorted(path.name for path in DATA.glob("*.facts.json"))
    assert described == sorted({f"{stem(name)}.facts.json" for name in with_facts()})


# -- the framework ----------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(FILES))
def test_the_framework_is_found(data_dir: Path, name: str) -> None:
    identifier, version = FILES[name]
    found = coati.detect(data_dir / name)
    assert found is not None
    assert found.id == identifier
    assert found.version == version
    assert found.supported
    assert name.startswith(found.name)


@pytest.mark.parametrize("name", sorted(FILES))
def test_the_framework_may_be_named(data_dir: Path, name: str) -> None:
    identifier, version = NAMED.get(name, FILES[name])
    named = document_of(data_dir / name, identifier)
    found = document_of(data_dir / name)
    assert named["metadata"]["framework_id"] == identifier
    assert named["framework_version"] == version
    assert found["framework_version"] == FILES[name][1]
    for document in (named, found):
        del document["framework_version"], document["metadata"]
    assert named == found


@pytest.mark.parametrize("name", sorted(FILES))
def test_a_file_is_not_read_as_that_of_another_framework(data_dir: Path, name: str) -> None:
    others = {"calliope-v0-7-0", "calliope-v0-6-10", "pypsa-v1-2-4", "adopt-net0-v0-1-10"}
    own = coati.detect(data_dir / name)
    for identifier in sorted(others):
        if coati.frameworks.parse(identifier).family == own.family:
            continue
        with pytest.raises(coati.errors.FrameworkError):
            coati.results_document(data_dir / name, identifier)


# -- the results ------------------------------------------------------------------------------


@pytest.mark.parametrize("name", with_facts())
def test_the_document_says_what_the_framework_says(data_dir: Path, name: str) -> None:
    assert against_facts(document_of(data_dir / name), facts_of(name)) == []


@pytest.mark.parametrize("name", SOLVED)
def test_a_solved_model(data_dir: Path, name: str) -> None:
    found = document_of(data_dir / name)
    assert found["success"] is True
    assert found["termination_condition"] == "optimal"
    assert found["objective"] > 0
    steps = len(found["timestamps"])
    assert steps == STEPS.get(name, 48 if name.startswith("adopt") else 24)
    assert len(found["demand_timeseries"]) == steps
    assert all(len(series) == steps for series in found["dispatch"].values())
    assert all(len(flow["timeseries"]) == steps for flow in found["transmission_flow"].values())
    assert set(found["tech_parents"]) == set(found["tech_metadata"])
    described = set(found["tech_metadata"])
    assert {key.split("::")[1] for key in found["capacities"]} <= described
    assert {key.split("::")[1] for key in found.get("storage_capacities", {})} <= described
    assert {key.split("::")[1] for key in found["generation"]} <= described
    assert set(found["dispatch"]) <= described
    assert set(found["costs_by_tech"]) <= described
    sized = set(found["capacities"]) | set(found.get("storage_capacities", {}))
    generating = {key.rsplit("::", 1)[0] for key in found["generation"]}
    bought = {key for key in generating if key.split("::")[1].startswith("import_")}
    assert generating - bought <= sized


@pytest.mark.parametrize("name", SOLVED)
def test_a_connection_is_listed_at_both_of_its_ends(data_dir: Path, name: str) -> None:
    found = document_of(data_dir / name)
    lines = [
        key for key in found["capacities"]
        if found["tech_parents"][key.split("::")[1]] == "transmission"
    ]  # fmt: skip
    if "stochastic" in name:
        assert lines == []
        return
    assert len(lines) % 2 == 0
    assert {key.split("::")[0] for key in lines} == {"north", "south"}
    sizes = sorted(found["capacities"][key] for key in lines)
    assert sizes[0::2] == sizes[1::2]
    costs = sorted(
        cost
        for costs in found["costs_by_location"].values()
        for technology, cost in costs.items()
        if found["tech_parents"][technology] == "transmission"
    )
    assert costs[0::2] == pytest.approx(costs[1::2])


@pytest.mark.parametrize("name", SOLVED)
def test_the_costs_add_up_to_the_objective(data_dir: Path, name: str) -> None:
    found = document_of(data_dir / name)
    total = sum(sum(costs.values()) for costs in found["costs_by_location"].values())
    assert total == pytest.approx(found["objective"], rel=1e-6)
    by_technology = sum(found["costs_by_tech"].values())
    negative = sum(
        cost for costs in found["costs_by_location"].values() for cost in costs.values() if cost < 0
    )
    assert by_technology + negative == pytest.approx(found["objective"], rel=1e-6)


@pytest.mark.parametrize("name", SOLVED)
def test_the_dispatch_adds_up_to_the_generation(data_dir: Path, name: str) -> None:
    found = document_of(data_dir / name)
    weights = found.get("weights", [1.0] * len(found["timestamps"]))
    kinds = found["tech_parents"]
    for technology, series in found["dispatch"].items():
        generated = sum(
            value for key, value in found["generation"].items() if key.split("::")[1] == technology
        )
        weighted = sum(value * weight for value, weight in zip(series, weights, strict=True))
        assert weighted == pytest.approx(generated, rel=1e-6, abs=1e-6), (technology, kinds)


@pytest.mark.parametrize("name", SOLVED)
def test_what_is_exported_is_imported(data_dir: Path, name: str) -> None:
    found = document_of(data_dir / name)
    if not found["transmission_flow"]:
        assert "imports_by_location" not in found
        return
    imports, exports = found["imports_by_location"], found["exports_by_location"]
    assert sum(imports.values()) == pytest.approx(sum(exports.values()))
    assert sum(imports.values()) > 0


@pytest.mark.parametrize("version", ["0.25.2", "0.35.2", "1.2.4", "1.3.0"])
def test_both_formats_of_pypsa_say_the_same(data_dir: Path, version: str) -> None:
    netcdf = document_of(data_dir / f"pypsa-{version}.nc")
    hdf5 = document_of(data_dir / f"pypsa-{version}.h5")
    assert netcdf["metadata"].pop("source")["format"] == "netcdf4"
    assert hdf5["metadata"].pop("source")["format"] == "hdf5"
    assert differences(hdf5, netcdf) == []


@pytest.mark.parametrize("preview", ["calliope-0.7.0.dev7", "calliope-0.7.0.dev7-spores"])
def test_the_preview_of_calliope_says_what_the_release_says(data_dir: Path, preview: str) -> None:
    release = document_of(data_dir / f"{preview.replace('.dev7', '')}.nc")
    found = document_of(data_dir / f"{preview}.nc")
    for document in (release, found):
        del document["metadata"], document["framework_version"]
    assert differences(found, release) == []


@pytest.mark.parametrize("version", ["0.6.10", "0.7.0.dev7", "0.7.0"])
def test_the_solutions_of_the_spores_mode(data_dir: Path, version: str) -> None:
    # The model looks for two alternatives that cost at most a fifth more than the optimum.
    found = document_of(data_dir / f"calliope-{version}-spores.nc")
    assert found["details"]["mode"] == "spores"
    spores = found["details"]["spores"]
    assert [entry["spore"] for entry in spores] == ["0", "1", "2"]
    assert spores[0]["cost"] == pytest.approx(found["objective"], rel=1e-12)
    assert spores[0]["capacities"] == found["capacities"]
    assert spores[0]["generation"] == found["generation"]
    for entry in spores[1:]:
        assert found["objective"] < entry["cost"] <= found["objective"] * 1.2 * (1 + 1e-6)
        assert entry["capacities"] != found["capacities"]
    assert found["warnings"] == [
        (
            "the file holds 3 solutions of the SPORES mode; the document reports the first,"
            " details.spores lists the cost, the capacities and the generation of each"
        )
    ]
    base = document_of(data_dir / f"calliope-{version}.nc")
    assert differences(found["capacities"], base["capacities"]) == []
    assert found["objective"] == pytest.approx(base["objective"], rel=1e-6)


def test_a_stochastic_network(data_dir: Path) -> None:
    found = document_of(data_dir / "pypsa-1.2.4-stochastic.nc")
    assert found["scenarios"] == {"high": 0.25, "low": 0.75}
    # Gas alone meets the demand of 420 at a price of 90 or of 30.
    assert found["objective_function_value"] == pytest.approx(420 * (0.25 * 90 + 0.75 * 30))
    assert found["objective"] == pytest.approx(found["objective_function_value"])
    assert found["capacities"] == {"hub::gas": 300.0, "hub::pv": 0.0}
    assert found["warnings"] == [
        "the network has 2 scenarios; the document reports the expectation"
    ]


def test_a_network_that_is_not_solved(data_dir: Path) -> None:
    found = document_of(data_dir / "pypsa-1.2.4-unsolved.nc")
    assert found["success"] is False
    assert found["termination_condition"] == "not_solved"
    assert found["objective"] is None
    assert found["dispatch"] == {}
    assert found["costs_by_tech"] == {}
    assert found["costs_by_location"] == {}
    solved = document_of(data_dir / "pypsa-1.2.4.nc")
    assert set(found["capacities"]) == set(solved["capacities"])
    assert found["demand_timeseries"] == pytest.approx(solved["demand_timeseries"])
    assert len(found["warnings"]) == 1


def test_typical_days_stand_for_the_whole_time(data_dir: Path) -> None:
    # Two typical days stand for six days. The file has the 48 hours of the typical days;
    # the summary has the costs of the six days, which AdOpT-NET0 computes from the model.
    path = data_dir / "adopt-net0-0.1.10-typical-days.h5"
    found = document_of(path)
    assert found["details"]["typical_days"] is True
    assert len(found["timestamps"]) == 144
    assert "weights" not in found
    with coati.open_dataset(path) as dataset:
        assert dataset.variable("/k_means_specs/period1/factors").shape == (48,)
        assert dataset.variable(
            "/operation/energy_balance/period1/south/electricity/demand"
        ).shape == (48,)
    summary = found["details"]["summary"]
    by_kind = {"technologies": 0.0, "networks": 0.0, "imports": 0.0}
    for costs in found["costs_by_location"].values():
        for technology, cost in costs.items():
            kind = found["tech_parents"][technology]
            if technology.startswith("import_"):
                by_kind["imports"] += cost
            else:
                by_kind["networks" if kind == "transmission" else "technologies"] += cost
    assert by_kind["technologies"] == pytest.approx(summary["cost_tecs"], rel=1e-9)
    assert by_kind["networks"] == pytest.approx(summary["cost_netws"], rel=1e-9)
    assert by_kind["imports"] == pytest.approx(summary["cost_imports"], rel=1e-9)
    assert found["objective"] == summary["total_npv"]
    assert found["warnings"] == []


def test_the_periods_of_adopt_net0(data_dir: Path) -> None:
    path = data_dir / "adopt-net0-0.1.10-periods.h5"
    first, second = document_of(path), document_of(path, "adopt-net0-v0-1-10")
    assert first["details"]["period"] == "period1"
    assert first["details"]["periods"] == ["period1", "period2"]
    total = first["details"]["summary"]["total_npv"]
    assert first["objective_function_value"] == total
    assert first["objective"] < total
    assert second["capacities"] == first["capacities"]


def test_adopt_net0_writes_the_last_period_in_place_of_every_period(data_dir: Path) -> None:
    """Hold on to a defect of AdOpT-NET0 0.1.10 that the document warns about.

    The demand of the second period is twice that of the first. The file holds
    that of the second for both: the function that writes the results takes
    the design of the nodes, the operation and the energy balances of every
    period from the period it has looked at last. Once AdOpT-NET0 writes what
    belongs to each period, this test fails for a file of the new version, and
    the warning can be limited to the versions that have the defect.
    """
    path = data_dir / "adopt-net0-0.1.10-periods.h5"
    demand = facts_of("adopt-net0-0.1.10-periods.h5")["_demand_of_periods"]
    assert demand == {"period1": 1920.0, "period2": 3840.0}
    for period in ("period1", "period2"):
        options = coati.ExtractOptions(period=period)
        found = as_json(coati.results_document(path, options=options))
        assert found["details"]["period"] == period
        assert found["demand_by_location"] == {"south": pytest.approx(demand["period2"])}
        assert found["warnings"] == [
            (
                f"the file holds 2 investment periods; the document reports {period!r},"
                " and its objective is the cost of that period"
            ),
            (
                "the file holds the same results for each of its 2 investment periods, except"
                " for the design of the networks; AdOpT-NET0 0.1.10 is known to write the"
                " results of the last period, 'period2', in place of those of every period"
            ),
        ]


def test_adopt_net0_records_no_times(data_dir: Path) -> None:
    path = data_dir / "adopt-net0-0.1.10.h5"
    assert document_of(path)["timestamps"] == list(range(48))
    options = coati.ExtractOptions(time_start="2030-06-01", time_step="1h")
    stamps = as_json(coati.results_document(path, options=options))["timestamps"]
    assert stamps[0] == "2030-06-01T00:00:00"
    assert stamps[-1] == "2030-06-02T23:00:00"


# -- the documents ----------------------------------------------------------------------------


def golden(document: dict[str, Any]) -> dict[str, Any]:
    """Leave out what changes although the file stays the same."""
    document = json.loads(json.dumps(document))
    del document["metadata"]["generator_version"]
    return document


@pytest.mark.parametrize(
    "name",
    [
        "adopt-net0-0.1.10.h5",
        "adopt-net0-0.1.10-typical-days.h5",
        "calliope-0.6.10.nc",
        "calliope-0.6.10-spores.nc",
        "calliope-0.7.0.nc",
        "calliope-0.7.0-spores.nc",
        "pypsa-0.25.2.nc",
        "pypsa-0.35.2.nc",
        "pypsa-1.2.4.nc",
        "pypsa-1.2.4-stochastic.nc",
        "pypsa-1.2.4-unsolved.nc",
    ],
)
def test_the_document_is_the_one_expected(
    data_dir: Path, expect: Callable[[str, Any], None], name: str
) -> None:
    expect(stem(name), golden(document_of(data_dir / name)))


@pytest.mark.parametrize("name", sorted(FILES))
def test_the_documents_are_valid(data_dir: Path, name: str) -> None:
    for kind, document in (
        ("results", document_of(data_dir / name)),
        ("dataset", as_json(coati.dataset_document(data_dir / name))),
        ("dataset", as_json(coati.dataset_document(data_dir / name), non_finite="string")),
    ):
        schema = json.loads(
            (Path(coati.__file__).parent / "schemas" / f"{kind}.schema.json").read_text("utf-8")
        )
        errors = [error.message for error in Draft202012Validator(schema).iter_errors(document)]
        assert errors == []


@pytest.mark.parametrize("name", sorted(FILES))
def test_the_command_writes_the_same_document(
    data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    identifier, _ = NAMED.get(name, FILES[name])
    output = tmp_path / "results.json"
    assert main([str(data_dir / name), str(output), identifier, "--quiet"]) == 0
    assert capsys.readouterr() == ("", "")
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written == document_of(data_dir / name, identifier)


# -- the reader -------------------------------------------------------------------------------


def variables_of(group: Any, path: str = "") -> dict[str, Any]:
    found = {f"{path}/{name}": variable for name, variable in group.variables.items()}
    for name, child in group.groups.items():
        found.update(variables_of(child, f"{path}/{name}"))
    return found


@pytest.mark.parametrize("name", sorted(name for name in FILES if name.endswith(".nc")))
def test_the_reader_reads_what_the_netcdf_library_reads(data_dir: Path, name: str) -> None:
    with netCDF4.Dataset(data_dir / name) as expected, coati.open_dataset(data_dir / name) as found:
        variables = variables_of(expected)
        own_paths = [item.path for group in found.walk() for item in group.variables.values()]
        assert sorted(variables) == sorted(own_paths)
        for path, variable in variables.items():
            variable.set_auto_maskandscale(False)
            own = found.variable(path)
            assert own.dimensions == variable.dimensions, path
            assert own.shape == variable.shape, path
            values, read = np.asarray(variable[...]), own.read()
            if values.dtype.kind in "OU":
                assert read.tolist() == values.tolist(), path
            else:
                assert read.dtype == values.dtype, path
                np.testing.assert_array_equal(read, values, err_msg=path)
            attributes = {key: variable.getncattr(key) for key in variable.ncattrs()}
            assert sorted(own.attributes) == sorted(attributes), path


@pytest.mark.parametrize("name", sorted(name for name in FILES if name.endswith(".nc")))
def test_times_are_those_that_the_netcdf_library_finds(data_dir: Path, name: str) -> None:
    checked = 0
    with netCDF4.Dataset(data_dir / name) as expected, coati.open_dataset(data_dir / name) as found:
        for path, variable in variables_of(expected).items():
            units = getattr(variable, "units", "")
            if not isinstance(units, str) or " since " not in units:
                continue
            calendar = getattr(variable, "calendar", "standard")
            dates = netCDF4.num2date(
                variable[...], units, calendar, only_use_cftime_datetimes=False
            )
            decoded = cf.decode(found.variable(path))
            assert decoded.type_name == "datetime", path
            stamps = [str(value)[:19] for value in decoded.values.ravel()]
            assert stamps == [date.strftime("%Y-%m-%dT%H:%M:%S") for date in dates.ravel()], path
            checked += 1
    assert checked > 0
