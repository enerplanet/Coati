# Dataset document

Where the results document answers what a model says, the dataset document
answers what is in the file: every group, dimension, variable and
attribute, with the values. It needs no knowledge of a framework and reads
any netCDF or HDF5 file.

```console
$ coati dump results.nc dataset.json
```

The document has the schema version `1.0`; `coati schema dataset` prints its
JSON Schema.

## Layout

The layout follows the data model of netCDF. A file is a group; a group has
attributes, dimensions, variables and further groups:

```json
{
  "schema_version": "1.0",
  "format": "netcdf4",
  "attributes": {},
  "dimensions": {},
  "variables": {},
  "groups": {
    "results": {
      "attributes": {},
      "dimensions": {
        "nodes": {"size": 2, "unlimited": false},
        "techs": {"size": 7, "unlimited": false},
        "carriers": {"size": 2, "unlimited": false}
      },
      "variables": {
        "flow_cap": {
          "dtype": "float64",
          "dimensions": ["nodes", "techs", "carriers"],
          "shape": [2, 7, 2],
          "attributes": {},
          "encoding": {"_FillValue": null},
          "data": [[[null, null], [null, 136.4]], [[null, 100.0], [10.0, 11.1]]]
        }
      },
      "groups": {}
    }
  },
  "warnings": [],
  "metadata": {}
}
```

The example is shortened.

| Key | Meaning |
|---|---|
| `format` | the format of the file: `netcdf4`, `hdf5`, `netcdf3-classic`, `netcdf3-64bit-offset` or `netcdf3-64bit-data` |
| `attributes` | the attributes of the group, by name |
| `dimensions` | the dimensions that the group defines, each with its `size` and whether it is `unlimited` |
| `variables` | the variables of the group, by name |
| `groups` | the groups within the group, by name |
| `warnings` | what the reader could not represent, such as a link into another file |
| `metadata` | how the document was made, and what the file says about the software that wrote it |

A variable has these keys:

| Key | Meaning |
|---|---|
| `dtype` | the type of the values: that of NumPy for numbers, such as `float64`, or `string`, `char`, `bool`, `datetime`, `compound`, `opaque`, `reference`, `vlen<...>` |
| `dimensions` | the name of the dimension of each axis; null for an axis without one, which occurs in HDF5 files that are not netCDF |
| `shape` | the extent of each axis |
| `attributes` | the attributes that describe the variable |
| `encoding` | the attributes that the interpretation of the values has consumed, such as `units` and `_FillValue` |
| `enumeration` | for a variable of an enumerated type, the name of each value |
| `data` | the values: nested lists with one level for each axis, or a single value for a variable without axes |
| `data_omitted` | present and true if the values were left out because the variable has more elements than the limit |

## How the values are interpreted

A netCDF file stores numbers; attributes of the variable say what they
mean. Coati applies the conventions that the frameworks rely on, those of
[CF](https://cfconventions.org/) and of xarray, in this order:

1. **Characters.** An array of single characters is joined along its last
   axis into text, which is how the classic formats store text.
2. **Unsigned integers.** `_Unsigned = "true"` reinterprets signed integers.
3. **Missing values.** Elements that equal `_FillValue` or `missing_value`
   are missing and become `null`.
4. **Packed values.** `scale_factor` and `add_offset` unpack to double
   precision.
5. **Truth values.** Integers with the attribute `dtype = "bool"`, the
   convention of xarray, become `true` and `false`.
6. **Times.** Numbers with `units` of the form `hours since 2005-01-01` in
   the Gregorian calendar become instants, written as ISO 8601 text. A
   reference time with a zone offset is converted to UTC.

The attributes that a step consumes are reported as the `encoding` of the
variable, apart from its descriptive `attributes`, as xarray does. What
cannot be interpreted safely, such as times in a calendar without leap
years, is left as stored.

With `--raw`, the values and the attributes are those of the file:

=== "interpreted"

    ```json
    {
      "dtype": "datetime",
      "dimensions": ["timesteps"],
      "shape": [3],
      "attributes": {},
      "encoding": {"units": "hours since 2005-01-01 00:00:00", "calendar": "proleptic_gregorian"},
      "data": ["2005-01-01T00:00:00", "2005-01-01T01:00:00", "2005-01-01T02:00:00"]
    }
    ```

=== "`--raw`"

    ```json
    {
      "dtype": "int64",
      "dimensions": ["timesteps"],
      "shape": [3],
      "attributes": {"units": "hours since 2005-01-01 00:00:00", "calendar": "proleptic_gregorian"},
      "data": [0, 1, 2]
    }
    ```

## Attributes

An attribute is text, a number, a truth value, null or a list of these. An
attribute that holds one number is that number, not a list of one.

The bookkeeping of the formats is not part of the document: the attributes
with which netCDF-4 records its dimensions in an HDF5 file, such as
`DIMENSION_LIST` and `_Netcdf4Dimid`, say nothing that the document does not
say with `dimensions`.

Calliope stores its configuration as YAML in attributes, and PyPSA its
metadata as JSON. With `--decode-text`, an attribute that holds a JSON or
YAML document is reported as that document:

=== "as text"

    ```json
    {"config": "init:\n  name: Coati test model\n  mode: base\nsolve:\n  solver: cbc\n"}
    ```

=== "`--decode-text`"

    ```json
    {"config": {"init": {"name": "Coati test model", "mode": "base"}, "solve": {"solver": "cbc"}}}
    ```

YAML needs PyYAML: `pip install "enerplanet-coati[yaml]"`. A text that is no
document stays a text.

## Large files

The values of a variable are read when the variable is written, so that a
dump needs the memory of the largest variable and not that of the file.
Three options keep a document small:

| Option | Effect |
|---|---|
| `--no-data` | the document describes the structure of the file, without values |
| `--max-elements N` | the values of a variable with more than `N` elements are left out, and the variable says so with `data_omitted` |
| `--variable PATTERN` | only the variables that match are part of the document |

## Formats

| Format | Read with | Remarks |
|---|---|---|
| netCDF-4 | h5py | groups, dimensions that may grow, texts of any length, types that the user defines |
| HDF5 | h5py | a file that is no netCDF has no dimensions: the axes of its variables have no names |
| netCDF classic, CDF-1 | Coati itself | |
| netCDF 64-bit offset, CDF-2 | Coati itself | |
| netCDF 64-bit data, CDF-5 | Coati itself | unsigned integers and integers of 64 bits |

A file is recognised by its first bytes, not by its name. A file that is
compressed as a whole, with gzip or as a zip archive, is refused with a
message that says so; unpack it first.

### HDF5 files that are no netCDF

AdOpT-NET0 and the HDF5 export of PyPSA write HDF5 files that are no netCDF.
They have no dimensions. The document lists their datasets as variables
whose axes have no names:

```json
{
  "dtype": "float64",
  "dimensions": [null],
  "shape": [48],
  "attributes": {},
  "data": [0.0, 0.0]
}
```

### Links

A link of an HDF5 file into another file is not followed: the document
holds what the file holds. The link is named in a warning. A group that
contains itself is read once.

## What Coati does not read

- Values of the types `reference` and `opaque` are described; references
  are not followed.
- The classic formats are read as a whole into the address space of the
  process, which the operating system does without reading the file.
