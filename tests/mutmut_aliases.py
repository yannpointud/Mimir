"""Pytest plugin loaded only by mutmut (see [tool.mutmut] in pyproject.toml).

mutmut names a mutant after its file path (backend/src/rag_core/fusion.py gives
backend.src.rag_core.fusion) and only activates it when the running function's
__module__ has that exact name. The unit tests import the same files as src.*
(tests/conftest.py puts backend/ on sys.path), which loads a second, distinct
module object that would never see the mutants. Aliasing the src.* names to
the backend.src.* modules makes both import paths share one module object.
"""

import importlib
import sys
from pathlib import Path

# Same path setup as tests/conftest.py: backend.src.monitoring.logger imports
# src.config, so src must be importable before the modules below.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

MUTATED_MODULES = ("rag_core.fusion", "ingestion.chunking", "rag_core.tokenizer_fr")

for _name in MUTATED_MODULES:
    _module = importlib.import_module(f"backend.src.{_name}")
    _package, _, _attr = f"src.{_name}".rpartition(".")
    sys.modules[f"src.{_name}"] = _module
    setattr(importlib.import_module(_package), _attr, _module)
