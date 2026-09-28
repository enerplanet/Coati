"""The modelling frameworks Coati knows, their identifiers and their recognition.

A *framework identifier* names a framework and, optionally, a version:

```text
calliope-v0-6-10      Calliope 0.6.10
pypsa-v1-2-4          PyPSA 1.2.4
adopt-net0-v0-1-10    AdOpT-NET0 0.1.10
calliope              Calliope, version taken from the file
auto                  framework and version taken from the file
```

The parts of a version are separated by `-`, `.` or `_`. For a framework
whose versions start with zero, the zero may be left out where that is
unambiguous: `calliope-v6-10` is Calliope 0.6.10.

What decides how a file is read is not the exact version but the *family*: the
range of versions that write the same layout. Calliope 0.6 and 0.7, for
example, are two families, because their files have nothing in common. A
version is accepted if it belongs to a family, whether or not that very version
has been tested; `Family.tested` lists the versions that have.

An identifier is a claim about a file. `resolve` checks the claim against
what `detect` finds in the file and refuses a file of another framework
or family, so that a mix-up in a pipeline is an error and not a document full
of wrong numbers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from coati import yamltext
from coati.errors import FrameworkError
from coati.model import Dataset, Group
from coati.readers import pytables

__all__ = [
    "AUTO",
    "FAMILIES",
    "Family",
    "Framework",
    "detect",
    "families",
    "parse",
    "resolve",
]

#: The identifier that leaves framework and version to the file.
AUTO: Final = "auto"


@dataclass(frozen=True)
class Family:
    """A range of versions of a framework that write the same layout.

    Attributes:
        id: The identifier of the family, for example `calliope-v0-7`.
        framework: The identifier of the framework, for example `calliope`.
        title: The name of the framework as its authors write it.
        series: The leading parts of the versions that belong to the family.
        since: The oldest version of the series that the family covers.
        tested: The versions whose files are part of the test suite.
        formats: The file formats in which the family stores results.
        layout: A description of the layout in a few words.
    """

    id: str
    framework: str
    title: str
    series: tuple[int, ...]
    since: tuple[int, ...]
    tested: tuple[str, ...]
    formats: tuple[str, ...]
    layout: str

    @property
    def versions(self) -> str:
        """The versions of the family, for example `0.7.x` or `0.25 and later 0.x`."""
        series = ".".join(str(part) for part in self.series)
        if self.since == self.series:
            return f"{series}.x"
        return f"{'.'.join(str(part) for part in self.since)} and later {series}.x"

    def covers(self, numbers: tuple[int, ...]) -> bool:
        """Tell whether the version with the parts `numbers` belongs to the family.

        A version may name fewer parts than the oldest version of the family
        has: `0` stands for the family that starts with `0.25`.
        """
        if numbers[: len(self.series)] != self.series:
            return False
        return numbers >= self.since or self.since[: len(numbers)] == numbers


#: The families, in the order in which they are listed.
FAMILIES: Final[tuple[Family, ...]] = (
    Family(
        id="calliope-v0-6",
        framework="calliope",
        title="Calliope",
        series=(0, 6),
        since=(0, 6),
        tested=("0.6.10",),
        formats=("netcdf4",),
        layout="one group; sets that join location, technology and carrier",
    ),
    Family(
        id="calliope-v0-7",
        framework="calliope",
        title="Calliope",
        series=(0, 7),
        since=(0, 7),
        tested=("0.7.0.dev7", "0.7.0"),
        formats=("netcdf4",),
        layout="the groups inputs, results and attrs; dimensions nodes, techs and carriers",
    ),
    Family(
        id="pypsa-v0",
        framework="pypsa",
        title="PyPSA",
        series=(0,),
        since=(0, 25),
        tested=("0.25.2", "0.35.2"),
        formats=("netcdf4", "hdf5"),
        layout="one table per component, written by export_to_netcdf or export_to_hdf5",
    ),
    Family(
        id="pypsa-v1",
        framework="pypsa",
        title="PyPSA",
        series=(1,),
        since=(1,),
        tested=("1.2.4", "1.3.0"),
        formats=("netcdf4", "hdf5"),
        layout="one table per component, written by export_to_netcdf or export_to_hdf5",
    ),
    Family(
        id="adopt-net0-v0-1",
        framework="adopt-net0",
        title="AdOpT-NET0",
        series=(0, 1),
        since=(0, 1),
        tested=("0.1.10",),
        formats=("hdf5",),
        layout="the groups summary, topology, design and operation",
    ),
)

_TITLES: Final = {family.framework: family.title for family in FAMILIES}

# Spellings of the names of the frameworks, reduced to letters and digits.
_ALIASES: Final = {
    "calliope": "calliope",
    "pypsa": "pypsa",
    "adoptnet0": "adopt-net0",
    "adopt": "adopt-net0",
}

_IDENTIFIER: Final = re.compile(
    r"""^
    (?P<name>[a-z][a-z0-9]*(?:[-_.\s]+[a-z][a-z0-9]*)*?)
    (?:[-_.\s]*v[-_.\s]*(?P<version>\d[a-z0-9]*(?:[-_.][a-z0-9]+)*))?
    $""",
    re.X,
)

_PART: Final = re.compile(r"^(?P<number>\d+)(?P<suffix>(?:a|b|c|rc|dev|post)\d*)?$")
_SUFFIX: Final = re.compile(r"^(?:a|b|c|rc|dev|post)\d*$")


@dataclass(frozen=True)
class Framework:
    """A framework, as named by an identifier or as found in a file.

    Attributes:
        name: The identifier of the framework, for example `calliope`.
        version: The version, for example `0.6.10`; `None` if unknown.
        family: The family the version belongs to; `None` if the version is
            unknown and the framework has more than one family.
        supported: Whether the version belongs to the family. It does not if a
            file states a version that Coati does not know; the file is then
            read like the family whose layout it has.
    """

    name: str
    version: str | None = None
    family: Family | None = None
    supported: bool = True

    @property
    def title(self) -> str:
        """The name of the framework as its authors write it."""
        return _TITLES[self.name]

    @property
    def id(self) -> str:
        """The identifier with the most detail known, for example `calliope-v0-6-10`."""
        if self.version is not None:
            return f"{self.name}-v{re.sub(r'[.]', '-', self.version)}"
        return self.family.id if self.family is not None else self.name

    def __str__(self) -> str:
        if self.version is not None:
            return f"{self.title} {self.version}"
        if self.family is not None:
            return f"{self.title} {self.family.versions}"
        return self.title


def families(framework: str | None = None) -> tuple[Family, ...]:
    """Return the families, of one framework if `framework` is given."""
    if framework is None:
        return FAMILIES
    return tuple(family for family in FAMILIES if family.framework == framework)


def parse(identifier: str) -> Framework | None:
    """Parse a framework identifier.

    Args:
        identifier: An identifier as described in the documentation of this module.

    Returns:
        The framework the identifier names, or `None` for `auto`.

    Raises:
        FrameworkError: The identifier is malformed or names a framework or a
            version that Coati does not know.
    """
    text = identifier.strip().lower()
    if text == AUTO:
        return None
    match = _IDENTIFIER.match(text)
    if match is None:
        raise FrameworkError(
            f"{identifier!r} is not a framework identifier; expected for example {_example()}"
        )
    spelling = re.sub(r"[^a-z0-9]", "", match["name"])
    name = _ALIASES.get(spelling)
    if name is None:
        for alias in _ALIASES:
            if spelling.startswith(alias + "v"):
                raise FrameworkError(
                    f"{identifier!r}: {spelling[len(alias) + 1 :]!r} is not a version"
                )
        known = ", ".join(sorted(_TITLES))
        raise FrameworkError(
            f"{identifier!r} names an unknown framework; the frameworks are {known}"
        )
    if match["version"] is None:
        candidates = families(name)
        return Framework(name, None, candidates[0] if len(candidates) == 1 else None)
    numbers, suffix = _split_version(match["version"], identifier)
    family, numbers = _family_of(name, numbers, identifier)
    return Framework(name, _join_version(numbers, suffix), family)


def _example() -> str:
    family = FAMILIES[0]
    return f"{family.framework}-v{family.tested[0].replace('.', '-')!s}"


def _split_version(text: str, identifier: str) -> tuple[tuple[int, ...], str]:
    """Split the text of a version into its numbers and its suffix, such as `dev7`."""
    numbers: list[int] = []
    suffix = ""
    for part in re.split(r"[-_.]", text):
        match = _PART.match(part)
        if suffix or (match is None and not _SUFFIX.match(part)):
            raise FrameworkError(f"{identifier!r}: {text!r} is not a version")
        if match is None:
            suffix = part
        else:
            numbers.append(int(match["number"]))
            suffix = match["suffix"] or ""
    return tuple(numbers), suffix


def _join_version(numbers: tuple[int, ...], suffix: str) -> str:
    version = ".".join(str(number) for number in numbers)
    if not suffix:
        return version
    return version + suffix if suffix.startswith(("a", "b", "c", "rc")) else f"{version}.{suffix}"


def _family_of(
    name: str, numbers: tuple[int, ...], identifier: str
) -> tuple[Family, tuple[int, ...]]:
    """Return the family of a version and the version with its leading zero."""
    for candidate in (numbers, (0, *numbers)):
        matching = [family for family in families(name) if family.covers(candidate)]
        if matching:
            return max(matching, key=lambda family: len(family.series)), candidate
    version = ".".join(str(number) for number in numbers)
    supported = ", ".join(f"{family.id} ({family.versions})" for family in families(name))
    raise FrameworkError(
        f"{identifier!r}: {_TITLES[name]} {version} is not supported; supported are {supported}"
    )


def detect(dataset: Dataset) -> Framework | None:
    """Recognise the framework that wrote `dataset`.

    Returns:
        The framework with the version the file states, or `None` if the
        file has the layout of no known framework.
    """
    for recognise in (_detect_calliope, _detect_pypsa, _detect_adopt_net0):
        found = recognise(dataset)
        if found is not None:
            return found
    return None


def _with_family(name: str, version: str | None, fallback: str) -> Framework:
    """Return the framework with the family of `version`, or the family `fallback`."""
    by_id = {family.id: family for family in FAMILIES}
    if version is None:
        return Framework(name, None, by_id[fallback])
    try:
        numbers, suffix = _split_version(version, version)
    except FrameworkError:
        return Framework(name, version, by_id[fallback], supported=False)
    for family in families(name):
        if family.covers(numbers):
            return Framework(name, _join_version(numbers, suffix), family)
    return Framework(name, _join_version(numbers, suffix), by_id[fallback], supported=False)


def _detect_calliope(dataset: Dataset) -> Framework | None:
    records = dataset.groups.get("attrs")
    if records is not None and {"inputs", "results"} & set(dataset.groups):
        runtime = records.attributes.get("runtime")
        config = records.attributes.get("config")
        version = yamltext.scalar(runtime, "calliope_version_initialised") or yamltext.scalar(
            config, "init", "calliope_version"
        )
        return _with_family("calliope", version, "calliope-v0-7")
    if "inputs" in dataset.groups and "base_tech" in dataset.groups["inputs"].variables:
        return _with_family("calliope", None, "calliope-v0-7")
    version = dataset.attributes.get("calliope_version")
    if isinstance(version, str):
        return _with_family("calliope", version, "calliope-v0-6")
    if "loc_techs" in dataset.dimensions and "techs" in dataset.dimensions:
        return _with_family("calliope", None, "calliope-v0-6")
    return None


def _detect_pypsa(dataset: Dataset) -> Framework | None:
    version = dataset.attributes.get("network_pypsa_version")
    if isinstance(version, str):
        return _with_family("pypsa", version, "pypsa-v1")
    if "snapshots" in dataset.dimensions and any(
        name.endswith("_i") for name in dataset.dimensions
    ):
        return _with_family("pypsa", None, "pypsa-v1")
    network = dataset.groups.get("network")
    if network is not None and "snapshots" in dataset.groups and pytables.is_frame(network):
        found = pytables.read_frame(network).column("pypsa_version")
        version = str(found[0]) if found is not None and found.size else None
        return _with_family("pypsa", version, "pypsa-v1")
    return None


def _detect_adopt_net0(dataset: Dataset) -> Framework | None:
    groups = {name.lower(): group for name, group in dataset.groups.items()}
    if not {"summary", "design", "operation"} <= set(groups):
        return None
    parts = {name.lower() for name in groups["operation"].groups}
    if not {"technology_operation", "energy_balance"} & parts:
        return None
    return _with_family("adopt-net0", None, "adopt-net0-v0-1")


def resolve(identifier: str | None, dataset: Dataset) -> tuple[Framework, list[str]]:
    """Decide as which framework `dataset` is read.

    Args:
        identifier: The framework the caller names; `None` or `auto` to
            rely on the file alone.
        dataset: The file.

    Returns:
        The framework, with the family that determines the layout, and
        remarks about differences that do not prevent the conversion.

    Raises:
        FrameworkError: The identifier is invalid, the file has the layout of
            another framework or family than the identifier names, or the
            file has no known layout and the identifier does not settle it.
    """
    declared = parse(identifier) if identifier is not None else None
    detected = detect(dataset)
    if declared is None:
        if detected is None:
            raise FrameworkError(
                f"{_source(dataset)}: the file has the layout of no known framework"
            )
        return detected, _remarks(detected)
    if detected is None:
        raise FrameworkError(
            f"{_source(dataset)}: the file does not have the layout of {declared.title}"
        )
    if detected.name != declared.name:
        raise FrameworkError(
            f"{_source(dataset)}: the file was written by {detected}, not by {declared}"
        )
    if declared.family is not None and detected.family != declared.family:
        raise FrameworkError(
            f"{_source(dataset)}: the file has the layout of {detected},"
            f" which differs from that of {declared}"
        )
    return _reconcile(declared, detected)


def _reconcile(declared: Framework, detected: Framework) -> tuple[Framework, list[str]]:
    """Combine what the caller names and what the file states."""
    remarks = _remarks(detected)
    if declared.version is None or detected.version is None:
        version = declared.version or detected.version
    else:
        version = detected.version
        if not _agrees(declared.version, detected.version):
            remarks.append(
                f"the file states {detected}; it is read as such, although {declared} was named"
            )
    return Framework(detected.name, version, detected.family, detected.supported), remarks


def _remarks(detected: Framework) -> list[str]:
    if detected.supported or detected.family is None:
        return []
    remark = (
        f"the file states {detected}, a version Coati does not know;"
        f" it is read like {detected.title} {detected.family.versions}"
    )
    return [remark]


def _agrees(named: str, stated: str) -> bool:
    """Tell whether the version a caller names is the one a file states, or a part of it.

    `0.7` agrees with `0.7.0`, because it names the series and leaves the
    rest open; `0.7.0` does not agree with `0.7.0.dev7`.
    """
    if named == stated:
        return True
    try:
        chosen, suffix = _split_version(named, named)
        found, _ = _split_version(stated, stated)
    except FrameworkError:
        return False
    return not suffix and len(chosen) < len(found) and found[: len(chosen)] == chosen


def _source(dataset: Group) -> str:
    return str(dataset.source) if isinstance(dataset, Dataset) else dataset.path
