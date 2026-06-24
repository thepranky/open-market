from pathlib import Path

from pydantic import ValidationError

from app.cases.loader.yaml_loader import load_all_cases


def validate_all(cases_dir: str) -> tuple[int, int, list[str]]:
    """Returns (ok_count, error_count, error_messages)."""
    ok = 0
    errors: list[str] = []

    for path, result in load_all_cases(cases_dir):
        if isinstance(result, ValidationError):
            errors.append(f"{path}: ValidationError\n{result}")
        elif isinstance(result, Exception):
            errors.append(f"{path}: {type(result).__name__}: {result}")
        else:
            ok += 1

    return ok, len(errors), errors
