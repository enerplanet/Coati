"""Coati converts result files of energy system models to JSON.

It reads the netCDF and HDF5 files that Calliope, PyPSA and AdOpT-NET0 write.
The frameworks themselves are not needed, and neither is xarray: Coati reads
the files with h5py and NumPy.
"""

import logging

from coati._version import __version__
from coati.errors import (
    CoatiError,
    EncodingError,
    ExtractionError,
    FrameworkError,
    SourceError,
)

# A library does not decide where messages go: without a handler of the application,
# the warnings about a file are dropped instead of written to the standard error.
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "CoatiError",
    "EncodingError",
    "ExtractionError",
    "FrameworkError",
    "SourceError",
    "__version__",
]
