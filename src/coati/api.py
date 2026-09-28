"""What Coati does, as functions.

The functions come in pairs. One of each pair returns a document as a
dictionary, the other writes it to a file as JSON:

| Returns | Writes | Document |
|---|---|---|
| `results_document` | `convert` | what a solved model says |
| `dataset_document` | `dump` | everything a file holds |

`inspect` summarises a file without reading the values of its variables,
and `detect` tells which framework wrote it.

A source is the path of a file. It may also be a directory that holds exactly
one data file, at any depth; AdOpT-NET0 writes its results into a folder whose
name it makes up from the time of the run, so the caller knows the folder
above but not the file.
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
from typing import IO, Any, Final

from coati import frameworks
from coati.dataset import DumpOptions, build_document
from coati.errors import SourceError
from coati.frameworks import AUTO, Framework
from coati.jsonio import JsonOptions, write_file
from coati.jsonio import dump as write_stream
from coati.model import Dataset, Group
from coati.readers import open_dataset
from coati.results import ExtractOptions, Results, extract_results

__all__ = [
    "convert",
    "dataset_document",
    "detect",
    "dump",
    "find_source",
    "inspect",
    "read_results",
    "results_document",
]

_LOG: Final = logging.getLogger("coati")

# The extensions of the files that a directory is searched for.
_EXTENSIONS: Final = frozenset({".h5", ".hdf5", ".hdf", ".he5", ".nc", ".nc4", ".cdf", ".netcdf"})

# How many files a message lists at most.
_LISTED: Final = 8

_Source = str | os.PathLike[str]
_Output = str | os.PathLike[str] | IO[str]


def _write(document: dict[str, Any], output: _Output, options: JsonOptions | None) -> None:
    """Write a document to a file, replaced in one step, or to an open stream."""
    if isinstance(output, (str, os.PathLike)):
        write_file(document, output, options)
    else:
        write_stream(document, output, options)


def find_source(source: _Source) -> Path:
    """Return the file that `source` names.

    Args:
        source: The path of a file, or of a directory that holds exactly one
            data file at any depth.

    Raises:
        SourceError: The path does not exist, or the directory holds no data
            file or more than one.
    """
    path = Path(source)
    if not path.is_dir():
        return path
    found = sorted(
        candidate
        for candidate in path.rglob("*")
        if candidate.suffix.lower() in _EXTENSIONS and candidate.is_file()
    )
    if len(found) == 1:
        return found[0]
    if not found:
        raise SourceError(f"{path}: the directory holds no netCDF or HDF5 file")
    listed = "".join(f"\n  {candidate}" for candidate in found[:_LISTED])
    more = f"\n  ... and {len(found) - _LISTED} more" if len(found) > _LISTED else ""
    raise SourceError(
        f"{path}: the directory holds {len(found)} data files; name one of them:{listed}{more}"
    )


def detect(source: _Source) -> Framework | None:
    """Tell which framework wrote the file `source`.

    Returns:
        The framework with the version the file states, or `None` if the
        file has the layout of no framework that Coati knows.

    Raises:
        SourceError: The file cannot be read.
    """
    with open_dataset(find_source(source)) as opened:
        return frameworks.detect(opened)


def read_results(
    source: _Source, framework: str = AUTO, options: ExtractOptions | None = None
) -> Results:
    """Read what the solved model in the file `source` says.

    Args:
        source: The path of the file; see `find_source`.
        framework: The framework identifier, such as `calliope-v0-6-10`, or
            `auto` to rely on the file. See `coati.frameworks`.
        options: The choices of the caller; the defaults if omitted.

    Raises:
        SourceError: The file cannot be read.
        FrameworkError: The identifier is invalid or does not match the file.
        ExtractionError: The file lacks content that the results require.
    """
    with open_dataset(find_source(source)) as opened:
        return _read_results(opened, framework, options)


def _read_results(opened: Dataset, framework: str, options: ExtractOptions | None) -> Results:
    resolved, remarks = frameworks.resolve(framework, opened)
    found = extract_results(opened, resolved, options)
    found.warnings[:0] = remarks + opened.warnings
    for warning in found.warnings:
        _LOG.warning("%s: %s", opened.source, warning)
    return found


def _describe_source(opened: Dataset) -> dict[str, Any]:
    description: dict[str, Any] = {"name": opened.source.name, "format": opened.format}
    with contextlib.suppress(OSError):
        description["size"] = opened.source.stat().st_size
    return description


def results_document(
    source: _Source, framework: str = AUTO, options: ExtractOptions | None = None
) -> dict[str, Any]:
    """Return the results document of the file `source`.

    The document is a dictionary whose time series are NumPy arrays;
    `coati.jsonio.dumps` writes it as JSON. See `read_results` for
    the arguments and the errors.
    """
    with open_dataset(find_source(source)) as opened:
        return _read_results(opened, framework, options).to_document(_describe_source(opened))


def convert(
    source: _Source,
    output: _Output,
    framework: str = AUTO,
    options: ExtractOptions | None = None,
    json_options: JsonOptions | None = None,
) -> dict[str, Any]:
    """Write the results document of the file `source` to `output`.

    A file is replaced in one step: a conversion that fails leaves an existing
    file untouched.

    Args:
        source: The path of the file; see `find_source`.
        output: The path of the JSON file to write, or a stream that is open
            for writing text.
        framework: The framework identifier, or `auto`.
        options: The choices about the content; the defaults if omitted.
        json_options: The choices about the JSON text; the defaults if omitted.

    Returns:
        The document that has been written.

    Raises:
        SourceError: The file cannot be read.
        FrameworkError: The identifier is invalid or does not match the file.
        ExtractionError: The file lacks content that the results require.
        EncodingError: A value cannot be written as JSON.
        OSError: The output cannot be written.
    """
    document = results_document(source, framework, options)
    _write(document, output, json_options)
    return document


def dataset_document(source: _Source, options: DumpOptions | None = None) -> dict[str, Any]:
    """Return the dataset document of the file `source`.

    The document holds the values of every variable, so it needs the memory
    that the file needs when it is read as a whole; `dump` does not.

    Raises:
        SourceError: The file cannot be read.
    """
    with open_dataset(find_source(source)) as opened:
        document = build_document(opened, options, lazy=False)
        document["metadata"]["source"] = _describe_source(opened)
        return document


def dump(
    source: _Source,
    output: _Output,
    options: DumpOptions | None = None,
    json_options: JsonOptions | None = None,
) -> None:
    """Write the dataset document of the file `source` to `output`.

    The values of a variable are read when the variable is written, so the
    memory needed is that of the largest variable, not that of the file. The
    output is a path or a stream, as for `convert`.

    Raises:
        SourceError: The file cannot be read.
        EncodingError: A value cannot be written as JSON.
        OSError: The output cannot be written.
    """
    with open_dataset(find_source(source)) as opened:
        document = build_document(opened, options)
        document["metadata"]["source"] = _describe_source(opened)
        _write(document, output, json_options)


def inspect(source: _Source) -> dict[str, Any]:
    """Summarise the file `source` without reading the values of its variables.

    Returns:
        A dictionary with the format of the file, the framework that wrote
        it, if any is recognised, and the groups with their dimensions and
        variables.

    Raises:
        SourceError: The file cannot be read.
    """
    with open_dataset(find_source(source)) as opened:
        found = frameworks.detect(opened)
        summary: dict[str, Any] = {
            "source": _describe_source(opened),
            "framework": None,
            "groups": [_summarise(group) for group in opened.walk()],
            "warnings": list(opened.warnings),
        }
        if found is not None:
            summary["framework"] = {
                "id": found.id,
                "name": found.name,
                "title": found.title,
                "version": found.version,
                "family": found.family.id if found.family else None,
                "supported": found.supported,
            }
        return summary


def _summarise(group: Group) -> dict[str, Any]:
    return {
        "path": group.path,
        "attributes": list(group.attributes),
        "dimensions": {name: dimension.size for name, dimension in group.dimensions.items()},
        "variables": [
            {
                "name": variable.name,
                "dtype": variable.type_name,
                "dimensions": list(variable.dimensions),
                "shape": list(variable.shape),
            }
            for variable in group.variables.values()
        ],
    }
