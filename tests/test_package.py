"""The package and the repository around it: what they state must agree."""

from __future__ import annotations

import re
import sys
from importlib import metadata, resources
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.version import Version

import coati
from coati import cli

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

ROOT = Path(__file__).parent.parent

#: The keys of the citation files of the organisation, in their order.
CITATION_KEYS = [
    "cff-version",
    "title",
    "message",
    "type",
    "abstract",
    "authors",
    "repository-code",
    "url",
    "license",
    "version",
    "date-released",
]


def read(name: str) -> str:
    path = ROOT / name
    if not path.is_file():
        pytest.skip(f"{name} is not part of what is tested here")
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def project() -> dict[str, Any]:
    return tomllib.loads(read("pyproject.toml"))["project"]


# -- the version ------------------------------------------------------------------------------


def test_the_version_is_written_as_python_writes_versions() -> None:
    assert str(Version(coati.__version__)) == coati.__version__


def test_the_citation_names_the_version() -> None:
    citation = yaml.safe_load(read("CITATION.cff"))
    assert Version(citation["version"]) == Version(coati.__version__)


def test_the_changelog_names_the_version_or_what_is_to_come() -> None:
    headings = re.findall(r"(?m)^## \[([^\]]+)\]", read("CHANGELOG.md"))
    assert headings
    assert len(headings) == len(set(headings))
    released = [Version(heading) for heading in headings if heading != "Unreleased"]
    assert released == sorted(released, reverse=True)
    if "Unreleased" not in headings:
        assert released[0] == Version(coati.__version__)
    for version in released:
        assert version <= Version(coati.__version__)


def test_the_installed_package_has_the_version() -> None:
    try:
        installed = metadata.version("enerplanet-coati")
    except metadata.PackageNotFoundError:
        pytest.skip("the package is not installed")
    assert Version(installed) == Version(coati.__version__)


# -- the citation -----------------------------------------------------------------------------


def test_the_citation_has_the_keys_of_the_organisation() -> None:
    # As the citation files of MEME, TentaCron and T1K have them.
    text = read("CITATION.cff")
    assert re.findall(r"(?m)^([a-z-]+):", text) == CITATION_KEYS
    assert text.startswith("# CITATION.cff — citation metadata for Coati.\n")
    citation = yaml.safe_load(text)
    assert citation["cff-version"] == "1.2.0"
    assert citation["type"] == "software"
    assert citation["license"] == "MIT"
    assert citation["repository-code"] == "https://github.com/enerplanet/Coati"
    assert citation["url"] == "https://enerplanet.github.io/Coati"
    assert re.fullmatch(r"\d+\.\d+\.\d+(-(alpha|beta|rc\d*))?", citation["version"])
    assert list(citation["authors"][0]) == ["family-names", "given-names", "orcid", "affiliation"]


# -- the package ------------------------------------------------------------------------------


def test_the_package_says_that_it_is_typed() -> None:
    assert resources.files("coati").joinpath("py.typed").is_file()


@pytest.mark.parametrize("name", ["results", "dataset"])
def test_the_schemas_are_part_of_the_package(name: str) -> None:
    assert resources.files("coati.schemas").joinpath(f"{name}.schema.json").is_file()


def test_the_command_is_that_of_the_package(project: dict[str, Any]) -> None:
    assert project["scripts"] == {"coati": "coati.cli:main"}
    assert cli.main is coati.cli.main
    try:
        found = metadata.distribution("enerplanet-coati").entry_points
    except metadata.PackageNotFoundError:
        return
    commands = {point.name: point.value for point in found if point.group == "console_scripts"}
    assert commands == {"coati": "coati.cli:main"}


def test_the_metadata(project: dict[str, Any]) -> None:
    assert project["name"] == "enerplanet-coati"
    assert project["license"] == "MIT"
    assert project["requires-python"] == ">=3.10"
    assert [Requirement(text).name for text in project["dependencies"]] == ["h5py", "numpy"]
    versions = re.findall(r"Python :: (3\.\d+)", "\n".join(project["classifiers"]))
    assert versions[0] == project["requires-python"].removeprefix(">=")
    assert versions == sorted(versions, key=Version)
    # Nothing that names a person is part of the metadata but the name of the author.
    assert all(set(entry) == {"name"} for entry in project["authors"] + project["maintainers"])


def test_the_documentation_is_built_with_what_the_extra_names(project: dict[str, Any]) -> None:
    listed = [
        line.strip()
        for line in read("docs/requirements.txt").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert sorted(listed) == sorted(project["optional-dependencies"]["docs"])


# -- the artwork ------------------------------------------------------------------------------

#: An image of a page in Markdown: what it shows, without a title.
IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")

#: A link of a page in Markdown that leads neither to a site nor to a place on the page.
RELATIVE = re.compile(r"\]\((?!https?://|#)([^)\s]+)\)")

LOGOS = ROOT / "docs" / "assets" / "logos"


@pytest.mark.parametrize(
    ("page", "schemes"),
    [
        ("README.md", ["gh-dark-mode-only", "gh-light-mode-only"]),
        ("docs/index.md", ["only-dark", "only-light"]),
    ],
)
def test_the_banner_is_shown_for_both_colour_schemes(page: str, schemes: list[str]) -> None:
    above_the_title = read(page).split("# Coati")[0]
    shown = IMAGE.findall(above_the_title)
    assert [target.partition("#")[2] for target in shown] == schemes
    names = [Path(target.partition("#")[0]).name for target in shown]
    assert names == ["coati-banner-dark.png", "coati-banner-light.png"]


def test_the_images_of_the_pages_exist() -> None:
    pages = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
    if not pages[0].is_file():
        pytest.skip("the pages are not part of what is tested here")
    for page in pages:
        for target in IMAGE.findall(page.read_text(encoding="utf-8")):
            if not target.startswith(("http://", "https://")):
                image = page.parent / target.partition("#")[0]
                assert image.is_file(), f"{page.relative_to(ROOT)} shows {target}"


def test_the_badges_read_files_that_exist() -> None:
    # A badge that reads a file of the repository says "not found" once the file is renamed.
    raw = "https://raw.githubusercontent.com/enerplanet/Coati/main/"
    read_by_badges = [
        unquote(address).partition(raw)[2].partition("&")[0]
        for address in IMAGE.findall(read("README.md"))
        if raw in unquote(address)
    ]
    assert sorted(read_by_badges) == ["CITATION.cff", "pyproject.toml"]
    for name in read_by_badges:
        assert (ROOT / name).is_file()


def test_no_badge_asks_pypi_before_the_first_release() -> None:
    # PyPI knows a project from its first release on; until then its badges say "not found".
    released = re.findall(r"(?m)^## \[(\d[^\]]*)\]", read("CHANGELOG.md"))
    asking = [address for address in IMAGE.findall(read("README.md")) if "/pypi/" in address]
    assert released or not asking


@pytest.mark.parametrize("key", ["favicon", "logo"])
def test_the_documentation_has_the_mark_of_the_project(key: str) -> None:
    found = re.search(rf"(?m)^  {key}: (\S+)", read("mkdocs.yml"))
    assert found is not None
    assert found[1].startswith("assets/logos/coati-")
    assert (ROOT / "docs" / found[1]).is_file()


def test_the_vector_images_run_nothing_and_load_nothing() -> None:
    images = sorted(LOGOS.glob("*.svg"))
    if not images:
        pytest.skip("the artwork is not part of what is tested here")
    for image in images:
        text = image.read_text(encoding="utf-8").lower()
        for unwanted in ("<script", "<foreignobject", "<image", "href=", "onload=", "onclick="):
            assert unwanted not in text, f"{image.name} holds {unwanted}"


def test_the_description_on_pypi_has_no_banner_and_no_links_into_the_repository() -> None:
    # PyPI shows neither images of the repository nor what a relative link points to.
    try:
        description = metadata.metadata("enerplanet-coati").get_payload()
    except metadata.PackageNotFoundError:
        pytest.skip("the package is not installed")
    assert description.startswith("# Coati\n")
    assert RELATIVE.findall(description) == []
    assert all(target.startswith("https://") for target in IMAGE.findall(description))
    readme = read("README.md")
    assert len(description.splitlines()) == len(readme[readme.index("# Coati") :].splitlines())


# -- what is said about the frameworks --------------------------------------------------------


def test_every_version_that_is_called_tested_has_a_file() -> None:
    data = ROOT / "tests" / "data"
    if not data.is_dir():
        pytest.skip("the files of the tests are not part of what is tested here")
    for family in coati.FAMILIES:
        for version in family.tested:
            found = [
                path.name
                for path in data.glob(f"{family.framework}-{version}.*.xz")
                if path.name.split(".")[-2] in ("nc", "h5")
            ]
            assert found, f"{family.title} {version} has no file under tests/data"


@pytest.mark.parametrize("page", ["README.md", "docs/frameworks/overview.md"])
def test_the_documentation_lists_the_families(page: str) -> None:
    text = read(page)
    rows = {
        cells[0].strip("` "): [cell.strip() for cell in cells[1:]]
        for cells in (line.strip("|").split("|") for line in text.splitlines() if "|" in line)
        if cells[0].strip("` ") in {family.id for family in coati.FAMILIES}
    }
    assert list(rows) == [family.id for family in coati.FAMILIES]
    for family in coati.FAMILIES:
        framework, versions, tested, formats = rows[family.id]
        assert family.title in framework
        assert versions == family.versions
        assert tested == ", ".join(family.tested)
        names = {"netcdf4": "netCDF-4", "hdf5": "HDF5"}
        assert formats == ", ".join(names[name] for name in family.formats)


def test_the_documentation_shows_the_list_of_the_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["frameworks"]) == 0
    printed = capsys.readouterr().out
    assert printed in read("docs/usage/cli.md")
