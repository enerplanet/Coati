"""Make the files under ``tests/data`` with the framework that is installed.

Run it with the interpreter of an environment that has one of the frameworks
and a solver, from the directory ``tests``::

    python -m models.fixtures pypsa data
    python -m models.fixtures calliope data
    python -m models.fixtures adopt-net0 data

Each run builds the model of the framework, solves it, and writes the file of
results, compressed with xz, together with the facts that the framework states
about the model. The names of the files carry the version of the framework, so
files of several versions live side by side.

Calliope 0.6 needs Python 3.9 or older, so this module does without what newer
versions of Python have added.
"""

from __future__ import annotations

import lzma
import sys
import tempfile
from importlib import metadata
from pathlib import Path

USAGE = "usage: python -m models.fixtures {pypsa,calliope,adopt-net0} DIRECTORY"


def _pypsa(work: Path) -> tuple[str, dict[str, Path]]:
    from models import pypsa_model

    version = metadata.version("pypsa")
    built = pypsa_model.build(work)
    names = {
        "network.nc": "{}.nc",
        "network.h5": "{}.h5",
        "facts.json": "{}.facts.json",
        "stochastic.nc": "{}-stochastic.nc",
        "unsolved.nc": "{}-unsolved.nc",
    }
    stem = f"pypsa-{version}"
    return stem, {names[name].format(stem): path for name, path in built.items()}


def _calliope(work: Path) -> tuple[str, dict[str, Path]]:
    version = metadata.version("calliope")
    stem = f"calliope-{version}"
    if version.startswith("0.6"):
        from models import calliope06_model

        built = calliope06_model.build(work)
    else:
        from models import calliope07_model

        built = calliope07_model.build(work)
    names = {
        "model.nc": "{}.nc",
        "model.facts.json": "{}.facts.json",
        "spores.nc": "{}-spores.nc",
        "spores.facts.json": "{}-spores.facts.json",
    }
    return stem, {names[name].format(stem): path for name, path in built.items()}


def _adopt_net0(work: Path) -> tuple[str, dict[str, Path]]:
    from models import adoptnet0_model

    version = metadata.version("adopt_net0")
    stem = f"adopt-net0-{version}"
    built = adoptnet0_model.build(work)
    names = {
        "base.h5": "{}.h5",
        "base.facts.json": "{}.facts.json",
        "typical-days.h5": "{}-typical-days.h5",
        "typical-days.facts.json": "{}-typical-days.facts.json",
        "periods.h5": "{}-periods.h5",
        "periods.facts.json": "{}-periods.facts.json",
    }
    return stem, {names[name].format(stem): path for name, path in built.items()}


BUILDERS = {"pypsa": _pypsa, "calliope": _calliope, "adopt-net0": _adopt_net0}


def main(arguments: list[str]) -> int:
    """Build the files of one framework; return the exit status."""
    if len(arguments) != 2 or arguments[0] not in BUILDERS:
        sys.stderr.write(USAGE + "\n")
        return 2
    directory = Path(arguments[1])
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as work:
        _, built = BUILDERS[arguments[0]](Path(work))
        for name, path in sorted(built.items()):
            if name.endswith(".json"):
                target = directory / name
                target.write_bytes(path.read_bytes())
            else:
                target = directory / (name + ".xz")
                packed = lzma.compress(path.read_bytes(), preset=9 | lzma.PRESET_EXTREME)
                target.write_bytes(packed)
            sys.stdout.write(f"{target} ({target.stat().st_size} bytes)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
