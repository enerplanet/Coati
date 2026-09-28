# JSON

Coati writes JSON as [RFC 8259](https://www.rfc-editor.org/rfc/rfc8259)
defines it, in UTF-8 and with a newline at the end. Any parser reads it.
This holds for a file and for the standard output, and on every platform:
on Windows, too, a document that is redirected into a file is UTF-8 and its
lines end with a line feed.

## Numbers that are not finite

JSON has no `NaN` and no infinity. The encoder of Python writes them
nevertheless, as `NaN` and `Infinity`, and most parsers refuse the
document. Result files are full of both: `NaN` is what a framework writes
for a technology that is not installed, and an infinite `p_nom_max` is a
capacity without a limit.

Every number passes a policy before it is written:

| `--non-finite` | `NaN` | infinity | |
|---|---|---|---|
| `null` | `null` | `null` | the default; a reader cannot tell the two apart |
| `string` | `"NaN"` | `"Infinity"`, `"-Infinity"` | keeps the distinction; a reader has to expect text in the place of a number |
| `error` | | | the document is refused, and the message names the place of the number |

```console
$ coati network.nc results.json --non-finite error
coati: $.capacities["north::pv"]: Infinity is not a JSON number (choose the
non-finite policy 'null' or 'string' to write it)
```

A value that is missing in a file, because it equals the fill value of its
variable, is `null` under every policy.

## Precision

A number is written with the digits that are needed to read it back
unchanged: `0.1` is written as `0.1`, and a number that was stored in single
precision with the digits of single precision, `0.3` and not
`0.30000001192092896`.

`--decimals N` rounds to `N` decimal places, which makes a document smaller
and its numbers easier to read:

```console
$ coati results.nc results.json --decimals 3
```

Rounding turns negative zero into zero. A number so large that it has no
digits at the places in question is written as it is. Whole numbers stay
whole: an integer of the file is an integer of the document.

## Layout

A document is indented by two spaces unless `--indent` says otherwise. An
array of numbers is written on one line even so, which keeps a time series
readable and the file small:

```json
{
  "dispatch": {
    "pv": [0.0, 0.0, 77.65, 136.35],
    "gas": [30.19, 30.19, 0.19, 0.0]
  }
}
```

`--compact` writes the document without any whitespace, for a program to
read. `--sort-keys` writes the keys of every object in sorted order, which
makes two documents comparable line by line; without it the keys have the
order of the document, which is that of its description.

## Text

Text is written as it is, in UTF-8: `"größe"`. `--ascii` escapes every
character outside ASCII, `"größe"`, for a reader that cannot be
trusted with UTF-8.

## Times

An instant is written as ISO 8601 text without a zone, with seconds and, if
it has any, fractions of a second: `2025-01-01T00:00:00`. A time that is
missing is `null`.

## Other values

| Value of the file | In the document |
|---|---|
| a truth value | `true` or `false` |
| bytes that are no text | text in Base64 |
| a complex number | a pair of its real and its imaginary part |
| a record of a compound type | an object with the fields of the type |
| a value of an enumerated type | its number; the variable lists the names under `enumeration` |

## Files

A file is written next to its place, under a name of its own, and moved to
its place once the document is complete. A conversion that fails leaves an
existing file as it was; a program that watches for the file never reads
half a document. A file that is replaced keeps its permissions.

## Size

A document is larger than its file: text takes more space than numbers in
binary form, and a file may be compressed. As a rule of thumb, a number
takes 5 to 20 bytes in a document, depending on its digits. `--compact` and
`--decimals` reduce the size; a document that is compressed with gzip or
zstd afterwards takes about as much space as the file.
