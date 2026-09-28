"""What all tests share: the files of ``tests/data`` and the expected documents."""

from __future__ import annotations

import json
import lzma
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from coati import jsonio
from support.compare import differences

DATA = Path(__file__).parent / "data"
EXPECTED = DATA / "expected"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-expected",
        action="store_true",
        help="rewrite the expected documents under tests/data/expected instead of comparing",
    )


@pytest.fixture(autouse=True)
def plain_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the messages of the command plain, whatever the environment asks for.

    From Python 3.14 on, the command line colours its help and its messages
    if the environment asks for colours, as that of CI does.
    """
    monkeypatch.setenv("NO_COLOR", "1")
    for name in ("FORCE_COLOR", "PYTHON_COLORS"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The files of ``tests/data``, unpacked into a directory of their own."""
    target = tmp_path_factory.mktemp("data")
    for packed in sorted(DATA.glob("*.xz")):
        (target / packed.name[: -len(".xz")]).write_bytes(lzma.decompress(packed.read_bytes()))
    return target


@pytest.fixture
def expect(request: pytest.FixtureRequest) -> Callable[[str, Any], None]:
    """Compare a document with the expected one of the given name.

    With ``--update-expected`` the expected document is rewritten instead, and
    the test is skipped to make plain that nothing has been checked.
    """

    def compare(name: str, document: Any) -> None:
        path = EXPECTED / f"{name}.json"
        if request.config.getoption("--update-expected"):
            EXPECTED.mkdir(exist_ok=True)
            jsonio.write_file(document, path, jsonio.JsonOptions(decimals=9))
            pytest.skip(f"{path.name} has been rewritten")
        expected = json.loads(path.read_text(encoding="utf-8"))
        found = json.loads(jsonio.dumps(document))
        assert differences(found, expected) == []

    return compare
