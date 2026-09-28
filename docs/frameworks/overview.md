# Frameworks

Coati reads the result files of three modelling frameworks:

| Identifier | Framework | Versions | Tested with | Formats |
|---|---|---|---|---|
| `calliope-v0-6` | [Calliope](calliope.md#calliope-06) | 0.6.x | 0.6.10 | netCDF-4 |
| `calliope-v0-7` | [Calliope](calliope.md#calliope-07) | 0.7.x | 0.7.0.dev7, 0.7.0 | netCDF-4 |
| `pypsa-v0` | [PyPSA](pypsa.md) | 0.25 and later 0.x | 0.25.2, 0.35.2 | netCDF-4, HDF5 |
| `pypsa-v1` | [PyPSA](pypsa.md) | 1.x | 1.2.4, 1.3.0 | netCDF-4, HDF5 |
| `adopt-net0-v0-1` | [AdOpT-NET0](adopt-net0.md) | 0.1.x | 0.1.10 | HDF5 |

`coati frameworks` prints this list for the version that is installed.

## Framework identifiers

A framework identifier names a framework and a version:

```text
calliope-v0-6-10      Calliope 0.6.10
calliope-v0-7-0       Calliope 0.7.0
calliope-v0-7-0-dev7  Calliope 0.7.0.dev7
pypsa-v1-2-4          PyPSA 1.2.4
adopt-net0-v0-1-10    AdOpT-NET0 0.1.10
```

It consists of the name of the framework, the letter `v` and the parts of
the version. The rules are lenient about how it is written:

- The parts are separated by `-`, `.` or `_`: `pypsa-v1.2.4` and
  `pypsa_v1_2_4` are PyPSA 1.2.4. Capital letters are accepted.
- For a framework whose versions start with zero, the zero may be left out:
  `calliope-v6-10` is Calliope 0.6.10, and `adopt-net0-v1-10` is AdOpT-NET0
  0.1.10. A version that exists with and without the zero is taken as it is
  written: `pypsa-v1-2` is PyPSA 1.2, not 0.1.2.
- AdOpT-NET0 may be written `adopt-net0`, `adoptnet0`, `adopt_net0` or
  `adopt`.
- The version may be less than complete. `calliope-v0-7` names the versions
  0.7.x, `pypsa-v1` the versions 1.x, and `calliope` leaves the version to
  the file.
- `auto` leaves the framework and the version to the file. It is what an
  identifier that is left out stands for.

## Families

What decides how a file is read is not the exact version but the *family*:
the range of versions that write the same layout. Calliope 0.6 and 0.7 are
two families, because their files have nothing in common; PyPSA 1.2.4 and
1.3.0 are one.

A version is accepted if it belongs to a family, whether or not that very
version has been tested: `pypsa-v1-4-0` is read like the versions 1.x before
it. *Tested with* lists the versions whose files are part of the test suite
of Coati. A version that belongs to no family is refused:

```console
$ coati results.nc results.json calliope-v0-8
coati: 'calliope-v0-8': Calliope 0.8 is not supported; supported are
calliope-v0-6 (0.6.x), calliope-v0-7 (0.7.x)
```

## A claim is checked

An identifier is a claim about a file. Coati compares it with what it finds
in the file:

| The file | Result |
|---|---|
| was written by another framework | error: `the file was written by PyPSA 1.2.4, not by Calliope 0.7.0` |
| has the layout of another family | error: `the file has the layout of Calliope 0.7.x, which differs from that of Calliope 0.6.10` |
| has the layout of no framework | error: `the file does not have the layout of Calliope` |
| states another version of the same family | the file is read; the document states the version of the file and a warning |
| states no version | the file is read; the document states the version that was named |
| states the version that was named, or a version of the series that was named | the file is read |

A mix-up in a pipeline is thus an error and not a document full of wrong
numbers. The version that a file states has precedence over the one that is
named, because the file knows what wrote it:

```console
$ coati results.nc results.json calliope-v0-7-0
coati: warning: results.nc: the file states Calliope 0.7.0.dev7; it is read
as such, although Calliope 0.7.0 was named
```

## How a file is recognised

| Framework | Recognised by | Version from |
|---|---|---|
| Calliope 0.7 | the group `attrs` together with `inputs` or `results` | `calliope_version_initialised` of the record of the run, else `init.calliope_version` of the configuration |
| Calliope 0.6 | the attribute `calliope_version`, or the dimensions `loc_techs` and `techs` | the attribute `calliope_version` |
| PyPSA, netCDF | the attribute `network_pypsa_version`, or the dimension `snapshots` with dimensions that end in `_i` | the attribute `network_pypsa_version` |
| PyPSA, HDF5 | the tables `network` and `snapshots` | the column `pypsa_version` of the table `network` |
| AdOpT-NET0 | the groups `summary`, `design` and `operation` | not recorded |

Two kinds of files do not record the version that wrote them: those of
AdOpT-NET0, and those of Calliope 0.7.0, which records a version only if the
model declares one. The document then states `null` as the version of the
framework unless the caller names it.

A file may state a version that Coati does not know, such as one that is
released after Coati. If the file has the layout of a family, it is read
like that family, and the document says so in a warning.

## The document names the framework

Every results document says as what its file was read:

```json
{
  "framework": "calliope",
  "framework_version": "0.7.0",
  "metadata": {
    "framework_id": "calliope-v0-7-0",
    "framework_family": "calliope-v0-7"
  }
}
```

`framework_id` is an identifier that, passed back to Coati, reads the file
in the same way.
