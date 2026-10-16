"""Pytest plugin loaded only by mutmut (see [tool.mutmut] in pyproject.toml).

mutmut names a mutant after its file path (backend/mimir/rag_core/fusion.py
gives backend.mimir.rag_core.fusion) and only activates it when the running
function's __module__ has that exact name. The tests import the same files as
mimir.*, a second, distinct module object that would never see the mutants.
Aliasing the mimir.* names to the backend.mimir.* modules makes both import
paths share one module object.
"""

import importlib
import sys

MUTATED_MODULES = ("rag_core.fusion", "ingestion.chunking", "rag_core.tokenizer_fr")

for _name in MUTATED_MODULES:
    _module = importlib.import_module(f"backend.mimir.{_name}")
    _package, _, _attr = f"mimir.{_name}".rpartition(".")
    sys.modules[f"mimir.{_name}"] = _module
    setattr(importlib.import_module(_package), _attr, _module)
