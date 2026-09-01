"""Regression tests for image-search dependency inversion."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pubmed_search.application.image_search as image_search_package
from pubmed_search.application.image_search import ImageSearchService
from pubmed_search.application.image_search.source_adapters import build_image_source_registry


def test_image_search_application_has_no_outer_layer_imports() -> None:
    package_dir = Path(image_search_package.__file__).parent
    violations: list[str] = []
    for module_path in sorted(package_dir.glob("*.py")):
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = [node.module]
            for module_name in imported:
                if module_name.startswith(("pubmed_search.infrastructure", "pubmed_search.presentation")):
                    violations.append(f"{module_path.name}:{node.lineno}: {module_name}")

    assert violations == []


def test_image_search_composition_dependencies_are_required() -> None:
    service_adapters = inspect.signature(ImageSearchService).parameters["adapters"]
    openi_factory = inspect.signature(build_image_source_registry).parameters["openi_client_factory"]

    assert service_adapters.default is inspect.Parameter.empty
    assert openi_factory.default is inspect.Parameter.empty
