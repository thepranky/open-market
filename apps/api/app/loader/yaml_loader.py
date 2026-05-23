import os
from pathlib import Path
from typing import Iterator

import yaml
from pydantic import ValidationError

from app.models import CaseRecord


def load_yaml_file(path: Path) -> CaseRecord:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return CaseRecord.model_validate(data)


def load_all_cases(cases_dir: str) -> Iterator[tuple[Path, CaseRecord | Exception]]:
    root = Path(cases_dir)
    for yaml_file in sorted(root.rglob("*.yaml")):
        try:
            record = load_yaml_file(yaml_file)
            yield yaml_file, record
        except (ValidationError, Exception) as exc:
            yield yaml_file, exc


def load_cases_dict(cases_dir: str) -> dict[str, CaseRecord]:
    cases: dict[str, CaseRecord] = {}
    for path, result in load_all_cases(cases_dir):
        if isinstance(result, CaseRecord):
            cases[result.case_id] = result
    return cases
