# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| latest minor release (`0.x`) | yes |
| earlier releases | no, upgrade first |

Fixes ship in a new minor or patch release of the latest line; there are no
backports before 1.0.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's
private vulnerability reporting for this repository:

<https://github.com/enerplanet/Coati/security/advisories/new>

Include the Coati version or commit, the command or the call, and a file that
reproduces the problem, as small as possible and with any confidential values
removed, and a description of the impact. You will get an acknowledgement
within five working days. We aim to publish a fix or a mitigation within
thirty days of confirming the report and will credit you in the release notes
unless you prefer otherwise.

## Scope

In scope: the `coati` package and command: the readers of netCDF and HDF5
files, the interpretation of their contents, the extraction of results and
the writing of JSON.

Out of scope: the frameworks whose files Coati reads (Calliope, PyPSA,
AdOpT-NET0), the libraries Coati depends on (h5py with the HDF5 library,
NumPy) and the services that consume the documents. Report those to their
maintainers.

## What is already in place

Coati reads files that may come from elsewhere, so the readers treat a file
as data that cannot be trusted:

- Coati performs no network access and executes nothing; it reads a file and
  writes a document.
- The files that PyPSA exports to HDF5 hold the names of their columns as
  pickles, the serialisation format of Python, which can run code when it is
  read. Coati reads them with an unpickler that refuses every class and
  function, so that a pickle can yield lists, texts and numbers and nothing
  else.
- Links from an HDF5 file into other files are not followed; the document
  names them in a warning. Groups that contain themselves are read once.
- The reader of the classic netCDF formats checks every offset and length
  against the size of the file before it reads, and refuses a file whose
  header states more than the file holds.
- YAML is parsed with the safe loader of PyYAML, and only if the caller asks
  for it; the results are read from YAML with a parser of Coati's own that
  knows scalars and mappings alone.
- The folder of a run on the machine that ran it, which AdOpT-NET0 records in
  its files, is left out of the documents.
- An output file is replaced only after its document has been written in
  full, and keeps its permissions.
- The CI lints the code with the security rules of ruff (`flake8-bandit`).

Reading a file takes memory in proportion to its largest variable, and a
compressed variable can be much larger than the file. Set a limit for the
process where files of unknown origin are converted, and use
`coati dump --max-elements` to leave out the values of large variables.
