"""Results documents: one extractor for each family of frameworks.

The extractors register here by the identifier of their family.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from coati.errors import FrameworkError
from coati.frameworks import Framework
from coati.model import Dataset
from coati.results.document import SCHEMA_VERSION, Results, Transmission
from coati.results.options import ExtractOptions

__all__ = ["SCHEMA_VERSION", "ExtractOptions", "Results", "Transmission", "extract_results"]

_Extractor = Callable[[Dataset, Framework, ExtractOptions], Results]

_EXTRACTORS: Final[dict[str, _Extractor]] = {}


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
