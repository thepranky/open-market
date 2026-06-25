"""Shared pytest path setup for pipeline script imports."""
import sys
from pathlib import Path

_API = Path(__file__).resolve().parent.parent
_SCRIPTS = _API / "scripts"
for _sub in ("cases", "screening"):
    _p = str(_SCRIPTS / _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)
if str(_API) not in sys.path:
    sys.path.insert(0, str(_API))
