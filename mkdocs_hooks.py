"""Hooks of the documentation site: publish the JSON Schemas where their `$id` points.

The schemas of the documents are part of the package, under `coati/schemas`,
and each names its own address with `$id`, such as
https://enerplanet.github.io/Coati/schemas/results-1.0.schema.json. The site is
served at that host, so the schemas are copied into it under `schemas/` when
the site is built. MkDocs loads this file through `hooks:` in `mkdocs.yml`.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCHEMAS = Path(__file__).parent / "src" / "coati" / "schemas"


def published_name(schema: Path) -> str:
    """Return the name under which `$id` publishes the schema, such as results-1.0.schema.json."""
    identifier = json.loads(schema.read_text(encoding="utf-8"))["$id"]
    return Path(urlparse(identifier).path).name


def on_post_build(config: Any, **_: Any) -> None:
    """Copy the schemas into the built site under `schemas/`."""
    target = Path(config["site_dir"]) / "schemas"
    target.mkdir(parents=True, exist_ok=True)
    for schema in sorted(SCHEMAS.glob("*.schema.json")):
        shutil.copyfile(schema, target / published_name(schema))
