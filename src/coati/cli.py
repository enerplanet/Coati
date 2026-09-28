"""The command `coati`.

```text
coati [convert] SOURCE OUTPUT [FRAMEWORK]   write the results of a model as JSON
coati dump SOURCE OUTPUT                    write everything a file holds as JSON
coati inspect SOURCE                        summarise a file
coati frameworks                            list what is supported
coati schema {results,dataset}              print the JSON Schema of a document
```

`convert` is what `coati` does if no command is named. `OUTPUT` may be
`-` for the standard output.

The exit status is 0 on success, 1 if the conversion fails and 2 if the command
line is wrong. Messages go to the standard error; on success there are none
unless the file gives rise to a warning. If the reader of the standard output
leaves before the document is complete, as `head` does, the command ends
without a message, with the status 141 that a program ended by a closed pipe
has.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import sys
from collections.abc import Sequence
from importlib import resources
from typing import IO, Any, Final, NoReturn

from coati import api, frameworks, jsonio
from coati._version import __version__
from coati.dataset import DumpOptions
from coati.errors import CoatiError
from coati.jsonio import NON_FINITE_POLICIES, JsonOptions
from coati.results import ExtractOptions

__all__ = ["main"]

_PROGRAM: Final = "coati"
_COMMANDS: Final = ("convert", "dump", "inspect", "frameworks", "schema")
_STDOUT: Final = "-"
_INDENT: Final = 2
_SCHEMAS: Final = {"results": "results.schema.json", "dataset": "dataset.schema.json"}
_FORMATS: Final = {
    "netcdf4": "netCDF-4",
    "hdf5": "HDF5",
    "netcdf3-classic": "netCDF classic (CDF-1)",
    "netcdf3-64bit-offset": "netCDF 64-bit offset (CDF-2)",
    "netcdf3-64bit-data": "netCDF 64-bit data (CDF-5)",
}

EXIT_OK: Final = 0
EXIT_FAILURE: Final = 1
EXIT_USAGE: Final = 2
_EXIT_INTERRUPTED: Final = 130
_EXIT_PIPE: Final = 141


class _UsageError(Exception):
    """The arguments of the command line contradict each other."""


class _Warnings(logging.Handler):
    """Writes the warnings of the library to the standard error."""

    def emit(self, record: logging.LogRecord) -> None:
        with contextlib.suppress(Exception):
            sys.stderr.write(f"{_PROGRAM}: warning: {record.getMessage()}\n")


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the command and return its exit status.

    Args:
        arguments: The arguments of the command line, without the name of the
            program; those of the process if omitted.
    """
    given = list(sys.argv[1:] if arguments is None else arguments)
    try:
        options = _parse(given)
    except SystemExit as stop:
        return stop.code if isinstance(stop.code, int) else EXIT_USAGE
    handler = _Warnings()
    logger = logging.getLogger(_PROGRAM)
    logger.addHandler(handler)
    logger.setLevel(logging.ERROR if getattr(options, "quiet", False) else logging.WARNING)
    try:
        options.run(options)
    except _UsageError as error:
        options.parser.print_usage(sys.stderr)
        sys.stderr.write(f"{options.parser.prog}: {error}\n")
        return EXIT_USAGE
    except BrokenPipeError:
        _discard_stdout()
        return _EXIT_PIPE
    except (CoatiError, OSError) as error:
        sys.stderr.write(f"{_PROGRAM}: {_message(error)}\n")
        return EXIT_FAILURE
    except KeyboardInterrupt:
        return _EXIT_INTERRUPTED
    finally:
        logger.removeHandler(handler)
    return EXIT_OK


def _message(error: BaseException) -> str:
    if isinstance(error, OSError) and error.filename is not None:
        return f"{error.filename}: {error.strerror or error}"
    return str(error)


def _parse(arguments: list[str]) -> argparse.Namespace:
    """Read the command line; options and arguments may come in any order."""
    parser, commands = _parsers()
    given = _with_default_command(arguments)
    if given and given[0] in commands:
        return commands[given[0]].parse_intermixed_args(given[1:])
    return parser.parse_args(given)


def _with_default_command(arguments: list[str]) -> list[str]:
    """Put `convert` before arguments that name no command."""
    for argument in arguments:
        if argument in ("-h", "--help", "-V", "--version"):
            return arguments
        if not argument.startswith("-") or argument == _STDOUT:
            return arguments if argument in _COMMANDS else ["convert", *arguments]
    return arguments


# -- the command line -----------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: {message}\n")


def _parsers() -> tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser]]:
    """The parser of the command line and the parsers of its commands."""
    parser = _Parser(
        prog=_PROGRAM,
        description="Convert netCDF and HDF5 result files of Calliope, PyPSA and AdOpT-NET0"
        " to JSON.",
        epilog="Without a command, coati converts: coati SOURCE OUTPUT [FRAMEWORK].",
    )
    parser.add_argument("-V", "--version", action="version", version=f"{_PROGRAM} {__version__}")
    commands = parser.add_subparsers(title="commands", metavar="COMMAND", parser_class=_Parser)
    commands.required = True
    _add_convert(commands)
    _add_dump(commands)
    _add_inspect(commands)
    _add_frameworks(commands)
    _add_schema(commands)
    return parser, dict(commands.choices)


def _add_json_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("JSON")
    layout = group.add_mutually_exclusive_group()
    layout.add_argument(
        "--indent",
        type=_count,
        metavar="N",
        help=f"spaces per nesting level (default: {_INDENT})",
    )
    layout.add_argument(
        "--compact", action="store_true", help="write the JSON without any whitespace"
    )
    group.add_argument(
        "--decimals",
        type=_count,
        metavar="N",
        help="round numbers to N decimal places (default: write them in full)",
    )
    group.add_argument(
        "--non-finite",
        choices=NON_FINITE_POLICIES,
        default="null",
        help="what becomes of NaN and the infinities, which JSON does not have: null,"
        " the strings NaN, Infinity and -Infinity, or an error (default: null)",
    )
    group.add_argument("--sort-keys", action="store_true", help="write the keys in sorted order")
    group.add_argument("--ascii", action="store_true", help="escape every character outside ASCII")
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="do not write warnings to the standard error"
    )


def _count(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = -1
    if value < 0:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number of zero or more")
    return value


def _json_options(options: argparse.Namespace) -> JsonOptions:
    indent = _INDENT if options.indent is None else options.indent
    return JsonOptions(
        indent=None if options.compact else indent,
        non_finite=options.non_finite,
        decimals=options.decimals,
        sort_keys=options.sort_keys,
        ensure_ascii=options.ascii,
    )


def _add_convert(commands: Any) -> None:
    parser = commands.add_parser(
        "convert",
        help="write the results of a model as JSON (the default)",
        description="Write what a solved model says as JSON: capacities, generation, dispatch,"
        " costs and more, in the same terms for every framework.",
    )
    parser.add_argument(
        "source",
        metavar="SOURCE",
        help="the file of the model, or a directory that holds exactly one such file",
    )
    parser.add_argument("output", metavar="OUTPUT", help="the JSON file to write, or - for stdout")
    parser.add_argument(
        "framework_argument",
        metavar="FRAMEWORK",
        nargs="?",
        help="the framework and version that wrote the file, such as calliope-v0-6-10,"
        " pypsa-v1-2-4 or adopt-net0-v0-1-10; see 'coati frameworks'"
        " (default: auto, which takes both from the file)",
    )
    parser.add_argument(
        "-f",
        "--framework",
        metavar="FRAMEWORK",
        help="the same as the argument FRAMEWORK",
    )
    content = parser.add_argument_group("content")
    content.add_argument(
        "--no-labels",
        action="store_true",
        help="leave out the display names and colours of the technologies",
    )
    content.add_argument(
        "--period",
        metavar="NAME",
        help="the investment period to report, for a file of AdOpT-NET0 with several"
        " (default: the first)",
    )
    content.add_argument(
        "--time-start",
        metavar="TIME",
        help="the first time of a model whose file records no times, such as"
        " 2025-01-01T00:00; needs --time-step",
    )
    content.add_argument(
        "--time-step",
        metavar="DURATION",
        help="the distance between two times, such as 1h or 15min; needs --time-start",
    )
    _add_json_options(parser)
    parser.set_defaults(run=_convert, parser=parser)


def _framework(options: argparse.Namespace) -> str:
    positional, named = options.framework_argument, options.framework
    if positional is not None and named is not None and positional != named:
        raise _UsageError(
            f"the framework is given twice: as {positional!r} and as --framework {named!r}"
        )
    return positional or named or frameworks.AUTO


def _convert(options: argparse.Namespace) -> None:
    if (options.time_start is None) != (options.time_step is None):
        raise _UsageError("--time-start and --time-step must be given together")
    content = ExtractOptions(
        labels=not options.no_labels,
        period=options.period,
        time_start=options.time_start,
        time_step=options.time_step,
    )
    with _output(options.output) as output:
        api.convert(options.source, output, _framework(options), content, _json_options(options))


def _add_dump(commands: Any) -> None:
    parser = commands.add_parser(
        "dump",
        help="write everything a file holds as JSON",
        description="Write every group, dimension, variable and attribute of a netCDF or HDF5"
        " file as JSON, whatever wrote the file.",
    )
    parser.add_argument("source", metavar="SOURCE", help="the file, or a directory that holds one")
    parser.add_argument("output", metavar="OUTPUT", help="the JSON file to write, or - for stdout")
    content = parser.add_argument_group("content")
    content.add_argument(
        "--no-data",
        action="store_true",
        help="describe the variables without their values",
    )
    content.add_argument(
        "--raw",
        action="store_true",
        help="write the values as stored: do not interpret times, missing values and the"
        " like according to the CF conventions",
    )
    content.add_argument(
        "--decode-text",
        action="store_true",
        help="write an attribute that holds a JSON or YAML document as that document"
        " (YAML needs PyYAML)",
    )
    content.add_argument(
        "--max-elements",
        type=_count,
        metavar="N",
        help="leave out the values of a variable with more than N elements",
    )
    content.add_argument(
        "--variable",
        action="append",
        default=[],
        metavar="PATTERN",
        help="write only the variables whose path or name matches the pattern, such as"
        " '/results/flow_*'; may be given several times",
    )
    _add_json_options(parser)
    parser.set_defaults(run=_dump, parser=parser)


def _dump(options: argparse.Namespace) -> None:
    content = DumpOptions(
        data=not options.no_data,
        decode=not options.raw,
        decode_text=options.decode_text,
        max_elements=options.max_elements,
        variables=tuple(options.variable),
    )
    with _output(options.output) as output:
        api.dump(options.source, output, content, _json_options(options))


class _output:  # noqa: N801 - used as a function
    """The output of a command: the path of a file, or the standard output for `-`."""

    def __init__(self, name: str) -> None:
        self._name = name

    def __enter__(self) -> str | IO[str]:
        return _stdout() if self._name == _STDOUT else self._name

    def __exit__(self, *error: object) -> None:
        if self._name == _STDOUT and error[0] is None:
            _flush_stdout()


def _stdout() -> IO[str]:
    """Return the standard output, set to write UTF-8 and lines that end alike.

    JSON is UTF-8, whatever the platform prefers for its streams. On Windows
    that is the code page of the system: a document that is redirected into a
    file would be no JSON, and one with a character that the code page lacks
    could not be written at all.
    """
    stream = sys.stdout
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        with contextlib.suppress(OSError, ValueError, LookupError):
            reconfigure(encoding="utf-8", newline="\n")
    return stream


def _flush_stdout() -> None:
    """Hand what has been written to the reader of the standard output."""
    sys.stdout.flush()


def _discard_stdout() -> None:
    """Let go of the standard output, whose reader has left.

    Python writes what is left of the output when it ends, and would report
    that the reader has left a second time.
    """
    with contextlib.suppress(OSError, ValueError):
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())


def _add_inspect(commands: Any) -> None:
    parser = commands.add_parser(
        "inspect",
        help="summarise a file",
        description="Show the format of a file, the framework that wrote it and its groups,"
        " dimensions and variables, without reading the values.",
    )
    parser.add_argument("source", metavar="SOURCE", help="the file, or a directory that holds one")
    parser.add_argument("--json", action="store_true", help="write the summary as JSON")
    parser.set_defaults(run=_inspect, parser=parser)


def _inspect(options: argparse.Namespace) -> None:
    summary = api.inspect(options.source)
    if options.json:
        jsonio.dump(summary, _stdout())
    else:
        _stdout().write(_render_summary(summary))
    _flush_stdout()


def _render_summary(summary: dict[str, Any]) -> str:
    source = summary["source"]
    lines = [f"file:      {source['name']}"]
    lines.append(f"format:    {_FORMATS.get(source['format'], source['format'])}")
    if "size" in source:
        lines.append(f"size:      {_size(source['size'])}")
    found = summary["framework"]
    if found is None:
        lines.append("framework: not recognised")
    else:
        version = found["version"] or "version not recorded"
        lines.append(f"framework: {found['title']} {version} ({found['id']})")
    for group in summary["groups"]:
        lines.extend(_render_group(group))
    for warning in summary["warnings"]:
        lines.append(f"warning: {warning}")
    return "\n".join(lines) + "\n"


def _render_group(group: dict[str, Any]) -> list[str]:
    lines = ["", f"group {group['path']}"]
    if group["attributes"]:
        lines.append(f"  attributes: {', '.join(group['attributes'])}")
    if group["dimensions"]:
        sizes = ", ".join(f"{name} ({size})" for name, size in group["dimensions"].items())
        lines.append(f"  dimensions: {sizes}")
    variables = group["variables"]
    if variables:
        lines.append("  variables:")
        width = max(len(variable["name"]) for variable in variables)
        kinds = max(len(variable["dtype"]) for variable in variables)
        for variable in variables:
            axes = ", ".join(
                f"{name or '?'}: {size}"
                for name, size in zip(variable["dimensions"], variable["shape"], strict=True)
            )
            lines.append(
                f"    {variable['name']:<{width}}  {variable['dtype']:<{kinds}}  ({axes})".rstrip()
            )
    return lines


def _size(size: int) -> str:
    amount = float(size)
    for unit in ("B", "kB", "MB", "GB"):
        if amount < 1000 or unit == "GB":
            return f"{int(amount)} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1000
    raise AssertionError("unreachable")


def _add_frameworks(commands: Any) -> None:
    parser = commands.add_parser(
        "frameworks",
        help="list the frameworks and versions that are supported",
        description="List the families of versions that coati reads. A framework identifier"
        " names a family or a version of it: calliope-v0-7 and calliope-v0-7-0 are both valid.",
    )
    parser.add_argument("--json", action="store_true", help="write the list as JSON")
    parser.set_defaults(run=_frameworks, parser=parser)


def _frameworks(options: argparse.Namespace) -> None:
    listed = [
        {
            "id": family.id,
            "framework": family.framework,
            "title": family.title,
            "versions": family.versions,
            "tested": list(family.tested),
            "formats": list(family.formats),
            "layout": family.layout,
        }
        for family in frameworks.FAMILIES
    ]
    if options.json:
        jsonio.dump(listed, _stdout())
    else:
        _stdout().write(_render_frameworks(listed))
    _flush_stdout()


def _render_frameworks(listed: list[dict[str, Any]]) -> str:
    header = ("IDENTIFIER", "FRAMEWORK", "VERSIONS", "TESTED WITH", "FORMATS")
    rows = [
        (
            entry["id"],
            entry["title"],
            entry["versions"],
            ", ".join(entry["tested"]),
            ", ".join(_FORMATS.get(name, name) for name in entry["formats"]),
        )
        for entry in listed
    ]
    widths = [max(len(row[column]) for row in (header, *rows)) for column in range(len(header))]
    lines = [
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in (header, *rows)
    ]
    return "\n".join(lines) + "\n"


def _add_schema(commands: Any) -> None:
    parser = commands.add_parser(
        "schema",
        help="print the JSON Schema of a document",
        description="Print the JSON Schema of the results document or of the dataset document.",
    )
    parser.add_argument("document", choices=sorted(_SCHEMAS), help="the document")
    parser.set_defaults(run=_schema, parser=parser)


def _schema(options: argparse.Namespace) -> None:
    schema = resources.files("coati.schemas").joinpath(_SCHEMAS[options.document])
    _stdout().write(schema.read_text(encoding="utf-8"))
    _flush_stdout()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
