"""Framework identifiers, and recognising the framework that wrote a file."""

from __future__ import annotations

from pathlib import Path

import h5py
import pytest
from hypothesis import given
from hypothesis import strategies as st

from coati import frameworks
from coati.errors import FrameworkError
from coati.frameworks import FAMILIES, Framework
from coati.readers import open_dataset
from support import files

# -- identifiers ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("identifier", "canonical", "text", "family"),
    [
        ("calliope-v0-6-10", "calliope-v0-6-10", "Calliope 0.6.10", "calliope-v0-6"),
        ("calliope-v6-10", "calliope-v0-6-10", "Calliope 0.6.10", "calliope-v0-6"),
        ("calliope-v0-6", "calliope-v0-6", "Calliope 0.6", "calliope-v0-6"),
        ("calliope-v6", "calliope-v0-6", "Calliope 0.6", "calliope-v0-6"),
        ("calliope-v0-7-0", "calliope-v0-7-0", "Calliope 0.7.0", "calliope-v0-7"),
        ("calliope-v7-0", "calliope-v0-7-0", "Calliope 0.7.0", "calliope-v0-7"),
        ("calliope-v0-7-0-dev7", "calliope-v0-7-0-dev7", "Calliope 0.7.0.dev7", "calliope-v0-7"),
        ("calliope-v0-7-0dev7", "calliope-v0-7-0-dev7", "Calliope 0.7.0.dev7", "calliope-v0-7"),
        ("calliope-v0.7.0.dev7", "calliope-v0-7-0-dev7", "Calliope 0.7.0.dev7", "calliope-v0-7"),
        ("calliope_v0_7_0", "calliope-v0-7-0", "Calliope 0.7.0", "calliope-v0-7"),
        ("Calliope-V0.7.0", "calliope-v0-7-0", "Calliope 0.7.0", "calliope-v0-7"),
        ("  calliope-v0-7-0  ", "calliope-v0-7-0", "Calliope 0.7.0", "calliope-v0-7"),
        ("calliope v0.7.0", "calliope-v0-7-0", "Calliope 0.7.0", "calliope-v0-7"),
        ("calliopev0-7-0", "calliope-v0-7-0", "Calliope 0.7.0", "calliope-v0-7"),
        ("pypsa-v1-2-4", "pypsa-v1-2-4", "PyPSA 1.2.4", "pypsa-v1"),
        ("pypsa-v1", "pypsa-v1", "PyPSA 1", "pypsa-v1"),
        ("pypsa-v1-0-0rc1", "pypsa-v1-0-0rc1", "PyPSA 1.0.0rc1", "pypsa-v1"),
        ("pypsa-v0-35-2", "pypsa-v0-35-2", "PyPSA 0.35.2", "pypsa-v0"),
        ("pypsa-v35-2", "pypsa-v0-35-2", "PyPSA 0.35.2", "pypsa-v0"),
        ("pypsa-v0-25", "pypsa-v0-25", "PyPSA 0.25", "pypsa-v0"),
        ("pypsa-v0", "pypsa-v0", "PyPSA 0", "pypsa-v0"),
        ("PyPSA-v1.3.0", "pypsa-v1-3-0", "PyPSA 1.3.0", "pypsa-v1"),
        ("adopt-net0-v0-1-10", "adopt-net0-v0-1-10", "AdOpT-NET0 0.1.10", "adopt-net0-v0-1"),
        ("adopt-net0-v1-10", "adopt-net0-v0-1-10", "AdOpT-NET0 0.1.10", "adopt-net0-v0-1"),
        ("adoptnet0-v0-1-10", "adopt-net0-v0-1-10", "AdOpT-NET0 0.1.10", "adopt-net0-v0-1"),
        ("adopt_net0-v0.1.10", "adopt-net0-v0-1-10", "AdOpT-NET0 0.1.10", "adopt-net0-v0-1"),
        ("AdOpT-NET0-v0.1.10", "adopt-net0-v0-1-10", "AdOpT-NET0 0.1.10", "adopt-net0-v0-1"),
        ("adopt-v0-1-10", "adopt-net0-v0-1-10", "AdOpT-NET0 0.1.10", "adopt-net0-v0-1"),
    ],
)
def test_an_identifier_names_a_framework_and_a_version(
    identifier: str, canonical: str, text: str, family: str
) -> None:
    found = frameworks.parse(identifier)
    assert found is not None
    assert found.id == canonical
    assert str(found) == text
    assert found.family is not None
    assert found.family.id == family
    assert found.supported


@pytest.mark.parametrize(
    ("identifier", "name", "canonical", "text"),
    [
        ("calliope", "calliope", "calliope", "Calliope"),
        ("pypsa", "pypsa", "pypsa", "PyPSA"),
        ("PyPSA", "pypsa", "pypsa", "PyPSA"),
        ("adopt-net0", "adopt-net0", "adopt-net0-v0-1", "AdOpT-NET0 0.1.x"),
        ("adoptnet0", "adopt-net0", "adopt-net0-v0-1", "AdOpT-NET0 0.1.x"),
        ("adopt_net0", "adopt-net0", "adopt-net0-v0-1", "AdOpT-NET0 0.1.x"),
    ],
)
def test_an_identifier_may_leave_the_version_to_the_file(
    identifier: str, name: str, canonical: str, text: str
) -> None:
    found = frameworks.parse(identifier)
    assert found is not None
    assert found.name == name
    assert found.version is None
    assert found.id == canonical
    assert str(found) == text


def test_a_framework_with_one_family_has_that_family() -> None:
    assert frameworks.parse("adopt-net0").family.id == "adopt-net0-v0-1"
    assert frameworks.parse("calliope").family is None
    assert frameworks.parse("pypsa").family is None


@pytest.mark.parametrize("identifier", ["auto", "AUTO", " Auto "])
def test_auto_names_nothing(identifier: str) -> None:
    assert frameworks.parse(identifier) is None


@pytest.mark.parametrize(
    ("identifier", "message"),
    [
        ("calliope-v0-8-0", "Calliope 0.8.0 is not supported; supported are calliope-v0-6 (0.6.x)"),
        ("calliope-v8-0", "Calliope 8.0 is not supported"),
        ("calliope-v1", "Calliope 1 is not supported"),
        ("calliope-v0-5-5", "Calliope 0.5.5 is not supported"),
        ("pypsa-v2-0", "PyPSA 2.0 is not supported; supported are pypsa-v0 (0.25 and later 0.x)"),
        ("pypsa-v0-17-1", "PyPSA 0.17.1 is not supported"),
        ("adopt-net0-v0-2-0", "AdOpT-NET0 0.2.0 is not supported; supported are adopt-net0-v0-1"),
        (
            "osemosys-v1",
            "names an unknown framework; the frameworks are adopt-net0, calliope, pypsa",
        ),
        ("oemof", "names an unknown framework"),
        ("calliope-vx", "'x' is not a version"),
        ("calliope-v0-6-10-final", "'0-6-10-final' is not a version"),
        ("calliope-v0-dev1-6", "'0-dev1-6' is not a version"),
        ("", "is not a framework identifier; expected for example calliope-v0-6-10"),
        ("v1-2", "is not a framework identifier"),
        ("calliope-", "is not a framework identifier"),
        ("-v0-6", "is not a framework identifier"),
        ("0-6-10", "is not a framework identifier"),
        ("calliope/v0-6", "is not a framework identifier"),
    ],
)
def test_an_identifier_that_names_nothing_is_refused(identifier: str, message: str) -> None:
    with pytest.raises(FrameworkError) as caught:
        frameworks.parse(identifier)
    assert message in str(caught.value)
    assert repr(identifier) in str(caught.value)


def test_the_families() -> None:
    assert [family.id for family in FAMILIES] == [
        "calliope-v0-6",
        "calliope-v0-7",
        "pypsa-v0",
        "pypsa-v1",
        "adopt-net0-v0-1",
    ]
    assert frameworks.families() == FAMILIES
    assert [family.id for family in frameworks.families("pypsa")] == ["pypsa-v0", "pypsa-v1"]
    assert frameworks.families("oemof") == ()


@pytest.mark.parametrize("family", FAMILIES, ids=lambda family: family.id)
def test_a_family_is_described(family: frameworks.Family) -> None:
    assert family.id == frameworks.parse(family.id).id
    assert family.tested
    assert family.formats
    assert family.layout
    assert family.since[: len(family.series)] == family.series
    for version in family.tested:
        found = frameworks.parse(f"{family.framework}-v{version}")
        assert found.family is family
        assert found.version == version


def test_the_versions_of_a_family() -> None:
    by_id = {family.id: family for family in FAMILIES}
    assert by_id["calliope-v0-7"].versions == "0.7.x"
    assert by_id["pypsa-v0"].versions == "0.25 and later 0.x"
    assert by_id["pypsa-v0"].covers((0, 25))
    assert by_id["pypsa-v0"].covers((0, 35, 2))
    assert not by_id["pypsa-v0"].covers((0, 24, 9))
    assert not by_id["pypsa-v0"].covers((1, 0))


@given(
    st.sampled_from(FAMILIES),
    st.lists(st.integers(0, 99), max_size=3),
    st.sampled_from(["", "dev3", "rc1", "a2", "b1", "post4"]),
    st.sampled_from(["-", ".", "_"]),
)
def test_every_version_of_a_family_is_accepted_however_it_is_written(
    family: frameworks.Family, further: list[int], suffix: str, separator: str
) -> None:
    numbers = [*family.since, *further]
    version = separator.join(str(number) for number in numbers)
    version += (separator + suffix) if suffix else ""
    found = frameworks.parse(f"{family.framework}{separator}v{version}")
    assert found.family is family
    assert found.version.startswith(".".join(str(number) for number in numbers))
    assert frameworks.parse(found.id) == found


# -- recognising the framework ----------------------------------------------------------------


def detect(path: Path) -> Framework | None:
    with open_dataset(path) as dataset:
        return frameworks.detect(dataset)


def test_calliope_0_7(tmp_path: Path) -> None:
    found = detect(files.calliope07(tmp_path / "model.nc"))
    assert found == Framework("calliope", "0.7.0", frameworks.parse("calliope-v0-7").family)


def test_a_preview_of_calliope_0_7(tmp_path: Path) -> None:
    found = detect(files.calliope07(tmp_path / "model.nc", version="0.7.0.dev7"))
    assert found.id == "calliope-v0-7-0-dev7"


def test_calliope_0_7_without_a_record_of_the_run(tmp_path: Path) -> None:
    path = files.write_netcdf(
        tmp_path / "model.nc",
        {
            "groups": {
                "inputs": {
                    "dimensions": {"techs": 1},
                    "variables": {"base_tech": (("techs",), ["supply"])},
                }
            }
        },
    )
    found = detect(path)
    assert found.id == "calliope-v0-7"
    assert found.version is None


def test_calliope_0_6(tmp_path: Path) -> None:
    assert detect(files.calliope06(tmp_path / "model.nc")).id == "calliope-v0-6-10"


def test_calliope_0_6_without_a_version(tmp_path: Path) -> None:
    path = files.write_netcdf(
        tmp_path / "model.nc",
        {
            "dimensions": {"loc_techs": 1, "techs": 1},
            "variables": {"energy_cap": (("loc_techs",), [1.0])},
        },
    )
    assert detect(path).id == "calliope-v0-6"


@pytest.mark.parametrize(
    ("version", "identifier"),
    [("1.2.4", "pypsa-v1-2-4"), ("0.35.2", "pypsa-v0-35-2"), ("0.25.2", "pypsa-v0-25-2")],
)
def test_pypsa(tmp_path: Path, version: str, identifier: str) -> None:
    assert detect(files.pypsa_netcdf(tmp_path / "network.nc", version=version)).id == identifier
    assert detect(files.pypsa_hdf5(tmp_path / "network.h5", version=version)).id == identifier


def test_pypsa_without_a_version(tmp_path: Path) -> None:
    path = files.write_netcdf(
        tmp_path / "network.nc",
        {"dimensions": {"snapshots": 1, "buses_i": 1}, "variables": {}},
    )
    found = detect(path)
    assert found.id == "pypsa-v1"
    assert found.version is None


def test_adopt_net0_records_no_version(tmp_path: Path) -> None:
    found = detect(files.adopt_net0(tmp_path / "results.h5"))
    assert found.id == "adopt-net0-v0-1"
    assert found.version is None
    assert detect(files.adopt_net0(tmp_path / "upper.h5", capitalised=True)).id == found.id


def test_a_file_of_no_framework(tmp_path: Path) -> None:
    path = files.write_netcdf(
        tmp_path / "data.nc", {"dimensions": {"x": 2}, "variables": {"x": (("x",), [1.0, 2.0])}}
    )
    assert detect(path) is None
    plain = tmp_path / "plain.h5"
    with h5py.File(plain, "w") as file:
        file.create_group("summary")
        file.create_group("design")
        file.create_group("operation/other")
    assert detect(plain) is None


def test_a_version_that_is_not_known_is_read_like_the_nearest(tmp_path: Path) -> None:
    found = detect(files.pypsa_netcdf(tmp_path / "network.nc", version="2.1.0"))
    assert found.version == "2.1.0"
    assert found.family.id == "pypsa-v1"
    assert not found.supported
    found = detect(files.pypsa_netcdf(tmp_path / "other.nc", version="unknown"))
    assert found.version == "unknown"
    assert not found.supported


# -- identifier and file together -------------------------------------------------------------


def resolve(path: Path, identifier: str | None) -> tuple[Framework, list[str]]:
    with open_dataset(path) as dataset:
        return frameworks.resolve(identifier, dataset)


@pytest.mark.parametrize("identifier", [None, "auto", "calliope", "calliope-v0-7", "calliope-v7-0"])
def test_an_identifier_that_fits_the_file(tmp_path: Path, identifier: str | None) -> None:
    found, remarks = resolve(files.calliope07(tmp_path / "model.nc"), identifier)
    assert found.id == "calliope-v0-7-0"
    assert found.family.id == "calliope-v0-7"
    assert remarks == []


def test_another_version_of_the_family_is_a_remark(tmp_path: Path) -> None:
    found, remarks = resolve(files.calliope07(tmp_path / "model.nc"), "calliope-v0-7-0-dev7")
    assert found.version == "0.7.0"
    assert remarks == [
        "the file states Calliope 0.7.0; it is read as such, although Calliope 0.7.0.dev7 was named"
    ]


def test_the_version_of_the_identifier_fills_in_for_a_file_without_one(tmp_path: Path) -> None:
    found, remarks = resolve(files.adopt_net0(tmp_path / "results.h5"), "adopt-net0-v0-1-10")
    assert found.version == "0.1.10"
    assert remarks == []


def test_another_family_is_refused(tmp_path: Path) -> None:
    path = files.calliope07(tmp_path / "model.nc")
    with pytest.raises(FrameworkError) as caught:
        resolve(path, "calliope-v0-6-10")
    assert str(caught.value) == (
        f"{path}: the file has the layout of Calliope 0.7.0,"
        " which differs from that of Calliope 0.6.10"
    )
    with pytest.raises(FrameworkError, match=r"the layout of PyPSA 1\.2\.4, which differs"):
        resolve(files.pypsa_netcdf(tmp_path / "network.nc"), "pypsa-v0-35-2")


def test_another_framework_is_refused(tmp_path: Path) -> None:
    path = files.calliope07(tmp_path / "model.nc")
    with pytest.raises(FrameworkError) as caught:
        resolve(path, "pypsa-v1-2-4")
    assert (
        str(caught.value) == f"{path}: the file was written by Calliope 0.7.0, not by PyPSA 1.2.4"
    )


def test_a_file_of_no_framework_is_refused(tmp_path: Path) -> None:
    path = files.write_netcdf(tmp_path / "data.nc", {"attributes": {"title": "x"}})
    with pytest.raises(FrameworkError, match="the file has the layout of no known framework"):
        resolve(path, None)
    with pytest.raises(FrameworkError, match="the file does not have the layout of Calliope"):
        resolve(path, "calliope-v0-7-0")


def test_an_identifier_that_names_nothing_is_refused_before_the_file_is_looked_at(
    tmp_path: Path,
) -> None:
    with pytest.raises(FrameworkError, match="names an unknown framework"):
        resolve(files.calliope07(tmp_path / "model.nc"), "oemof-v1")


def test_a_version_that_is_not_known_is_a_remark(tmp_path: Path) -> None:
    path = files.pypsa_netcdf(tmp_path / "network.nc", version="2.1.0")
    found, remarks = resolve(path, None)
    assert found.version == "2.1.0"
    assert remarks == [
        "the file states PyPSA 2.1.0, a version Coati does not know; it is read like PyPSA 1.x"
    ]
    assert resolve(path, "pypsa-v1")[1] == [
        *remarks,
        "the file states PyPSA 2.1.0; it is read as such, although PyPSA 1 was named",
    ]


@pytest.mark.parametrize(
    ("named", "stated", "agrees"),
    [
        ("0.7.0", "0.7.0", True),
        ("0.7", "0.7.0", True),
        ("0.7", "0.7.0.dev7", True),
        ("1", "1.2.4", True),
        ("0.7.0", "0.7.0.dev7", False),
        ("0.7.0.dev7", "0.7.0", False),
        ("0.7.0.dev6", "0.7.0.dev7", False),
        ("0.6.8", "0.6.10", False),
        ("1.2", "1.3.0", False),
        ("1.2.4.0", "1.2.4", False),
        ("1", "unknown", False),
    ],
)
def test_a_part_of_a_version_agrees_with_the_version(
    tmp_path: Path, named: str, stated: str, agrees: bool
) -> None:
    path = files.pypsa_netcdf(tmp_path / "network.nc", version=stated)
    with open_dataset(path) as dataset:
        detected = frameworks.detect(dataset)
        declared = Framework("pypsa", named, detected.family)
        _, remarks = frameworks._reconcile(declared, detected)
    assert (not any("although" in remark for remark in remarks)) is agrees
