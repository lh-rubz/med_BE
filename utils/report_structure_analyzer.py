"""
Report Structure Analyzer - Identifies report layout, language, and table structure
to enable structure-specific prompt optimization.
"""
import json
from typing import Dict, List, Optional, Any


class ReportStructureAnalyzer:
    """Analyzes medical report images to determine their structure and layout."""
    
    # Predefined report structure patterns
    STRUCTURE_PATTERNS = {
        "standard_ltr_4col": {
            "name": "Standard LTR 4-Column",
            "description": "Left-to-right, 4 columns: Test | Value | Unit | Range",
            "column_count": 4,
            "direction": "ltr",
            "language": "English",
            "column_order": ["test_name", "field_value", "field_unit", "normal_range"],
            "confidence_boost": 0.2
        },
        "standard_rtl_4col": {
            "name": "Standard RTL 4-Column",
            "description": "Right-to-left, 4 columns: Range | Unit | Value | Test",
            "column_count": 4,
            "direction": "rtl",
            "language": "Arabic",
            "column_order": ["normal_range", "field_unit", "field_value", "test_name"],
            "confidence_boost": 0.2
        },
        "bilingual_ltr_5col": {
            "name": "Bilingual LTR 5-Column",
            "description": "English/Arabic, 5 columns: Category | Test | Value | Unit | Range",
            "column_count": 5,
            "direction": "ltr",
            "language": "Bilingual",
            "column_order": ["category", "test_name", "field_value", "field_unit", "normal_range"],
            "confidence_boost": 0.15
        },
        "compact_ltr_3col": {
            "name": "Compact LTR 3-Column",
            "description": "Left-to-right, 3 columns: Test | Value | Unit (no range)",
            "column_count": 3,
            "direction": "ltr",
            "language": "English",
            "column_order": ["test_name", "field_value", "field_unit"],
            "confidence_boost": 0.1
        },
        "detailed_ltr_6col": {
            "name": "Detailed LTR 6-Column",
            "description": "Left-to-right, 6 columns: Category | Test | Value | Unit | Range | Status",
            "column_count": 6,
            "direction": "ltr",
            "language": "English",
            "column_order": ["category", "test_name", "field_value", "field_unit", "normal_range", "status"],
            "confidence_boost": 0.15
        }
    }
    
    @staticmethod
    def analyze_structure(ocr_text: str) -> Dict[str, Any]:
        """
        Analyze OCR text to determine report structure.
        Returns structure type and confidence score.
        """
        analysis = {
            "structure_type": "standard_ltr_4col",  # Default fallback
            "confidence": 0.5,
            "language_primary": "English",
            "direction": "ltr",
            "column_count": 4,
            "patterns_detected": [],
            "recommendations": []
        }
        
        if not ocr_text or len(ocr_text) < 50:
            return analysis  # Fallback for minimal text
        
        text_lower = ocr_text.lower()
        
        # Detect language
        arabic_indicators = ["اختبار", "النتيجة", "الوحدة", "المعدل", "تقرير", "المجال"]
        english_indicators = ["test", "result", "value", "unit", "range", "normal", "report"]
        
        arabic_matches = sum(1 for indicator in arabic_indicators if indicator in text_lower)
        english_matches = sum(1 for indicator in english_indicators if indicator in text_lower)
        
        if arabic_matches > english_matches:
            analysis["language_primary"] = "Arabic"
            analysis["direction"] = "rtl"
        else:
            analysis["language_primary"] = "English"
            analysis["direction"] = "ltr"
        
        # Detect table structure by counting common headers
        headers_4col = ["test", "result", "value", "unit", "range", "normal"]
        headers_5col = ["category", "section", "test", "result", "unit", "range"]
        headers_6col = ["category", "test", "result", "unit", "range", "status", "flag"]
        
        count_4col = sum(1 for h in headers_4col if h in text_lower)
        count_5col = sum(1 for h in headers_5col if h in text_lower)
        count_6col = sum(1 for h in headers_6col if h in text_lower)
        
        # Detect column count
        if count_6col >= 4:
            analysis["structure_type"] = "detailed_ltr_6col"
            analysis["column_count"] = 6
            analysis["confidence"] = 0.85
        elif count_5col >= 3:
            analysis["structure_type"] = "bilingual_ltr_5col"
            analysis["column_count"] = 5
            analysis["confidence"] = 0.75
        elif count_4col >= 2:
            if analysis["direction"] == "rtl":
                analysis["structure_type"] = "standard_rtl_4col"
            else:
                analysis["structure_type"] = "standard_ltr_4col"
            analysis["column_count"] = 4
            analysis["confidence"] = 0.8
        else:
            analysis["structure_type"] = "compact_ltr_3col"
            analysis["column_count"] = 3
            analysis["confidence"] = 0.6
        
        analysis["patterns_detected"] = [
            f"Language: {analysis['language_primary']}",
            f"Direction: {analysis['direction'].upper()}",
            f"Columns: {analysis['column_count']}",
            f"Structure: {ReportStructureAnalyzer.STRUCTURE_PATTERNS[analysis['structure_type']]['name']}"
        ]
        
        return analysis
    
    @staticmethod
    def get_structure_pattern(structure_type: str) -> Dict[str, Any]:
        """Get the detailed pattern for a structure type."""
        return ReportStructureAnalyzer.STRUCTURE_PATTERNS.get(
            structure_type,
            ReportStructureAnalyzer.STRUCTURE_PATTERNS["standard_ltr_4col"]
        )


class StructureAwarePromptGenerator:
    """Generates optimized extraction prompts based on report structure."""
    
    @staticmethod
    def generate_extraction_prompt(
        structure_type: str,
        idx: int,
        total_pages: int,
        report_types: List[str]
    ) -> str:
        """Generate structure-specific extraction prompt."""
        
        pattern = ReportStructureAnalyzer.get_structure_pattern(structure_type)
        
        # Base instruction
        base_prompt = f"""Extract EVERY test result from this medical report image (page {idx}/{total_pages}).

CRITICAL: Extract ALL tests with values. Return only exact values as shown - take values as they are.
- If a field is empty in the report, return empty string ""
- If normal range is missing, that's OK - return ""
- Only include fields that have at least a test_name and field_value
- Delete/skip any row with empty field_name or field_value

Report Structure: {pattern['name']}
Expected Layout: {pattern['description']}
Direction: {pattern['direction'].upper()}
Columns: {pattern['column_count']}
"""
        
        # Structure-specific column mapping
        column_instructions = ReportStructureAnalyzer._get_column_instructions(pattern)
        
        # Extraction rules
        extraction_rules = f"""
EXTRACTION RULES - Take values EXACTLY as shown in the report:
1. field_name: EXACT test name (no modifications)
   - Example: "Haemoglobin" stays "Haemoglobin", not "Hemoglobin"
   - Preserve original text from report

2. field_value: EXACT result value including any operators
   - If shows "< 5.7", capture "< 5.7"
   - If shows "> 6.5", capture "> 6.5"
   - If shows "<= 100", capture "<= 100"
   - If empty or blank, return ""
   - Preserve decimals exactly (14.5 not 14.50)

3. field_unit: EXACT unit abbreviation
   - Examples: "g/dL", "mg/dL", "K/uL", "cells/L"
   - If no unit shown, return ""
   - Do NOT include values with units - just the unit

4. normal_range: EXACT range from the SAME ROW
   - If shows "(10-15)", capture "(10-15)"
   - If shows "Normal: <5.7 | High: >5.7", capture exactly as shown
   - If multiple categories shown, preserve all separators
   - If blank or missing, return "" - DO NOT invent ranges
   - Do NOT include units in range

5. category: Section header (e.g., "HAEMATOLOGY", "BIOCHEMISTRY")
   - If no category/section, return ""

6. notes: Any flags visible (e.g., "High", "Low", "Critical")
   - If empty, return ""

VALIDATION BEFORE RETURNING:
- Only include entries with non-empty field_name AND field_value
- Skip any row with empty field_name or field_value
- If normal_range is empty, that's OK - keep it empty
- Preserve exact original text from report
"""
        
        # JSON template
        json_template = f"""
RETURN ONLY VALID JSON (no markdown):
{{
    "patient_name": "",
    "patient_age": "",
    "patient_gender": "",
    "report_date": "YYYY-MM-DD",
    "report_name": "",
    "report_type": "",
    "doctor_names": "",
    "total_fields_in_image": 0,
    "medical_data": [
        {{
            "field_name": "",
            "field_value": "",
            "field_unit": "",
            "normal_range": "",
            "category": "",
            "notes": ""
        }}
    ]
}}
"""
        
        return base_prompt + column_instructions + extraction_rules + json_template
    
    @staticmethod
    def _get_column_instructions(pattern: Dict[str, Any]) -> str:
        """Generate column-specific instructions based on structure pattern."""
        
        direction = pattern['direction']
        columns = pattern['column_order']
        
        if direction == "ltr":
            reading_order = "Left to Right (LTR)"
        else:
            reading_order = "Right to Left (RTL)"
        
        instructions = f"\nREAD TABLE {reading_order}:\n"
        
        for i, col in enumerate(columns, 1):
            col_name = col.replace('_', ' ').title()
            instructions += f"{i}. Column {i}: {col_name}\n"
        
        instructions += f"\nREAD EACH ROW INDEPENDENTLY:\n"
        instructions += "- Trace horizontally across ONE row at a time\n"
        instructions += "- Do NOT mix values from different rows\n"
        instructions += "- Do NOT look above or below the current row\n"
        instructions += "- If a cell is empty, return empty string for that field\n"
        
        return instructions
    
    @staticmethod
    def generate_structure_analysis_prompt() -> str:
        """Generate prompt to analyze report structure (Phase 1)."""
        
        return """Analyze this medical report image and return ONLY this JSON structure:

{
    "report_structure": {
        "primary_language": "English|Arabic|Bilingual",
        "reading_direction": "LTR|RTL",
        "table_column_count": 3|4|5|6,
        "visible_headers": ["header1", "header2", ...],
        "has_categories": true|false,
        "has_ranges": true|false,
        "estimated_row_count": number
    },
    "confidence": 0.0-1.0,
    "notes": "brief observations"
}"""


# Registry of structure-specific optimizations
STRUCTURE_OPTIMIZATIONS = {
    "standard_ltr_4col": {
        "prompt_generator": "generate_extraction_prompt",
        "row_alignment_critical": True,
        "range_handling": "exact_from_column",
        "value_validation": "strict"
    },
    "standard_rtl_4col": {
        "prompt_generator": "generate_extraction_prompt",
        "row_alignment_critical": True,
        "range_handling": "exact_from_column_rtl",
        "value_validation": "strict"
    },
    "bilingual_ltr_5col": {
        "prompt_generator": "generate_extraction_prompt",
        "row_alignment_critical": True,
        "range_handling": "exact_from_column",
        "value_validation": "medium"
    },
    "compact_ltr_3col": {
        "prompt_generator": "generate_extraction_prompt",
        "row_alignment_critical": True,
        "range_handling": "optional",
        "value_validation": "medium"
    },
    "detailed_ltr_6col": {
        "prompt_generator": "generate_extraction_prompt",
        "row_alignment_critical": True,
        "range_handling": "exact_from_column",
        "value_validation": "strict"
    }
}
