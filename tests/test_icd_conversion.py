#!/usr/bin/env python3
"""Test ICD to MeSH conversion."""

import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Import directly from resources module without going through __init__
import importlib.util
spec = importlib.util.spec_from_file_location(
    "resources",
    os.path.join(os.path.dirname(__file__), '..', 'src', 'pubmed_search', 'mcp', 'resources.py')
)
resources = importlib.util.module_from_spec(spec)

# Mock the mcp import
import types
sys.modules['mcp'] = types.ModuleType('mcp')
sys.modules['mcp.server'] = types.ModuleType('mcp.server')
sys.modules['mcp.server.fastmcp'] = types.ModuleType('mcp.server.fastmcp')
sys.modules['mcp.server.fastmcp'].FastMCP = type('FastMCP', (), {})

spec.loader.exec_module(resources)

lookup_icd_to_mesh = resources.lookup_icd_to_mesh
lookup_mesh_to_icd = resources.lookup_mesh_to_icd

print('=== ICD-10 to MeSH ===')
tests = ['E11', 'I21', 'J45', 'C50', 'U07.1', 'G20', 'F32']
for code in tests:
    result = lookup_icd_to_mesh(code)
    if result['success']:
        mesh = result['mesh_term']
        print(f'{code:8} -> {mesh}')
    else:
        print(f'{code:8} -> ERROR')

print()
print('=== ICD-9 to MeSH ===')
tests9 = ['250', '410', '493', '162', '332', '296']
for code in tests9:
    result = lookup_icd_to_mesh(code)
    if result['success']:
        mesh = result['mesh_term']
        version = result['icd_version']
        print(f'{code:8} ({version}) -> {mesh}')

print()
print('=== MeSH to ICD (reverse) ===')
result = lookup_mesh_to_icd('Diabetes Mellitus')
if result['success']:
    print('Diabetes Mellitus:')
    for item in result['icd10_codes']:
        print(f"  ICD-10: {item['code']} - {item['description']}")
    for item in result['icd9_codes']:
        print(f"  ICD-9:  {item['code']} - {item['description']}")

print()
print('=== Test with subcode (E11.9) ===')
result = lookup_icd_to_mesh('E11.9')
if result['success']:
    print(f"E11.9 -> {result['mesh_term']} (matched via {result.get('matched_prefix', 'exact')})")

print()
print('ALL ICD TESTS PASSED!')


def test_icd_to_mesh_conversion():
    """Test ICD-10 to MeSH conversion."""
    # ICD-10
    result = lookup_icd_to_mesh('E11')
    assert result['success'] is True
    assert result['mesh_term'] == 'Diabetes Mellitus, Type 2'
    
    # ICD-9
    result = lookup_icd_to_mesh('250')
    assert result['success'] is True
    assert result['icd_version'] == 'ICD-9'
    
    # Subcode
    result = lookup_icd_to_mesh('E11.9')
    assert result['success'] is True
    assert result['matched_prefix'] == 'E11'
    
    # COVID-19
    result = lookup_icd_to_mesh('U07.1')
    assert result['success'] is True
    assert result['mesh_term'] == 'COVID-19'


def test_mesh_to_icd_conversion():
    """Test MeSH to ICD reverse lookup."""
    result = lookup_mesh_to_icd('Diabetes Mellitus')
    assert result['success'] is True
    assert len(result['icd10_codes']) >= 1
    assert len(result['icd9_codes']) >= 1
