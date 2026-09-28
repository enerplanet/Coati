# Releasing

A release is a tag. The workflow `release.yml` builds the distributions from
the tag, publishes them to [PyPI](https://pypi.org/project/enerplanet-coati/)
and creates the release on GitHub.

## Versions

The package follows [SemVer](https://semver.org/). Before 1.0, a minor
release may change the Python interface and the command line.

The version is written down in one place, `src/coati/_version.py`, as
Python writes versions. `CITATION.cff` and the changelog write the same
version as the other projects of the organisation do:

| `_version.py` | `CITATION.cff`, changelog, tag |
|---|---|
| `0.1.0a0` | `0.1.0-alpha` |
| `0.1.0` | `0.1.0` |

A test compares the two.

The documents have versions of their own, `schema_version`, which change
with the layout of a document and not with the package. See
[Changes of the layout](../documents/results.md#changes-of-the-layout).

## Steps

1. Make sure that `main` is what is to be released: CI passes, and the
   changelog lists what has changed under *Unreleased*.
2. On a branch `release/<version>`:
    - set the version in `src/coati/_version.py`
    - set `version` and `date-released` in `CITATION.cff`
    - in `CHANGELOG.md`, rename *Unreleased* to the version with the date,
      and start a new, empty *Unreleased*
3. Open a pull request, and merge it once CI passes.
4. Tag the merge commit and push the tag:

    ```console
    $ git tag --sign v0.1.0 --message "Coati 0.1.0"
    $ git push origin v0.1.0
    ```

The workflow refuses a tag that does not name the version of the package.

## PyPI

The workflow publishes through a
[trusted publisher](https://docs.pypi.org/trusted-publishers/): PyPI accepts
what this workflow of this repository uploads, and no token is stored
anywhere. It has to be set up once, by an owner of the project on PyPI:

| Setting | Value |
|---|---|
| PyPI project name | `enerplanet-coati` |
| Owner | `enerplanet` |
| Repository name | `Coati` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

For the first release, the project does not exist on PyPI yet; a *pending*
publisher with these settings creates it on the first upload. The
environment `pypi` of the repository can require a review, so that a
release is published only after a maintainer has approved it.

The badges of the readme take the version from `CITATION.cff` and the
versions of Python from `pyproject.toml`, as they are on `main`. They do not
ask PyPI, which knows nothing of a project before its first release and
would have the badges say so.

The description of the project on PyPI is the readme from its title on. The
banner above the title is left out, because GitHub chooses it by the colour
scheme of the viewer and PyPI would show both, and the links that are
relative to the repository lead to GitHub. `pyproject.toml` says how.

## Checking a release before it is made

```console
$ make build
```

builds the distributions into `dist/` and checks their metadata. Install the
wheel into a fresh environment and run the command:

```console
$ python -m venv /tmp/check && /tmp/check/bin/pip install dist/*.whl
$ /tmp/check/bin/coati --version
```
