"""Coati converts result files of energy system models to JSON.

It reads the netCDF and HDF5 files that Calliope, PyPSA and AdOpT-NET0 write
and produces two kinds of document:

* the **results document**, which says what a solved model says, in the same
  terms for every framework: capacities, generation, dispatch, costs;
* the **dataset document**, which holds everything that is in a file, whatever
  wrote it.

Convert a file:

```python
import coati

coati.convert("results.nc", "results.json", framework="calliope-v0-7-0")
```

or work with the document:

```python
document = coati.results_document("network.nc", framework="pypsa-v1-2-4")
document["capacities"]["north::pv"]
```

The frameworks themselves are not needed, and neither is xarray: Coati reads
the files with h5py and NumPy. The same functions are available on the command
line as `coati`.
"""

import logging

from coati._version import __version__
from coati.api import (
    convert,
    dataset_document,
    detect,
    dump,
    find_source,
    inspect,
    read_results,
    results_document,
)
from coati.dataset import DumpOptions
from coati.errors import (
    CoatiError,
    EncodingError,
    ExtractionError,
    FrameworkError,
    SourceError,
)
from coati.frameworks import FAMILIES, Family, Framework
from coati.jsonio import JsonOptions
from coati.model import Dataset, Dimension, Group, Variable
from coati.readers import open_dataset
from coati.results import ExtractOptions, Results, Transmission

# A library does not decide where messages go: without a handler of the application,
# the warnings about a file are dropped instead of written to the standard error.
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "FAMILIES",
    "CoatiError",
    "Dataset",
    "Dimension",
    "DumpOptions",
    "EncodingError",
    "ExtractOptions",
    "ExtractionError",
    "Family",
    "Framework",
    "FrameworkError",
    "Group",
    "JsonOptions",
    "Results",
    "SourceError",
    "Transmission",
    "Variable",
    "__version__",
    "convert",
    "dataset_document",
    "detect",
    "dump",
    "find_source",
    "inspect",
    "open_dataset",
    "read_results",
    "results_document",
]
