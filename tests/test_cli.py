"""The command ``coati``."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pytest

import coati
from coati.cli import EXIT_FAILURE, EXIT_OK, EXIT_USAGE, main
from support import files
from support.compare import as_json


class Run(NamedTuple):
    status: int
    out: str
    err: str


@pytest.fixture
def run(capsys: pytest.CaptureFixture[str]) -> object:
    def call(*arguments: object) -> Run:
        status = main([str(argument) for argument in arguments])
        captured = capsys.readouterr()
        return Run(status, captured.out, captured.err)

    return call


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return files.calliope07(tmp_path / "model.nc")


# -- converting -------------------------------------------------------------------------------


def test_source_output_and_framework(run, source: Path, tmp_path: Path) -> None:
    output = tmp_path / "results.json"
    assert run(source, output, "calliope-v0-7-0") == Run(EXIT_OK, "", "")
    assert json.loads(output.read_text()) == as_json(coati.results_document(source))


@pytest.mark.parametrize(
    "arguments",
    [
        ["{source}", "{output}"],
        ["{source}", "{output}", "auto"],
        ["{source}", "{output}", "calliope"],
        ["{source}", "{output}", "calliope-v7-0"],
        ["{source}", "{output}", "-f", "calliope-v0-7-0"],
        ["{source}", "{output}", "--framework", "calliope-v0-7-0"],
        ["{source}", "{output}", "--framework=calliope-v0-7-0"],
        ["-f", "calliope-v0-7-0", "{source}", "{output}"],
        ["{source}", "{output}", "--compact", "calliope-v0-7-0"],
        ["{source}", "--quiet", "{output}", "--sort-keys", "calliope-v0-7-0"],
        ["--indent", "4", "{source}", "{output}", "calliope-v0-7-0"],
        ["convert", "--decimals", "3", "{source}", "{output}", "calliope-v0-7-0"],
        ["{source}", "{output}", "calliope-v0-7-0", "-f", "calliope-v0-7-0"],
        ["convert", "{source}", "{output}", "calliope-v0-7-0"],
        ["convert", "-f", "calliope-v0-7", "{source}", "{output}"],
    ],
)
def test_the_ways_to_say_the_same(run, source: Path, tmp_path: Path, arguments: list[str]) -> None:
    output = tmp_path / "results.json"
    given = [argument.format(source=source, output=output) for argument in arguments]
    assert run(*given) == Run(EXIT_OK, "", "")
    assert json.loads(output.read_text())["metadata"]["framework_id"] == "calliope-v0-7-0"


def test_the_shorthand_of_the_version(run, tmp_path: Path) -> None:
    source = files.calliope06(tmp_path / "model.nc")
    output = tmp_path / "results.json"
    assert run(source, output, "calliope-v6-10") == Run(EXIT_OK, "", "")
    assert json.loads(output.read_text())["metadata"]["framework_id"] == "calliope-v0-6-10"


def test_the_standard_output(run, source: Path) -> None:
    found = run(source, "-", "calliope-v0-7-0", "--compact")
    assert found.status == EXIT_OK
    assert found.err == ""
    assert found.out.endswith("}\n")
    assert found.out.count("\n") == 1
    assert json.loads(found.out) == as_json(coati.results_document(source))


def test_a_file_whose_name_is_that_of_a_command(
    run, source: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    source.rename(tmp_path / "inspect")
    assert run("convert", "inspect", "results.json").status == EXIT_OK
    assert run("./inspect", "other.json").status == EXIT_OK
    assert (tmp_path / "results.json").read_text() == (tmp_path / "other.json").read_text().replace(
        '"./inspect"', '"inspect"'
    )


def test_the_choices_about_the_content(run, tmp_path: Path) -> None:
    source = files.adopt_net0(tmp_path / "results.h5", periods=("early", "late"))
    found = run(
        source, "-", "adopt-net0-v0-1-10", "--period", "late", "--no-labels",
        "--time-start", "2030-01-01", "--time-step", "1h", "--quiet",
    )  # fmt: skip
    assert found.status == EXIT_OK
    assert found.err == ""
    document = json.loads(found.out)
    assert document["details"]["period"] == "late"
    assert document["capacities"]["a::Wind"] == 6.0
    assert document["timestamps"] == files.TIMESTAMPS
    assert document["framework_version"] == "0.1.10"


def test_labels_can_be_left_out(run, source: Path) -> None:
    document = json.loads(run(source, "-", "--no-labels").out)
    assert document["tech_metadata"]["pv"] == {"parent": "supply", "carrier_out": "power"}


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ([], '{\n  "schema_version": "1.0",\n  "framework"'),
        (["--indent", "4"], '{\n    "schema_version": "1.0",\n    "framework"'),
        (["--indent", "0"], '{\n"schema_version": "1.0",\n"framework"'),
        (["--compact"], '{"schema_version":"1.0","framework"'),
        (["--sort-keys", "--compact"], '{"capacities":{"a::line":5.0,"a::pv":10.0,'),
    ],
)
def test_the_layout(run, source: Path, arguments: list[str], expected: str) -> None:
    assert run(source, "-", *arguments).out.startswith(expected)


def test_rounding(run, tmp_path: Path) -> None:
    source = files.calliope07(tmp_path / "model.nc")
    assert json.loads(run(source, "-").out)["unmet_demand_timeseries"] == [0.0, 0.5, 0.0]
    rounded = json.loads(run(source, "-", "--decimals", "0").out)
    assert rounded["unmet_demand_timeseries"] == [0.0, 0.0, 0.0]


def test_characters_outside_ascii(run, tmp_path: Path) -> None:
    # The file is named by Python: on Windows, the netCDF library names it in another encoding.
    source = files.calliope07(tmp_path / "model.nc").rename(tmp_path / "größe.nc")
    assert '"name": "größe.nc"' in run(source, "-").out
    escaped = run(source, "-", "--ascii").out
    assert escaped.isascii()
    assert json.loads(escaped)["metadata"]["source"]["name"] == "größe.nc"


@pytest.mark.parametrize("command", [[], ["dump"], ["inspect"], ["inspect", "--json"]])
def test_the_standard_output_is_utf_8_whatever_the_platform_prefers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: list[str]
) -> None:
    # As on Windows: the stream has the code page of the system and its ends of lines.
    source = files.calliope07(tmp_path / "model.nc").rename(tmp_path / "模型.nc")
    written = io.BytesIO()
    stream = io.TextIOWrapper(written, encoding="cp1252", newline="\r\n")
    monkeypatch.setattr(sys, "stdout", stream)
    output = [] if command[:1] == ["inspect"] else ["-"]
    assert main([*command, str(source), *output]) == EXIT_OK
    stream.flush()
    text = written.getvalue().decode("utf-8")
    assert "模型.nc" in text
    assert "\r" not in text
    assert text.endswith("\n")


def test_numbers_that_are_not_finite(run, tmp_path: Path) -> None:
    source = files.calliope07(tmp_path / "model.nc")
    with files.netCDF4.Dataset(source, "a") as dataset:
        dataset["results"].variables["flow_cap"][0, 0, 0] = float("inf")
    assert json.loads(run(source, "-").out)["capacities"]["a::pv"] is None
    text = run(source, "-", "--non-finite", "string").out
    assert json.loads(text)["capacities"]["a::pv"] == "Infinity"
    output = tmp_path / "results.json"
    found = run(source, output, "--non-finite", "error")
    assert found.status == EXIT_FAILURE
    assert found.err == (
        'coati: $.capacities["a::pv"]: Infinity is not a JSON number'
        " (choose the non-finite policy 'null' or 'string' to write it)\n"
    )
    assert not output.exists()


# -- warnings ---------------------------------------------------------------------------------


def test_warnings_go_to_the_standard_error(run, source: Path, tmp_path: Path) -> None:
    output = tmp_path / "results.json"
    found = run(source, output, "calliope-v0-7-0-dev7")
    assert found.status == EXIT_OK
    assert found.out == ""
    assert found.err == (
        f"coati: warning: {source}: the file states Calliope 0.7.0; it is read as such,"
        " although Calliope 0.7.0.dev7 was named\n"
    )
    assert len(json.loads(output.read_text())["warnings"]) == 1


def test_warnings_can_be_silenced(run, source: Path, tmp_path: Path) -> None:
    output = tmp_path / "results.json"
    for flag in ("-q", "--quiet"):
        assert run(source, output, "calliope-v0-7-0-dev7", flag) == Run(EXIT_OK, "", "")
    assert len(json.loads(output.read_text())["warnings"]) == 1


def test_a_run_leaves_nothing_behind_for_the_next(run, source: Path, tmp_path: Path) -> None:
    import logging

    before = list(logging.getLogger("coati").handlers)
    run(source, tmp_path / "a.json", "calliope-v0-7-0-dev7", "--quiet")
    found = run(source, tmp_path / "b.json", "calliope-v0-7-0-dev7")
    assert found.err.count("warning") == 1
    assert logging.getLogger("coati").handlers == before


# -- failures ---------------------------------------------------------------------------------


def test_another_framework(run, source: Path, tmp_path: Path) -> None:
    output = tmp_path / "results.json"
    found = run(source, output, "pypsa-v1-2-4")
    assert found == Run(
        EXIT_FAILURE,
        "",
        f"coati: {source}: the file was written by Calliope 0.7.0, not by PyPSA 1.2.4\n",
    )
    assert not output.exists()


def test_another_family(run, source: Path, tmp_path: Path) -> None:
    found = run(source, tmp_path / "results.json", "calliope-v6-10")
    assert found.status == EXIT_FAILURE
    assert "which differs from that of Calliope 0.6.10" in found.err


def test_an_identifier_that_names_nothing(run, source: Path, tmp_path: Path) -> None:
    found = run(source, tmp_path / "results.json", "oemof-v1")
    assert found == Run(
        EXIT_FAILURE,
        "",
        "coati: 'oemof-v1' names an unknown framework;"
        " the frameworks are adopt-net0, calliope, pypsa\n",
    )


def test_a_source_that_does_not_exist(run, tmp_path: Path) -> None:
    missing = tmp_path / "missing.nc"
    assert run(missing, tmp_path / "results.json") == Run(
        EXIT_FAILURE, "", f"coati: {missing}: no such file\n"
    )


def test_a_source_that_is_no_data_file(run, tmp_path: Path) -> None:
    source = tmp_path / "data.nc"
    source.write_text("{}")
    assert run(source, "-") == Run(
        EXIT_FAILURE, "", f"coati: {source}: not a netCDF or HDF5 file; it looks like JSON\n"
    )


def test_an_output_that_cannot_be_written(run, source: Path, tmp_path: Path) -> None:
    output = tmp_path / "missing" / "results.json"
    assert run(source, output) == Run(
        EXIT_FAILURE, "", f"coati: {output}: No such file or directory\n"
    )


def test_a_period_that_the_file_lacks(run, tmp_path: Path) -> None:
    source = files.adopt_net0(tmp_path / "results.h5")
    found = run(source, "-", "--period", "late")
    assert found.status == EXIT_FAILURE
    assert found.out == ""
    assert found.err == f"coati: {source}: no investment period 'late'; the file has period1\n"


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--time-start", "soon", "--time-step", "1h"], "'soon' is not a time"),
        (["--time-start", "2030-01-01", "--time-step", "often"], "'often' is not a duration"),
    ],
)
def test_choices_that_make_no_sense(run, source: Path, arguments: list[str], message: str) -> None:
    found = run(source, "-", *arguments)
    assert found.status == EXIT_FAILURE
    assert found.out == ""
    assert message in found.err


# -- a command line that is wrong -------------------------------------------------------------


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["model.nc"], "coati convert: the following arguments are required: OUTPUT"),
        (["convert"], "coati convert: the following arguments are required: SOURCE, OUTPUT"),
        ([], "coati: the following arguments are required: COMMAND"),
        (["a", "b", "c", "d"], "coati convert: unrecognized arguments: d"),
        (["a", "b", "--unknown"], "coati convert: unrecognized arguments: --unknown"),
        (["--unknown"], "coati: the following arguments are required: COMMAND"),
        (["a", "b", "--indent", "-1"], "'-1' is not a whole number of zero or more"),
        (["a", "b", "--indent", "two"], "'two' is not a whole number of zero or more"),
        (["a", "b", "--decimals", "1.5"], "'1.5' is not a whole number of zero or more"),
        (["a", "b", "--non-finite", "zero"], "argument --non-finite: invalid choice: 'zero'"),
        (["a", "b", "--compact", "--indent", "2"], "not allowed with argument"),
        (["a", "b", "--indent", "4", "--compact"], "not allowed with argument"),
        (["--compact", "convert", "a", "b"], "coati: unrecognized arguments: --compact"),
        (["inspect", "a", "b"], "coati inspect: unrecognized arguments: b"),
        (
            ["a", "b", "--time-start", "2030-01-01"],
            "--time-start and --time-step must be given together",
        ),
        (["a", "b", "--time-step", "1h"], "--time-start and --time-step must be given together"),
        (
            ["a", "b", "calliope", "-f", "pypsa"],
            "the framework is given twice: as 'calliope' and as --framework 'pypsa'",
        ),
        (["dump", "a"], "coati dump: the following arguments are required: OUTPUT"),
        (["dump", "a", "b", "calliope"], "coati dump: unrecognized arguments: calliope"),
        (["dump", "a", "b", "--max-elements", "-1"], "is not a whole number of zero or more"),
        (["inspect"], "coati inspect: the following arguments are required: SOURCE"),
        (["schema"], "coati schema: the following arguments are required: document"),
        (["schema", "other"], "invalid choice: 'other'"),
        (["frameworks", "extra"], "unrecognized arguments: extra"),
    ],
)
def test_a_wrong_command_line(run, arguments: list[str], message: str) -> None:
    found = run(*arguments)
    assert found.status == EXIT_USAGE
    assert found.out == ""
    assert found.err.startswith("usage: coati")
    assert message in found.err
    assert "Traceback" not in found.err


def test_nothing_is_written_for_a_wrong_command_line(run, source: Path, tmp_path: Path) -> None:
    output = tmp_path / "results.json"
    assert run(source, output, "--time-step", "1h").status == EXIT_USAGE
    assert not output.exists()


# -- help and version -------------------------------------------------------------------------


@pytest.mark.parametrize("flag", ["-V", "--version"])
def test_the_version(run, flag: str) -> None:
    assert run(flag) == Run(EXIT_OK, f"coati {coati.__version__}\n", "")


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (
            ["--help"],
            ["usage: coati [-h] [-V] COMMAND ...", "convert", "dump", "inspect", "frameworks"],
        ),
        (["-h"], ["Without a command, coati converts: coati SOURCE OUTPUT [FRAMEWORK]."]),
        (
            ["convert", "--help"],
            ["usage: coati convert", "SOURCE OUTPUT [FRAMEWORK]", "pypsa-v1-2-4", "--no-labels"],
        ),
        (["dump", "-h"], ["usage: coati dump", "--raw", "--decode-text", "--variable PATTERN"]),
        (["inspect", "-h"], ["usage: coati inspect", "--json"]),
        (["frameworks", "-h"], ["usage: coati frameworks"]),
        (["schema", "-h"], ["usage: coati schema", "{dataset,results}"]),
    ],
)  # fmt: skip
def test_help(run, arguments: list[str], expected: list[str]) -> None:
    found = run(*arguments)
    assert found.status == EXIT_OK
    assert found.err == ""
    for text in expected:
        assert text in found.out


# -- the other commands -----------------------------------------------------------------------


def test_dump(run, source: Path, tmp_path: Path) -> None:
    output = tmp_path / "dataset.json"
    assert run("dump", source, output) == Run(EXIT_OK, "", "")
    assert json.loads(output.read_text()) == as_json(coati.dataset_document(source))


def test_the_choices_of_dump(run, source: Path) -> None:
    found = run(
        "dump", source, "-", "--raw", "--max-elements", "3", "--decode-text", "--compact",
        "--variable", "/results/timesteps", "--variable", "flow_out",
    )  # fmt: skip
    assert found.status == EXIT_OK
    document = json.loads(found.out)
    variables = document["groups"]["results"]["variables"]
    assert list(variables) == ["flow_out", "timesteps"]
    assert variables["timesteps"]["data"] == [0, 1, 2]
    assert variables["timesteps"]["attributes"]["units"] == files.TIME_UNITS
    assert variables["flow_out"]["data_omitted"] is True
    assert document["groups"]["attrs"]["attributes"]["config"]["solve"]["solver"] == "highs"
    assert document["groups"]["inputs"]["variables"] == {}


def test_dump_without_values(run, source: Path) -> None:
    document = json.loads(run("dump", source, "-", "--no-data").out)
    assert "data" not in document["groups"]["results"]["variables"]["flow_cap"]


def test_dump_reads_any_file(run, tmp_path: Path) -> None:
    source = files.write_netcdf(tmp_path / "data.nc", {"attributes": {"title": "x"}})
    assert json.loads(run("dump", source, "-").out)["attributes"] == {"title": "x"}


def test_inspect(run, source: Path) -> None:
    found = run("inspect", source)
    assert found.status == EXIT_OK
    assert found.err == ""
    lines = found.out.splitlines()
    assert lines[:4] == [
        "file:      model.nc",
        "format:    netCDF-4",
        f"size:      {source.stat().st_size / 1000:.1f} kB",
        "framework: Calliope 0.7.0 (calliope-v0-7-0)",
    ]
    assert "group /results" in lines
    assert "  dimensions: nodes (2), techs (4), carriers (1), costs (2), timesteps (3)" in lines
    assert "    flow_cap               float64  (nodes: 2, techs: 4, carriers: 1)" in lines
    assert "    min_cost_optimisation  float64  ()" in lines
    assert "  attributes: config, runtime" in lines


def test_inspect_as_json(run, source: Path) -> None:
    found = run("inspect", source, "--json")
    assert json.loads(found.out) == coati.inspect(source)


def test_inspect_a_file_of_no_framework(run, tmp_path: Path) -> None:
    import h5py

    source = tmp_path / "data.h5"
    with h5py.File(source, "w") as file:
        file.create_dataset("values", data=[[1, 2]])
        file["outside"] = h5py.ExternalLink("other.h5", "/x")
    lines = run("inspect", source).out.splitlines()
    assert "format:    HDF5" in lines
    assert "framework: not recognised" in lines
    assert "    values  int64  (?: 1, ?: 2)" in lines
    assert "warning: /outside is a link into the file 'other.h5'; it is not followed" in lines


def test_inspect_a_file_without_a_version(run, tmp_path: Path) -> None:
    source = files.adopt_net0(tmp_path / "results.h5")
    assert (
        "framework: AdOpT-NET0 version not recorded (adopt-net0-v0-1)" in run("inspect", source).out
    )


def test_frameworks(run) -> None:
    found = run("frameworks")
    assert found.status == EXIT_OK
    lines = found.out.splitlines()
    assert lines[0].split() == ["IDENTIFIER", "FRAMEWORK", "VERSIONS", "TESTED", "WITH", "FORMATS"]
    assert [line.split()[0] for line in lines[1:]] == [family.id for family in coati.FAMILIES]
    assert "calliope-v0-7    Calliope    0.7.x               0.7.0.dev7, 0.7.0  netCDF-4" in lines
    assert all(line == line.rstrip() for line in lines)


def test_frameworks_as_json(run) -> None:
    listed = json.loads(run("frameworks", "--json").out)
    assert [entry["id"] for entry in listed] == [family.id for family in coati.FAMILIES]
    assert listed[0] == {
        "id": "calliope-v0-6",
        "framework": "calliope",
        "title": "Calliope",
        "versions": "0.6.x",
        "tested": ["0.6.10"],
        "formats": ["netcdf4"],
        "layout": "one group; sets that join location, technology and carrier",
    }


@pytest.mark.parametrize("document", ["results", "dataset"])
def test_schema(run, document: str) -> None:
    found = run("schema", document)
    assert found.status == EXIT_OK
    schema = json.loads(found.out)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["title"] == f"Coati {document} document"
    assert found.out.endswith("}\n")


# -- as a program -----------------------------------------------------------------------------


def program(*arguments: object, **options: object) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, "-m", "coati", *(str(argument) for argument in arguments)]
    return subprocess.run(command, capture_output=True, text=True, check=False, **options)  # noqa: S603


def test_the_module_is_a_program(source: Path, tmp_path: Path) -> None:
    output = tmp_path / "results.json"
    found = program(source, output, "calliope-v0-7-0")
    assert (found.returncode, found.stdout, found.stderr) == (0, "", "")
    assert json.loads(output.read_text())["objective"] == 128.0
    assert program("--version").stdout == f"coati {coati.__version__}\n"


def test_the_exit_status_of_the_program(source: Path, tmp_path: Path) -> None:
    found = program(source, tmp_path / "results.json", "pypsa")
    assert found.returncode == 1
    assert found.stderr.startswith("coati: ")
    assert "Traceback" not in found.stderr
    assert program(source).returncode == 2


@pytest.mark.skipif(sys.platform == "win32", reason="needs the pipes of a POSIX shell")
@pytest.mark.parametrize("command", ["dump {source} -", "{source} -", "schema results"])
def test_a_reader_that_leaves_ends_the_command_without_a_message(
    tmp_path: Path, command: str
) -> None:
    # The file is large enough for the document not to fit into the pipe at once.
    source = files.write_netcdf(
        tmp_path / "model.nc",
        {"dimensions": {"x": 200_000}, "variables": {"values": (("x",), np.arange(200_000.0))}},
    )
    if not command.startswith(("dump", "schema")):
        source = files.calliope07(tmp_path / "results.nc")
    piped = f"{sys.executable} -m coati {command.format(source=source)} | head -c 20"
    shell = ["bash", "-o", "pipefail", "-c", piped]
    found = subprocess.run(shell, capture_output=True, text=True, check=False)  # noqa: S603
    assert found.stdout == '{\n  "schema_version"' or found.stdout.startswith('{\n  "$schema"')
    assert found.stderr == ""
    assert found.returncode in (0, 141)


def test_the_status_of_a_closed_pipe(capsys: pytest.CaptureFixture[str]) -> None:
    class Closed:
        def write(self, text: str) -> int:
            raise BrokenPipeError(32, "Broken pipe")

        def flush(self) -> None:
            raise BrokenPipeError(32, "Broken pipe")

        def fileno(self) -> int:
            raise io.UnsupportedOperation("fileno")

    stdout, sys.stdout = sys.stdout, Closed()  # type: ignore[assignment]
    try:
        status = main(["frameworks"])
    finally:
        sys.stdout = stdout
    assert status == 141
    assert capsys.readouterr().err == ""
