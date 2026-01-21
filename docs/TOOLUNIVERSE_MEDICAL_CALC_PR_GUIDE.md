# ToolUniverse PR Guide: medical-calc-mcp

This guide provides step-by-step instructions for submitting `medical-calc-mcp` to ToolUniverse.

## 📋 Overview

**Project**: medical-calc-mcp  
**Tools Count**: 121 medical calculators  
**Target**: ToolUniverse PR (like PR #40)

## 🔧 Step 1: Fork ToolUniverse

```bash
# 1. Fork mims-harvard/ToolUniverse on GitHub
# 2. Clone your fork
git clone https://github.com/u9401066/ToolUniverse.git
cd ToolUniverse
git remote add upstream https://github.com/mims-harvard/ToolUniverse.git
```

## 📁 Step 2: File Structure

Based on ToolUniverse's tool_implementation_guide.md:

```
src/tooluniverse/
├── medical_calc_tool.py           # Main tool class (BaseTool)
├── data/
│   └── medical_calc_tools.json    # Tool configurations (121 tools)
└── tools/
    └── (auto-generated)           # Don't manually create

tests/
└── tools/
    └── test_medical_calc_tool.py  # Test suite
```

## 📝 Step 3: Create Tool Class

**File**: `src/tooluniverse/medical_calc_tool.py`

```python
"""Medical Calculator Tool for ToolUniverse."""
from typing import Dict, Any
from .base_tool import BaseTool
from .tool_registry import register_tool


@register_tool("MedicalCalculatorTool")
class MedicalCalculatorTool(BaseTool):
    """
    Validated medical calculators for AI agents.
    
    Provides 121 peer-reviewed medical calculators including:
    - Critical Care: SOFA, APACHE II, qSOFA, NEWS2
    - Cardiology: CHA₂DS₂-VASc, HEART, GRACE
    - Nephrology: CKD-EPI 2021, KDIGO AKI
    - Pulmonology: CURB-65, PSI/PORT, ROX Index
    - Hepatology: MELD, Child-Pugh, FIB-4
    - And more...
    
    All calculators cite original peer-reviewed research (PMID).
    """
    
    def __init__(self, tool_config: Dict[str, Any]):
        super().__init__(tool_config)
        self._tool_id = tool_config.get("tool_id", "")
        
    def run(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute medical calculation."""
        # Import calculation logic from medical-calc-mcp
        from medical_calc_mcp import calculate
        
        try:
            result = calculate(self._tool_id, arguments)
            return {
                "success": True,
                "calculator": self._tool_id,
                "result": result
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
```

## 📊 Step 4: Create JSON Configuration

**File**: `src/tooluniverse/data/medical_calc_tools.json`

```json
[
  {
    "name": "medical_calc_sofa_score",
    "type": "MedicalCalculatorTool",
    "tool_id": "sofa",
    "description": "SOFA Score (Sequential Organ Failure Assessment) - Predicts ICU mortality based on organ dysfunction (Sepsis-3 criteria). Reference: Vincent 1996, Singer 2016",
    "parameter": {
      "type": "object",
      "properties": {
        "pao2_fio2_ratio": {
          "type": "number",
          "description": "PaO2/FiO2 ratio (mmHg)"
        },
        "platelets": {
          "type": "number",
          "description": "Platelet count (×10³/μL)"
        },
        "bilirubin": {
          "type": "number",
          "description": "Bilirubin (mg/dL)"
        },
        "cardiovascular": {
          "type": "string",
          "enum": ["no_hypotension", "map_lt_70", "dopamine_lte_5", "dopamine_gt_5", "epi_norepi_any"],
          "description": "Cardiovascular status"
        },
        "gcs_score": {
          "type": "integer",
          "description": "Glasgow Coma Scale (3-15)"
        },
        "creatinine": {
          "type": "number",
          "description": "Creatinine (mg/dL)"
        }
      },
      "required": ["pao2_fio2_ratio", "platelets", "bilirubin", "cardiovascular", "gcs_score", "creatinine"]
    },
    "return_schema": {
      "type": "object",
      "properties": {
        "success": {"type": "boolean"},
        "calculator": {"type": "string"},
        "result": {
          "type": "object",
          "properties": {
            "score_name": {"type": "string"},
            "value": {"type": "number"},
            "interpretation": {"type": "object"}
          }
        }
      }
    },
    "test_examples": [
      {
        "arguments": {
          "pao2_fio2_ratio": 300,
          "platelets": 150,
          "bilirubin": 1.0,
          "cardiovascular": "no_hypotension",
          "gcs_score": 15,
          "creatinine": 1.0
        }
      }
    ]
  }
]
```

## ✅ Step 5: Create Tests

**File**: `tests/tools/test_medical_calc_tool.py`

```python
"""Tests for Medical Calculator Tool."""
import pytest
from tooluniverse import ToolUniverse


class TestMedicalCalculatorTool:
    """Test medical calculator tools."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        self.tu = ToolUniverse()
        self.tu.load_tools()
    
    def test_sofa_score(self):
        """Test SOFA score calculation."""
        result = self.tu.run({
            "name": "medical_calc_sofa_score",
            "arguments": {
                "pao2_fio2_ratio": 300,
                "platelets": 150,
                "bilirubin": 1.0,
                "cardiovascular": "no_hypotension",
                "gcs_score": 15,
                "creatinine": 1.0
            }
        })
        assert result["success"] is True
        assert "result" in result
    
    def test_ckd_epi(self):
        """Test CKD-EPI 2021 calculation."""
        result = self.tu.run({
            "name": "medical_calc_ckd_epi_2021",
            "arguments": {
                "serum_creatinine": 1.2,
                "age": 65,
                "sex": "female"
            }
        })
        assert result["success"] is True
```

## 📤 Step 6: Submit PR

```bash
# 1. Create branch
git checkout -b feat/medical-calc-tools

# 2. Add files
git add src/tooluniverse/medical_calc_tool.py
git add src/tooluniverse/data/medical_calc_tools.json
git add tests/tools/test_medical_calc_tool.py

# 3. Commit
git commit -m "feat: Add Medical Calculator MCP Tools (121 calculators)"

# 4. Push
git push origin feat/medical-calc-tools

# 5. Create PR on GitHub
```

## 📋 PR Template

```markdown
## Summary

This PR adds comprehensive medical calculator integration with 121 validated tools
for clinical scoring and risk assessment.

## Features

• **121 Calculator Tools**: Complete coverage of medical specialties
  - Critical Care: SOFA, APACHE II, qSOFA, NEWS2, CAM-ICU, RASS
  - Cardiology: CHA₂DS₂-VASc, HEART, GRACE, ACEF II
  - Nephrology: CKD-EPI 2021, KDIGO AKI
  - Pulmonology: CURB-65, PSI/PORT, ROX Index, sPESI
  - Hepatology: MELD, Child-Pugh, FIB-4, Glasgow-Blatchford
  - Neurology: NIHSS, ABCD2, Hunt & Hess, Fisher Grade
  - And 95+ more...

• **Evidence-Based**: All calculators cite peer-reviewed research (PMID)
• **Validated Formulas**: Deterministic calculation, no hallucination risk
• **Comprehensive Test Suite**: 1540+ tests

## Technical Implementation

- Tool Class: `MedicalCalculatorTool` (inherits BaseTool)
- JSON Config: `medical_calc_tools.json`
- Tests: Comprehensive pytest suite

## Checklist

- [x] All 121 tools implemented and tested
- [x] JSON configuration complete
- [x] Test suite passing
- [x] Documentation complete
- [x] Code follows ToolUniverse standards
```

## 🔗 References

- **medical-calc-mcp**: https://github.com/u9401066/medical-calc-mcp
- **ToolUniverse Guide**: https://zitniklab.hms.harvard.edu/ToolUniverse/expand_tooluniverse/comprehensive_tool_guide.html
- **PR #40 Example**: https://github.com/mims-harvard/ToolUniverse/pull/40
