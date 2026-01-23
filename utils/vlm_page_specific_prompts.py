"""Page-specific VLM prompts with enhanced validation and error prevention."""

def get_hematology_focused_prompt(idx, total_pages):
    """
    Specialized prompt for Hematology/CBC tables with common issues on page 2.
    This handles the second page issues where:
    - Values are misread or hallucinated
    - Ranges are incorrect or missing
    - Row alignment is critical
    """
    return f"""🚨 HEMATOLOGY TABLE EXTRACTION - STRICT MODE 🚨
Page {idx}/{total_pages}

YOU ARE EXTRACTING A HEMATOLOGY/COMPLETE BLOOD COUNT (CBC) TABLE.
This table typically has 20-30 tests with results and reference ranges.

🔴 CRITICAL RULES - FOLLOW EXACTLY:

1. **ROW INDEPENDENCE** - Each value belongs to ONLY ONE test row:
   - NEVER take a value from the row above or below
   - NEVER fill in missing values from neighboring rows
   - If a test has NO result (marked with *, blank, or dash), the value is EMPTY STRING
   
2. **EMPTY VALUE HANDLING** (THIS IS THE #1 ISSUE):
   - If a test result cell shows: * or - or blank or empty space → field_value = ""
   - DO NOT look at the next row's value and copy it
   - DO NOT guess a value
   - Return empty string "" if no value present
   - SKIP COMPLETELY if field_value would be empty - do not include in medical_data array
   
3. **RANGE/NORMAL VALUE READING**:
   - Read the normal range from the SAME ROW ONLY
   - Common Hematology ranges:
     * RBC: (4.0-5.5) or (4.2-5.4) M/uL
     * Hemoglobin: (12-16) or (11.5-15.5) g/dL for females, (13.5-17.5) for males
     * WBC: (4.5-11) or (4.5-11.0) K/uL
     * Platelets: (150-400) or (140-400) K/uL
     * Lymphocytes: Usually (20-40)% or specific count
     * Neutrophils: Usually (50-70)% or specific count
   - If the range column is empty/missing for this test, leave normal_range = ""
   - NEVER invent ranges not shown in image
   
4. **UNIT VERIFICATION**:
   - Read unit from the SAME ROW, same unit column
   - Common Hematology units: K/uL, M/uL, g/dL, %, cells/L, x10^3/uL, x10^6/uL
   - If no unit shown, leave field_unit = ""
   - Symbol-only units like "*", "-" or "—" mean the cell is empty → field_unit = ""
   
5. **VERIFICATION CHECKLIST FOR EACH ROW**:
   - Does this row have a test name? If NO → skip row
   - Does this row have a result value? If NO → skip row (don't include in output)
   - Does this row have a unit? If YES → include it, if NO → leave empty ""
   - Does this row have a range? If YES → include it, if NO → leave empty ""
   
6. **CRITICAL - Line by Line Alignment**:
   - Imagine drawing a horizontal line across ONE test row only
   - Keep your eye on that horizontal band
   - Scan left to right (or right to left if Arabic): Test Name → Value → Unit → Range
   - Do NOT cross the horizontal boundaries into adjacent rows
   - If you see misalignment (value looks like a unit, range looks like a number), STOP and recheck

7. **Percentage Tests** (VERY COMMON ON PAGE 2):
   - If test name is "Lymphocytes%", "Neutrophils%", "Monocytes%", etc.
   - These show PERCENTAGE values like "57.8", "41.1", "1.1"
   - Do NOT confuse the % symbol with empty markers
   - Range might be shown as percentage like "(20-40)" NOT "(20-40)%"
   - Examples:
     * "Lymphocytes%" = "57.8" (range might be "(20-40)" or "(20-40)%")
     * "Neutrophils%" = "41.1" (range might be "(50-70)%")
     * "Monocytes%" = "1.1" (range might be "(0-10)%" or "(2-8)%")

8. **COUNT VERIFICATION**:
   - Before returning, count your medical_data items
   - You should have 20-35 items (typical CBC = 25-30 tests)
   - If you have < 10 items, you MISSED DATA - go back and extract more

🔍 EXTRACTION PROCESS:
Starting from the first test at the top of the table:

Row 1: Extract test_name, test_value, unit, range → validate alignment
Row 2: Extract test_name, test_value, unit, range → validate alignment
Row 3: Extract test_name, test_value, unit, range → validate alignment
...continue until last visible row...

For EACH row, ask yourself:
  ✅ Can I clearly see a test name? (e.g., "WBC", "RBC", "Hemoglobin", "Lymphocytes%")
  ✅ Can I clearly see a value? (a number, percentage, or count - NOT a symbol like *)
  ✅ Is there a unit? (extract if present, "" if not)
  ✅ Is there a range? (extract if present like "(4-11)", "" if not)
  ❌ If ANY answer is NO (especially value), skip this row entirely

📝 JSON OUTPUT (MUST INCLUDE ALL VALIDATED ROWS):
{{
  "medical_data": [
    {{
      "field_name": "Test name EXACTLY from image",
      "field_value": "Numeric value or count (NOT empty) or skip row if empty",
      "field_unit": "Unit like K/uL, g/dL, % or empty string if not shown",
      "normal_range": "Range like (4-11) or (4.5-11) or empty string if not shown",
      "is_normal": null,
      "category": "Hematology" or "Complete Blood Count",
      "notes": ""
    }},
    ... more items ...
  ]
}}

🚨 VALIDATION BEFORE RETURNING:
- Every medical_data item has a non-empty field_value (values with NO result are skipped)
- Every medical_data item has a field_name (test name)
- Range format matches image (if shown)
- Units are valid medical units, not symbols
- Total items >= 20 (typical CBC has 25-30 tests)
- No items copied from adjacent rows
- No hallucinated ranges not in image
"""

def get_clinical_chemistry_focused_prompt(idx, total_pages):
    """
    Specialized prompt for Clinical Chemistry tables with validation rules.
    """
    return f"""🚨 CLINICAL CHEMISTRY TABLE EXTRACTION - STRICT MODE 🚨
Page {idx}/{total_pages}

YOU ARE EXTRACTING A CLINICAL CHEMISTRY TABLE.
This table typically has 10-25 tests (glucose, electrolytes, liver/kidney function, cholesterol, etc.)

🔴 CRITICAL RULES - FOLLOW EXACTLY:

1. **EMPTY VALUE RULE** (MOST IMPORTANT):
   - If a test result is: * (star), - (dash), blank, or empty space → DO NOT EXTRACT THAT ROW
   - A result with * or - is MISSING and should NOT appear in medical_data
   - Skip the entire row if field_value is empty
   
2. **ROW ALIGNMENT**:
   - Each row is independent - test value belongs to test name in SAME row ONLY
   - Never borrow values from adjacent rows
   - Trace horizontally across ONE row at a time
   - Verify columns don't shift between rows
   
3. **UNIT AND RANGE READING**:
   - Extract unit from same row's unit column (e.g., "mg/dl", "mmol/L", "IU/L")
   - Extract range from same row's range column (e.g., "(74-110)", "(0-200)")
   - If unit or range column is empty for that row, leave as ""
   - NEVER invent units or ranges not visible in image
   
4. **VALUE VALIDATION**:
   - Valid values: numbers like "109", "0.56", "230", "12.6", "128"
   - Valid values: text like "Normal", "Negative", "Positive" (qualitative results)
   - Invalid: symbols only like "*", "-", "—", ".", "(empty)", "N/A"
   - If value is ONLY a symbol or blank → skip this row
   
5. **COMMON CLINICAL CHEMISTRY TESTS**:
   - Glucose: (70-100) or (80-120) mg/dl
   - Creatinine: (0.6-1.2) or (0.5-0.9) mg/dl
   - Cholesterol Total: (0-200) or <200 mg/dl
   - HDL Cholesterol: (>40) or (35-80) mg/dl
   - LDL Cholesterol: (0-100) or (0-130) mg/dl
   - Triglycerides: (<150) or (0-150) mg/dl
   - Sodium: (135-145) mEq/L
   - Potassium: (3.5-5) mEq/L
   - ALT/AST: (0-33) or (0-40) U/L
   - Bilirubin: (0.1-1.2) mg/dl
   
6. **VERIFICATION CHECKLIST**:
   - ✅ Test name visible and clear
   - ✅ Value is a NUMBER or TEXT (not just a symbol)
   - ✅ Unit is present (or leave as "")
   - ✅ Range matches THIS test (verify alignment with test name)
   - ❌ If value is * or - or missing → SKIP THIS ROW
   
7. **BOUNDARY DETECTION**:
   - Identify table start and end clearly
   - Table usually has headers like: Test | Result | Unit | Reference Range
   - Stop when you reach the end of test data (don't include footer or notes)

📝 OUTPUT FORMAT:
Only include rows with actual values (skip * or - entries):
{{
  "medical_data": [
    {{
      "field_name": "Glucose",
      "field_value": "109",
      "field_unit": "mg/dl",
      "normal_range": "(74-110)",
      "is_normal": true,
      "category": "Clinical Chemistry",
      "notes": ""
    }},
    {{
      "field_name": "Creatinine, serum",
      "field_value": "0.56",
      "field_unit": "mg/dl",
      "normal_range": "(0.5-0.9)",
      "is_normal": true,
      "category": "Clinical Chemistry",
      "notes": ""
    }},
    // ... more items - ONLY those with actual values ...
  ]
}}

🚨 FINAL CHECK:
- All items have field_value (no empty values)
- All items have field_name (test name)
- Units and ranges match the image exactly
- No items from rows with * or - markers
- Total >= 10 items (typical chemistry panel)
"""

def get_page_2_specific_validation_prompt():
    """
    Post-extraction validation prompt to catch page 2 specific issues.
    Run this AFTER initial extraction to validate and correct.
    """
    return f"""🔍 PAGE 2 VALIDATION AND CORRECTION 🔍

You just extracted medical data from PAGE 2 of a report.
Now perform a STRICT VALIDATION to ensure accuracy.

VALIDATION TASKS:

1. **EMPTY VALUE CHECK**:
   Review each extracted item:
   - If field_value is in ["*", "-", "—", "", "N/A", "null"], REMOVE this item
   - These indicate missing test results, not actual values
   - Only keep items with actual numeric or text values
   
2. **RANGE VERIFICATION**:
   For each item, check the normal_range:
   - Does it match the image exactly? (e.g., "(4-11)" not "(4.0-11.0)" unless image shows decimals)
   - Is it copied from a DIFFERENT test row? (check alignment)
   - Does it look hallucinated/invented? (suspicious ranges: "(0-0.75)", "(0.1-0.5)")
   - If range doesn't match image or is from wrong row, correct or leave empty ""
   
3. **UNIT VALIDATION**:
   Check each unit:
   - Is it a valid medical unit? (K/uL, g/dL, %, cells/L, mg/dl, etc.)
   - Is it a symbol-only unit? ("*", "-", "—", "%%" alone) → set to ""
   - Does it match the test type?
     * RBC, WBC → should have /uL or cells/L, not %
     * Percentages → should have %, not /uL
   
4. **PERCENTAGE TEST CHECK**:
   For tests ending in "%":
   - field_name: "Lymphocytes%", "Neutrophils%", etc.
   - field_value: "57.8", "41.1" (NOT "57.8%") - percentage number only
   - field_unit: Leave as "" or "%" (prefer "")
   - normal_range: Likely "(20-40)" or "(20-40)%" - read from image exactly
   - These are COMMON on page 2 - verify each one
   
5. **CROSS-PAGE DUPLICATE CHECK**:
   If you extracted from multiple pages:
   - Remove exact duplicate test names with same values
   - Keep if same test appears on different pages (might be duplicate tests)
   
6. **FINAL COUNT**:
   Count remaining items after validation
   - Hematology/CBC: should have 20-30 items
   - Clinical Chemistry: should have 10-25 items
   - If too few, you may have removed too many - double-check removals
   
OUTPUT:
Return CORRECTED medical_data array with:
- All empty-value items removed
- All ranges verified against image
- All units validated
- All items with non-empty values only

{{
  "medical_data": [
    // Items with corrections applied //
  ],
  "validation_notes": {{
    "items_removed_for_empty_values": 0,
    "items_corrected_for_range": 0,
    "items_corrected_for_unit": 0,
    "items_removed_for_alignment_issues": 0
  }}
}}
"""

def get_image_comparison_prompt(expected_test_count):
    """
    Prompt for comparing extracted data with image to ensure accuracy.
    """
    return f"""🔎 IMAGE VS EXTRACTION COMPARISON 🔎

You extracted medical data. Now compare with the actual image to verify accuracy.

COMPARISON CHECKLIST:

1. **TEST COUNT**:
   - Expected ~{expected_test_count} tests in image
   - Count the tests you extracted
   - If extracted < {max(expected_test_count - 5, 10)}, you MISSED data
   
2. **VISUAL ROW-BY-ROW SCAN**:
   For FIRST test in table:
   - Test name in image matches your extracted field_name? ✓/✗
   - Value in image matches your extracted field_value? ✓/✗
   - Unit in image matches your extracted field_unit? ✓/✗
   - Range in image matches your extracted normal_range? ✓/✗
   
   For MIDDLE test (roughly row {expected_test_count//2}):
   - Same 4-point check as above
   
   For LAST test:
   - Same 4-point check as above
   
3. **COMMON ISSUES TO CHECK**:
   - Any values with "*" or "-" that you kept? → REMOVE them
   - Any ranges that look different from image? → VERIFY or CORRECT
   - Any units that don't match medical units? → CORRECT
   - Any test names truncated or modified? → CHECK against image
   
4. **ALIGNMENT VERIFICATION**:
   - For any suspicious items (value way outside range, unit seems wrong):
     * Check if value actually belongs to THIS test or different test
     * Verify no row misalignment occurred
   
5. **OUTPUT**:
   If all checks pass: Return confirmed extraction
   If issues found: Return CORRECTED data with corrections noted

{{
  "validation_status": "passed" or "corrected",
  "issues_found": ["list of issues fixed"],
  "medical_data": [ ... corrected items ... ]
}}
"""
