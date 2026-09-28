"""The package as a program: ``python -m coati``."""

from __future__ import annotations

import runpy
import sys

import pytest

import coati


def test_the_module_runs_the_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["coati", "--version"])
    with pytest.raises(SystemExit) as stop:
        runpy.run_module("coati", run_name="__main__")
    assert stop.value.code == 0
    assert capsys.readouterr().out == f"coati {coati.__version__}\n"


def test_the_exit_status_is_that_of_the_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["coati", "missing.nc", "-"])
    with pytest.raises(SystemExit) as stop:
        runpy.run_module("coati", run_name="__main__")
    assert stop.value.code == 1
    assert capsys.readouterr().err == "coati: missing.nc: no such file\n"


def test_importing_the_module_runs_nothing() -> None:
    assert runpy.run_module("coati.__main__", run_name="coati.__main__")["main"] is coati.cli.main
