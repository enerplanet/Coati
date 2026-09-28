"""Results documents: one extractor for each family of frameworks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from coati.errors import FrameworkError
from coati.frameworks import Framework
from coati.model import Dataset
from coati.results import adoptnet0, calliope06, calliope07, pypsa
from coati.results.document import SCHEMA_VERSION, Results, Transmission
from coati.results.options import ExtractOptions

__all__ = ["SCHEMA_VERSION", "ExtractOptions", "Results", "Transmission", "extract_results"]

_Extractor = Callable[[Dataset, Framework, ExtractOptions], Results]

_EXTRACTORS: Final[dict[str, _Extractor]] = {
    "adopt-net0-v0-1": adoptnet0.extract,
    "calliope-v0-6": calliope06.extract,
    "calliope-v0-7": calliope07.extract,
    "pypsa-v0": pypsa.extract,
    "pypsa-v1": pypsa.extract,
}


def extract_results(
    dataset: Dataset, framework: Framework, options: ExtractOptions | None = None
) -> Results:
    """Make the results of `dataset`, read as a file of `framework`.

    Args:
        dataset: The open file.
        framework: The framework with its family, as
            `coati.frameworks.resolve` returns it.
        options: The choices of the caller; the defaults if omitted.

    Raises:
        FrameworkError: The framework has no family.
        ExtractionError: The file lacks content that the results require.
    """
    if framework.family is None:
        raise FrameworkError(f"{framework}: the version is needed to read the file")
    extractor = _EXTRACTORS[framework.family.id]
    return extractor(dataset, framework, options or ExtractOptions())
