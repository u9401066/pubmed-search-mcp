"""Regression tests for the ICD application/presentation boundary."""

from __future__ import annotations

import ast
import inspect
from typing import TYPE_CHECKING

from pubmed_search.application.search import icd as application_icd
from pubmed_search.presentation.mcp_server.tools import icd as presentation_icd

if TYPE_CHECKING:
    from types import ModuleType


def _imported_modules(module: ModuleType) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def test_icd_application_logic_does_not_depend_on_presentation() -> None:
    imports = _imported_modules(application_icd)
    assert not any(name.startswith("pubmed_search.presentation") for name in imports)


def test_icd_presentation_module_is_registration_only() -> None:
    assert presentation_icd.__all__ == ["register_icd_tools"]
    assert presentation_icd._icd_service is application_icd
    for business_symbol in (
        "ICD9_TO_MESH",
        "ICD10_TO_MESH",
        "detect_icd_version",
        "get_icd_reference",
        "lookup_icd_to_mesh",
        "lookup_mesh_to_icd",
    ):
        assert not hasattr(presentation_icd, business_symbol)
