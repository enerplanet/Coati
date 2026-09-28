# Command line

```text
coati [convert] SOURCE OUTPUT [FRAMEWORK]   write the results of a model as JSON
coati dump SOURCE OUTPUT                    write everything a file holds as JSON
coati inspect SOURCE                        summarise a file
coati frameworks                            list what is supported
coati schema {results,dataset}              print the JSON Schema of a document
```

`convert` is what `coati` does if no command is named: `coati a.nc a.json` and
`coati convert a.nc a.json` are the same. Options and arguments may come in
any order. `coati COMMAND --help` describes a command.

## Arguments

`SOURCE`
:   The file of the model. It may also be a directory that holds exactly one
    data file, at any depth. AdOpT-NET0 writes its results into a folder
    whose name it makes up from the time of the run; with a directory as the
    source, a pipeline can name the folder that it knows:

    ```console
    $ coati run/results results.json adopt-net0-v0-1-10
    ```

    A directory that holds several data files is refused, and the message
    lists them.

`OUTPUT`
:   The JSON file to write, or `-` for the standard output. A file is written
    next to its place and moved there once the document is complete: a
    conversion that fails leaves an existing file as it was, and a reader
    never sees half a document. The directory of the file must exist.

`FRAMEWORK`
:   The framework and version that wrote the file, such as
    `calliope-v0-6-10`, `pypsa-v1-2-4` or `adopt-net0-v0-1-10`. It may also
    be given as the option `-f` or `--framework`. Without it, or with `auto`,
    the framework and the version are taken from the file. See
    [Frameworks](../frameworks/overview.md).

## convert

```console
$ coati results.nc results.json calliope-v0-7-0
$ coati results.nc results.json --framework calliope-v0-7-0 --decimals 3
$ coati optimization_results.h5 results.json adopt-net0-v0-1-10 \
      --time-start 2025-01-01T00:00 --time-step 1h
```

Writes the [results document](../documents/results.md).

| Option | Meaning |
|---|---|
| `-f`, `--framework FRAMEWORK` | the same as the argument `FRAMEWORK` |
| `--no-labels` | leave out the display names and colours of the technologies |
| `--period NAME` | the investment period to report, for a file of AdOpT-NET0 with several; the first if omitted |
| `--time-start TIME` | the first time of a model whose file records no times, such as `2025-01-01T00:00`; needs `--time-step` |
| `--time-step DURATION` | the distance between two times, such as `1h`, `15min` or `1d`; needs `--time-start` |

`--no-labels`
:   A file of Calliope holds a name and a colour for each technology, which
    the document reports as `display_name` and `color`. A program that has
    names and colours of its own, and gives those of the document
    precedence, leaves them out with this option.

`--time-start`, `--time-step`
:   The files of AdOpT-NET0 record no times, nor do those of a PyPSA network
    whose snapshots are numbers. The `timestamps` of the document are then
    the positions `0, 1, 2, ...`. With a start and a step they are instants.
    The times that a file records have precedence.

## dump

```console
$ coati dump results.nc dataset.json
$ coati dump results.nc structure.json --no-data
$ coati dump results.nc flows.json --variable '/results/flow_*' --variable timesteps
$ coati dump results.nc attributes.json --no-data --decode-text
```

Writes the [dataset document](../documents/dataset.md). The file may be any
netCDF or HDF5 file; a framework is neither named nor needed.

| Option | Meaning |
|---|---|
| `--no-data` | describe the variables without their values |
| `--raw` | write the values as stored: do not interpret times, missing values and the like according to the CF conventions |
| `--decode-text` | write an attribute that holds a JSON or YAML document as that document; YAML needs PyYAML |
| `--max-elements N` | leave out the values of a variable with more than `N` elements |
| `--variable PATTERN` | write only the variables whose path or name matches the pattern; may be given several times |

A pattern is one of the shell: `*` stands for any text, `?` for one
character. It is compared with the path of a variable, such as
`/results/flow_cap`, and with its name, `flow_cap`. Quote it, so that the
shell does not take it for the name of a file.

The values of a variable are read when the variable is written. The memory
that a dump needs is that of the largest variable, not that of the file.

## JSON options

`convert` and `dump` share the options that decide how the JSON is written;
see [JSON](../documents/json.md).

| Option | Meaning |
|---|---|
| `--indent N` | spaces per nesting level; 2 if omitted |
| `--compact` | write the JSON without any whitespace |
| `--decimals N` | round numbers to `N` decimal places; written in full if omitted |
| `--non-finite {null,string,error}` | what becomes of `NaN` and the infinities: `null`, the strings `NaN`, `Infinity` and `-Infinity`, or an error; `null` if omitted |
| `--sort-keys` | write the keys in sorted order |
| `--ascii` | escape every character outside ASCII |
| `-q`, `--quiet` | do not write warnings to the standard error |

## inspect

```console
$ coati inspect optimization_results.h5
file:      optimization_results.h5
format:    HDF5
size:      112.4 kB
framework: AdOpT-NET0 version not recorded (adopt-net0-v0-1)
...
```

Shows the format of a file, the framework that wrote it and the groups with
their attributes, dimensions and variables. The values are not read, so the
command is fast for a file of any size. `--json` writes the summary as JSON.

The line `framework` names the identifier with the most detail that the file
allows. `version not recorded` says that the file does not state the version
that wrote it; name the version when converting, and the document states it.

## frameworks

```console
$ coati frameworks
IDENTIFIER       FRAMEWORK   VERSIONS            TESTED WITH        FORMATS
calliope-v0-6    Calliope    0.6.x               0.6.10             netCDF-4
calliope-v0-7    Calliope    0.7.x               0.7.0.dev7, 0.7.0  netCDF-4
pypsa-v0         PyPSA       0.25 and later 0.x  0.25.2, 0.35.2     netCDF-4, HDF5
pypsa-v1         PyPSA       1.x                 1.2.4, 1.3.0       netCDF-4, HDF5
adopt-net0-v0-1  AdOpT-NET0  0.1.x               0.1.10             HDF5
```

Lists the families of versions that Coati reads. `--json` writes the list as
JSON, for a program that wants to know what it may pass on.

## schema

```console
$ coati schema results > results.schema.json
```

Prints the [JSON Schema](https://json-schema.org/) of the results document or
of the dataset document, the one that the installed version writes.

## Messages and exit status

The command is silent on success. Messages go to the standard error and
start with `coati:`; the standard output holds nothing but a document that
was asked for with `-`.

| Status | Meaning |
|---|---|
| 0 | success |
| 1 | the conversion failed: the file cannot be read, the framework does not match, a value cannot be written |
| 2 | the command line is wrong |
| 130 | interrupted from the keyboard |
| 141 | the reader of the standard output left before the document was complete |

A warning does not change the status. It says what a reader of the document
should know about its making, and is part of the document as well, under
`warnings`:

```console
$ coati spores.nc results.json calliope-v0-7-0
coati: warning: spores.nc: the file holds 3 solutions of the SPORES mode; the
document reports the first, details.spores lists the cost, the capacities and
the generation of each
```

(The message is one line; it is broken here to fit the page.)

An error names the file and what is wrong with it:

```console
$ coati network.nc results.json calliope-v0-7-0
coati: network.nc: the file was written by PyPSA 1.2.4, not by Calliope 0.7.0

$ coati results.nc results.json calliope-v6-10
coati: results.nc: the file has the layout of Calliope 0.7.x, which differs
from that of Calliope 0.6.10

$ coati results.json out.json
coati: results.json: not a netCDF or HDF5 file; it looks like JSON
```
