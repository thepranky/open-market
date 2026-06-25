from pathlib import Path
from typing import Iterator

import yaml
from pydantic import ValidationError

from app.cases.models.concept import ConceptNode


def load_concept_file(path: Path) -> ConceptNode:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return ConceptNode.model_validate(data)


def load_all_concepts(concepts_dir: str) -> Iterator[tuple[Path, ConceptNode | Exception]]:
    root = Path(concepts_dir)
    for yaml_file in sorted(root.rglob("*.yaml")):
        try:
            yield yaml_file, load_concept_file(yaml_file)
        except (ValidationError, Exception) as exc:
            yield yaml_file, exc
