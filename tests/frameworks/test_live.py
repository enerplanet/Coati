"""The frameworks themselves: solve a model, convert the file that the framework writes.

The other tests read files that were made once and are kept under
``tests/data``. These tests make the files anew, with whatever version of a
framework is installed, and compare the results document with what the
framework says about its own model. They tell when a new version of a
framework writes its files differently.

A test is skipped if its framework or a solver for it is not installed. Coati
and Calliope 0.6 cannot be installed together, as that version of Calliope
needs a version of Python that Coati does not support; the files of Calliope
0.6 are therefore tested from ``tests/data`` alone.
"""

from __future__ import annotations

import json
import shutil
from importlib import metadata
from pathlib import Path

import pytest

import coati
from support.compare import against_facts, as_json

pytestmark = [pytest.mark.frameworks, pytest.mark.filterwarnings("ignore")]

#: The solvers that the models can be solved with, and the program of each.
SOLVERS = {"cbc": "cbc", "glpk": "glpsol"}


def solver(*names: str) -> str:
    """Return the first of the solvers that is installed; skip the test if none is."""
    for name in names:
        if shutil.which(SOLVERS[name]):
            return name
    pytest.skip("no solver is installed: " + " or ".join(names))


def facts_of(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_pypsa(tmp_path: Path) -> None:
    pytest.importorskip("pypsa")
    from models import pypsa_model

    built = pypsa_model.build(tmp_path)
    facts = facts_of(built["facts.json"])
    version = metadata.version("pypsa")
    documents = {}
    for name in ("network.nc", "network.h5"):
        found = as_json(coati.results_document(built[name]))
        assert found["framework"] == "pypsa"
        assert found["framework_version"] == version
        assert found["success"] is True
        assert found["warnings"] == []
        assert against_facts(found, facts) == []
        del found["metadata"]
        documents[name] = found
    assert documents["network.nc"] == documents["network.h5"]
    unsolved = as_json(coati.results_document(built["unsolved.nc"]))
    assert unsolved["success"] is False
    assert unsolved["costs_by_location"] == {}
    if "stochastic.nc" in built:
        uncertain = as_json(coati.results_document(built["stochastic.nc"]))
        assert uncertain["scenarios"] == {"high": 0.25, "low": 0.75}
        assert uncertain["objective"] == pytest.approx(uncertain["objective_function_value"])
        assert len(uncertain["warnings"]) == 1


def test_calliope(tmp_path: Path) -> None:
    pytest.importorskip("calliope")
    from models import calliope07_model

    built = calliope07_model.build(tmp_path, solver("cbc", "glpk"))
    version = metadata.version("calliope")
    for name in ("model", "spores"):
        found = as_json(coati.results_document(built[f"{name}.nc"]))
        assert found["framework"] == "calliope"
        assert found["metadata"]["framework_family"] == "calliope-v0-7"
        assert found["framework_version"] in (version, None)
        assert found["success"] is True
        assert against_facts(found, facts_of(built[f"{name}.facts.json"])) == []
        assert len(found["warnings"]) == (1 if name == "spores" else 0)
    assert len(found["details"]["spores"]) == calliope07_model.SPORES + 1


def test_adopt_net0(tmp_path: Path) -> None:
    pytest.importorskip("adopt_net0")
    from models import adoptnet0_model

    built = adoptnet0_model.build(tmp_path, solver("glpk"))  # or Gurobi, which needs a licence
    for variant in adoptnet0_model.VARIANTS:
        found = as_json(coati.results_document(built[f"{variant}.h5"]))
        assert found["framework"] == "adopt-net0"
        assert found["success"] is True
        assert against_facts(found, facts_of(built[f"{variant}.facts.json"])) == []
        total = sum(sum(costs.values()) for costs in found["costs_by_location"].values())
        assert total == pytest.approx(found["objective"], rel=1e-9)
        if variant != "periods":
            assert found["warnings"] == []
