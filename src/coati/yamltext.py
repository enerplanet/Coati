"""Reading single values from the YAML documents that Calliope embeds in its files.

Calliope stores its configuration and the record of a run as YAML text in
attributes. The results document needs a handful of scalar values from them:
the version, the termination condition, the name of the model and the solver.
`scalar` finds such a value by the path of its keys. It understands the
block style in which Calliope writes these documents and nothing more, which is
why Coati needs no YAML parser to convert a file. To read a whole document, use
a YAML parser; `coati dump --decode-text` does.
"""

from __future__ import annotations

__all__ = ["exists", "scalar"]

_NULLS = frozenset({"", "~", "null", "Null", "NULL"})


def scalar(text: object, *keys: str) -> str | None:
    """Return the scalar at the path `keys` of the YAML mapping `text`.

    Args:
        text: A YAML document whose top level is a mapping in block style.
        keys: The key at each level, from the top.

    Returns:
        The value as text, without quotes and with a value that continues on
        further lines joined by spaces; `None` if the path does not exist, if
        it leads to a mapping or a list, or if the value is null.
    """
    if not isinstance(text, str) or not keys:
        return None
    lines = [line for line in text.splitlines() if _is_content(line)]
    start, stop, indent = 0, len(lines), 0
    value = ""
    for key in keys:
        found = _find(lines, start, stop, indent, key)
        if found is None:
            return None
        position, value = found
        start = position + 1
        stop = _end_of_block(lines, start, stop, indent)
        indent = _indentation(lines[start]) if start < stop else indent + 1
    return _resolve(value, [line.strip() for line in lines[start:stop]])


def exists(text: object, *keys: str) -> bool:
    """Tell whether the YAML mapping `text` has the path `keys`, whatever it leads to."""
    if not isinstance(text, str) or not keys:
        return False
    lines = [line for line in text.splitlines() if _is_content(line)]
    start, stop, indent = 0, len(lines), 0
    for key in keys:
        found = _find(lines, start, stop, indent, key)
        if found is None:
            return False
        start = found[0] + 1
        stop = _end_of_block(lines, start, stop, indent)
        indent = _indentation(lines[start]) if start < stop else indent + 1
    return True


def _is_content(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#") and stripped != "---"


def _indentation(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _find(lines: list[str], start: int, stop: int, indent: int, key: str) -> tuple[int, str] | None:
    """Find the line that defines `key` at the indentation `indent`.

    Returns:
        The index of the line and the text after the colon, or `None`.
    """
    for position in range(start, stop):
        line = lines[position]
        if _indentation(line) != indent:
            continue
        stripped = line.strip()
        for candidate in (key, f"'{key}'", f'"{key}"'):
            rest = stripped[len(candidate) :]
            if stripped.startswith(candidate) and (rest == ":" or rest.startswith(": ")):
                return position, rest[1:].strip()
    return None


def _end_of_block(lines: list[str], start: int, stop: int, indent: int) -> int:
    """Return the index of the first line after `start` that leaves the block."""
    for position in range(start, stop):
        if _indentation(lines[position]) <= indent:
            return position
    return stop


def _resolve(value: str, continuation: list[str]) -> str | None:
    """Return the scalar that starts with `value` and may go on in `continuation`."""
    if value[:1] in ("'", '"'):
        return _quoted(value, continuation)
    if not value:
        if not continuation or _is_structure(continuation[0]):
            return None
        value = continuation[0]
        continuation = continuation[1:]
    elif value[:1] in "{[|>&*!":
        return None
    for line in continuation:
        if _is_structure(line):
            break
        value += " " + line
    comment = value.find(" #")
    if comment >= 0:
        value = value[:comment].rstrip()
    return None if value in _NULLS else value


def _is_structure(line: str) -> bool:
    """Tell whether `line` starts a mapping entry or an item of a list."""
    return line == "-" or line.startswith("- ") or line.endswith(":") or ": " in line


def _quoted(value: str, continuation: list[str]) -> str | None:
    quote = value[0]
    for line in continuation:
        if _is_closed(value, quote):
            break
        value += " " + line
    if not _is_closed(value, quote):
        return None
    inner = value[1:-1]
    return inner.replace("''", "'") if quote == "'" else inner


def _is_closed(value: str, quote: str) -> bool:
    body = value[1:]
    if quote == "'":  # a quote is written twice within the text: the last of an odd run closes
        return (len(body) - len(body.rstrip("'"))) % 2 == 1
    return body.endswith('"') and not body.endswith('\\"')
