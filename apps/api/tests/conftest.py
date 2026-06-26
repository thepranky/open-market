"""Shared pytest path setup for pipeline script imports."""
import sys
from pathlib import Path

_API = Path(__file__).resolve().parent.parent
_SCRIPTS = _API / "scripts"
# scripts/cases is regrouped into stage subfolders (discovery/ extract/ review/ promote/
# integrity/ evals/ embeddings/). Scripts import siblings flat (e.g. `from ingest_case
# import …`), so every bucket dir must be on sys.path — not just scripts/cases itself.
_roots = [_SCRIPTS / "cases", _SCRIPTS / "screening"]
_roots += [d for d in (_SCRIPTS / "cases").iterdir() if d.is_dir() and d.name != "__pycache__"]
for _root in _roots:
    _p = str(_root)
    if _p not in sys.path:
        sys.path.insert(0, _p)
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))
