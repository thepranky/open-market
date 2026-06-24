from pathlib import Path
from typing import Iterator

import yaml
from pydantic import ValidationError

from app.cases.models.case_index import CaseIndexEntry


def load_index_file(path: Path) -> CaseIndexEntry:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return CaseIndexEntry.model_validate(data)


def load_all_index_cases(index_dir: str) -> Iterator[tuple[Path, CaseIndexEntry | Exception]]:
    root = Path(index_dir)
    for yaml_file in sorted(root.rglob("*.yaml")):
        try:
            yield yaml_file, load_index_file(yaml_file)
        except (ValidationError, Exception) as exc:
            yield yaml_file, exc
