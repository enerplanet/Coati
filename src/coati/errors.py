"""The errors Coati raises.

Every error raised on purpose derives from `CoatiError`, so a caller can
catch one class. The subclasses say which part of a conversion failed:

* `SourceError`: the source file is missing, unreadable, damaged or in a
  format Coati does not read.
* `FrameworkError`: a framework identifier is unknown, or the file does
  not have the layout of the framework that was named.
* `ExtractionError`: the file has the layout of the framework but lacks
  content the results document needs.
* `EncodingError`: a value cannot be written as JSON under the chosen
  options.
"""

from __future__ import annotations

__all__ = [
    "CoatiError",
    "EncodingError",
    "ExtractionError",
    "FrameworkError",
    "SourceError",
]


class CoatiError(Exception):
    """Base class of every error Coati raises on purpose."""


class SourceError(CoatiError):
    """The source cannot be read: missing, damaged or in an unsupported format."""


class FrameworkError(CoatiError):
    """A framework identifier is unknown or does not match the file."""


class ExtractionError(CoatiError):
    """The file lacks content that the results document requires."""


class EncodingError(CoatiError):
    """A value cannot be written as JSON under the chosen options."""
