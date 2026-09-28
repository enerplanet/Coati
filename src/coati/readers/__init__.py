"""Readers: one per file format, all producing a `coati.model.Dataset`.

`open_dataset` looks at the first bytes of a file to choose the reader, so
the name of a file and its extension do not matter.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

import h5py

from coati.errors import SourceError
from coati.model import Dataset
from coati.readers.classic import open_classic
from coati.readers.hdf5 import open_hdf5

__all__ = ["open_dataset", "sniff"]

_HDF5_SIGNATURE: Final = b"\x89HDF\r\n\x1a\n"

# What a file that is not a data file may be instead, by its first bytes.
_OTHER_FORMATS: Final = (
    (b"\x1f\x8b", "it is compressed with gzip; decompress it first"),
    (b"PK\x03\x04", "it is a ZIP archive; extract it first"),
    (b"BZh", "it is compressed with bzip2; decompress it first"),
    (b"\xfd7zXZ\x00", "it is compressed with xz; decompress it first"),
    (b"\x28\xb5\x2f\xfd", "it is compressed with zstd; decompress it first"),
    (b"{", "it looks like JSON"),
    (b"[", "it looks like JSON"),
)


def open_dataset(source: str | os.PathLike[str]) -> Dataset:
    """Open a netCDF or HDF5 file and read its structure.

    The dataset keeps the file open until it is closed; use it as a context
    manager:

    ```python
    with open_dataset("results.nc") as dataset:
        print(dataset.format, list(dataset.variables))
    ```

    Args:
        source: The path of the file.

    Raises:
        SourceError: The file is missing, unreadable, damaged or neither a
            netCDF nor an HDF5 file.
    """
    path = Path(source)
    return open_hdf5(path) if sniff(path) == "hdf5" else open_classic(path)


def sniff(path: Path) -> str:
    """Return the family of formats `path` belongs to: `hdf5` or `netcdf3`.

    Raises:
        SourceError: The file cannot be read or is of neither family.
    """
    head = _head(path)
    if head[:3] == b"CDF" and head[3:4] in (b"\x01", b"\x02", b"\x05"):
        return "netcdf3"
    if head == _HDF5_SIGNATURE or _is_hdf5(path):
        return "hdf5"
    if not head:
        raise SourceError(f"{path}: the file is empty")
    for signature, explanation in _OTHER_FORMATS:
        if head.startswith(signature):
            raise SourceError(f"{path}: not a netCDF or HDF5 file; {explanation}")
    raise SourceError(f"{path}: not a netCDF or HDF5 file")


def _head(path: Path) -> bytes:
    try:
        with path.open("rb") as stream:
            return stream.read(len(_HDF5_SIGNATURE))
    except FileNotFoundError:
        raise SourceError(f"{path}: no such file") from None
    except IsADirectoryError:
        raise SourceError(f"{path}: is a directory, not a file") from None
    except OSError as error:
        raise SourceError(f"{path}: cannot be read: {error.strerror or error}") from error


def _is_hdf5(path: Path) -> bool:
    """Recognise an HDF5 file whose signature follows a user block."""
    try:
        return bool(h5py.is_hdf5(path))
    except OSError:
        return False
