"""Page-specific VLM prompts with enhanced validation and error prevention."""

def get_hematology_focused_prompt(idx, total_pages):
    """
    Specialized prompt for Hematology/CBC tables with no hardcoded values.
    Focus on extraction directly from the image, line-by-line verification.
    """
    return f"""🚨 HEMATOLOGY TABLE EXTRACTION - STRICT IMAGE-ONLY MODE 🚨
Page {idx}/{total_pages}

CRITICAL INSTRUCTION: Extract ONLY what you see in the image. Do NOT invent or assume any values.

YOU ARE EXTRACTING A HEMATOLOGY/COMPLETE BLOOD COUNT (CBC) TABLE.
The table has columns arranged left-to-right (or right-to-left for Arabic):
  Column 1: Test/Parameter Name (e.g., "RBC", "Hemoglobin", "WBC", "Lymphocytes%")
  Column 2: Test Result/Value (a number, percentage, or count visible in image)
  Column 3: Unit of Measurement (e.g., "K/uL", "g/dL", "%", "M/uL")
  Column 4: Reference Range (e.g., "(4.5-11)" or "(4-6)" - shown in image)

🔴 EXTRACTION RULES - FOLLOW EXACTLY:

1. **READ EVERY ROW FROM THE IMAGE ITSELF**:
   - Start at the TOP of the table and scan downward
   - For EACH visible row in the table:
     a) Look at Column 1: What is the test name shown in the image?
     b) Look at Column 2: What value/result is shown in the image for this test?
     c) Look at Column 3: What unit is shown in the image for this test?
     d) Look at Column 4: What reference range is shown in the image?
   - Write down EXACTLY what you see - no modifications, no assumptions

2. **CRITICAL - EMPTY VALUE DETECTION**:
   - If Column 2 (Value) shows: * (star), - (dash), — (line), or is blank/empty
     → This test has NO RESULT
     → DO NOT EXTRACT THIS ROW
     → Skip this row completely - do not include in medical_data array
   - NEVER guess or fill in a value for empty results
   - NEVER copy a value from the row above or below
   - If value is empty, the row is not included in output

3. **LINE-BY-LINE HORIZONTAL ALIGNMENT VERIFICATION**:
   - For EACH row you extract:
     → Draw an imaginary horizontal line across the entire row
     → Verify all 4 columns are aligned horizontally
     → Verify the value in Column 2 belongs to the test in Column 1 (same row)
     → Verify the unit in Column 3 is for the test in Column 1 (same row)
     → Verify the range in Column 4 is for the test in Column 1 (same row)
   - If misalignment detected → STOP and recheck the row alignment
   - If certain the alignment is correct → Extract the row

4. **HANDLE PERCENTAGE TESTS CORRECTLY**:
   - Some tests have "%" in their name (e.g., "Lymphocytes%", "Neutrophils%", "Monocytes%")
   - These tests show percentage values (e.g., 57.8, 41.1, 0.1, 1.1)
   - The "%" in the test name does NOT mean the result is empty
   - The "%" is PART OF THE TEST NAME, not an empty marker
   - Extract these normally with their percentage values
   - The range might show as "(20-40)" or with % symbol - extract exactly as shown

5. **UNIT READING**:
   - Read unit EXACTLY as shown in image (e.g., "K/uL", "M/uL", "g/dL", "%", "cells/L")
   - Do NOT modify or "correct" units
   - If Column 3 is empty for a test → leave field_unit as empty string ""
   - If Column 3 shows only symbols like "*" or "-" → that means no unit, leave as ""

6. **RANGE READING**:
   - Read reference range EXACTLY as shown in image (e.g., "(4.5-11)", "(140-400)", "(20-40)")
   - Extract the parentheses and format exactly as shown
   - If the range shown in image is "(4.5-11)" → extract "(4.5-11)" exactly
   - If Column 4 is empty → leave normal_range as empty string ""
   - NEVER invent a range not visible in the image
   - NEVER use knowledge of typical ranges - use ONLY what image shows

7. **VERIFICATION CHECKLIST FOR EACH ROW**:
   Before including a row in output, verify:
   ✅ Can I see a test name in Column 1? → If NO, skip this row
   ✅ Can I see a VALUE in Column 2 that is NOT *, -, or blank? → If NO, skip this row
   ✅ Is the value in Column 2 clearly aligned horizontally with test name in Column 1? → If NO, check alignment
   ✅ Column 3 visible? → Extract unit if present, otherwise ""
   ✅ Column 4 visible? → Extract range if present, otherwise ""

8. **TABLE BOUNDARY DETECTION**:
   - Identify where the table starts (usually has column headers)
   - Scan down and extract every row with actual test data
   - Stop when you reach the end of the table (before footer or notes)
   - Do NOT include rows outside the main table structure

9. **FINAL COUNT CHECK**:
   - Count total rows extracted (should be 20-30 for a typical CBC)
   - If count < 10, you likely missed rows - go back and recheck the table
   - If count > 40, verify you didn't include header rows or duplicates

📝 JSON OUTPUT - EXTRACT FROM IMAGE ONLY:
{{
  "medical_data": [
    {{
      "field_name": "EXACTLY as shown in Column 1 of image",
      "field_value": "EXACTLY the number/value shown in Column 2 of image",
      "field_unit": "EXACTLY as shown in Column 3 of image, or empty string if not shown",
      "normal_range": "EXACTLY as shown in Column 4 of image, or empty string if not shown",
      "is_normal": null,
      "category": "Hematology",
      "notes": ""
    }},
    {{
      "field_name": "EXACTLY as shown in Column 1 of image",
      "field_value": "EXACTLY the number/value shown in Column 2 of image",
      "field_unit": "EXACTLY as shown in Column 3 of image, or empty string if not shown",
      "normal_range": "EXACTLY as shown in Column 4 of image, or empty string if not shown",
      "is_normal": null,
      "category": "Hematology",
      "notes": ""
    }}
    // Continue for EVERY row with actual values in Column 2
    // DO NOT include rows where Column 2 is *, -, blank, or empty
  ]
}}

🚨 IMPORTANT REMINDERS:
- Extract ONLY from the image - no knowledge-based assumptions
- Do NOT provide values you know should be there if image is unclear
- Each row's values must align horizontally across all 4 columns
- Empty results (*, -, blank) mean skip that entire row
- Range must match the VALUE in the same row (verify alignment)
- Unit must match the TEST NAME in the same row (verify alignment)
"""

def get_clinical_chemistry_focused_prompt(idx, total_pages):
    """
    Specialized prompt for Clinical Chemistry tables with extraction from image only.
    No hardcoded values - extract directly from what's visible.
    """
    return f"""🚨 CLINICAL CHEMISTRY TABLE EXTRACTION - STRICT IMAGE-ONLY MODE 🚨
Page {idx}/{total_pages}

CRITICAL INSTRUCTION: Extract ONLY what you see in the image. Do NOT invent or assume any values.

YOU ARE EXTRACTING A CLINICAL CHEMISTRY TABLE.
The table has columns arranged:
  Column 1: Test/Parameter Name (e.g., "Glucose", "Creatinine", "Cholesterol Total")
  Column 2: Test Result/Value (a number visible in image)
  Column 3: Unit of Measurement (e.g., "mg/dl", "mmol/L", "IU/L")
  Column 4: Reference Range (e.g., "(70-110)" - shown in image)

🔴 CRITICAL RULES - FOLLOW EXACTLY:

1. **EXTRACT FROM IMAGE ONLY - NO ASSUMPTIONS**:
   - Scan the table from top to bottom
   - For EACH visible row:
     a) Column 1: Read the test name shown in image
     b) Column 2: Read the result/value shown in image
     c) Column 3: Read the unit shown in image
     d) Column 4: Read the reference range shown in image
   - Extract EXACTLY what you see - no modifications, no knowledge-based values

2. **EMPTY VALUE RULE** (MOST IMPORTANT):
   - If Column 2 (Result/Value) shows: * (star), - (dash), — (line), or is blank/empty
     → This test has NO RESULT
     → DO NOT EXTRACT THIS ROW
     → Skip this row completely - do not include in medical_data array
   - NEVER guess a value for empty results
   - NEVER copy a value from adjacent rows
   - If there's no value in Column 2, the row is not included

3. **ROW ALIGNMENT VERIFICATION** (CRITICAL FOR ACCURACY):
   - For EACH row extracted:
     → Verify the value in Column 2 is horizontally aligned with test name in Column 1
     → Verify the unit in Column 3 is horizontally aligned with same test
     → Verify the range in Column 4 is horizontally aligned with same test
   - If columns shift or misalign → RECHECK the row
   - Ensure no values are "borrowed" from adjacent rows
   - Each row must have its own test, value, unit, and range

4. **VALUE VALIDATION**:
   - Valid values: Numbers like "109", "0.56", "230", "12.6", "128"
   - Valid values: Decimals like "74.5", "0.12", "3.8"
   - Valid values: Text results like "Normal", "Negative", "Positive" (if image shows)
   - Invalid/Skip: Symbols only like "*", "-", "—", ".", or blank
   - If Column 2 shows ONLY a symbol or is blank → skip this entire row

5. **UNIT READING**:
   - Read unit EXACTLY as shown in image (e.g., "mg/dl", "mmol/L", "mEq/L", "U/L", "IU/L", "g/dL")
   - Do NOT modify or standardize units
   - If Column 3 is empty for a test → leave field_unit as empty string ""
   - If Column 3 shows only symbols → leave field_unit as empty string ""

6. **RANGE READING**:
   - Read reference range EXACTLY as shown in image
   - If shown as "(74-110)" → extract "(74-110)"
   - If shown as "<200" → extract "<200"
   - If shown as "(0-200)" → extract "(0-200)"
   - Extract the format exactly as displayed - do NOT modify
   - If Column 4 is empty → leave normal_range as empty string ""
   - NEVER invent a range not visible in the image
   - NEVER use typical ranges from medical knowledge - use ONLY image

7. **TABLE STRUCTURE VERIFICATION**:
   - Identify table start (usually has headers: Test, Result, Unit, Reference)
   - Extract every row with actual data (Column 2 has a value)
   - Stop when table ends (before footer, notes, or other sections)
   - Do NOT include header rows or footer rows

8. **COMMON TEST NAMES IN CHEMISTRY** (Use to verify you're extracting correctly):
   - Do NOT use this list to fill in missing values
   - Use ONLY to help identify row boundaries and test names
   - Extract names exactly as shown in image, not from this list
   - Examples of test names (for reference only): Glucose, Creatinine, Cholesterol, HDL, LDL, Triglycerides, Sodium, Potassium, ALT, AST, Bilirubin, etc.

9. **VERIFICATION CHECKLIST FOR EACH ROW**:
   Before including in output:
   ✅ Can I see a test name in Column 1? → If NO, skip
   ✅ Can I see a VALUE in Column 2 that is NOT *, -, blank? → If NO, skip
   ✅ Are all 4 columns horizontally aligned? → If NO, recheck alignment
   ✅ Column 3 (Unit) visible? → Extract if present, leave "" if not
   ✅ Column 4 (Range) visible? → Extract if present, leave "" if not

📝 JSON OUTPUT - EXTRACT FROM IMAGE ONLY:
{{
  "medical_data": [
    {{
      "field_name": "EXACTLY as shown in Column 1 of image",
      "field_value": "EXACTLY the number shown in Column 2 of image",
      "field_unit": "EXACTLY as shown in Column 3 of image, or empty string if not shown",
      "normal_range": "EXACTLY as shown in Column 4 of image, or empty string if not shown",
      "is_normal": null,
      "category": "Clinical Chemistry",
      "notes": ""
    }},
    {{
      "field_name": "EXACTLY as shown in Column 1 of image",
      "field_value": "EXACTLY the number shown in Column 2 of image",
      "field_unit": "EXACTLY as shown in Column 3 of image, or empty string if not shown",
      "normal_range": "EXACTLY as shown in Column 4 of image, or empty string if not shown",
      "is_normal": null,
      "category": "Clinical Chemistry",
      "notes": ""
    }}
    // Continue for EVERY row with actual values in Column 2
    // DO NOT include rows where Column 2 is *, -, blank, or empty
  ]
}}

🚨 IMPORTANT - NO HALLUCINATION:
- Extract ONLY from image - no guessing or assumptions
- Do NOT provide values you think should be there
- Each row must have horizontal column alignment
- Empty results (*, -, blank) mean skip that row
- Range must match the value in the same row
- Unit must match the test name in the same row
- No knowledge-based values, NO ASSUMPTIONS
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

def get_direct_image_extraction_prompt():
    """
    Prompt for direct extraction from image without any prior assumptions.
    Forces VLM to read line-by-line from the visible table.
    """
    return f"""🚨 DIRECT TABLE EXTRACTION - READ FROM IMAGE LINE BY LINE 🚨

TASK: Extract a complete medical test table from the image shown.
CRITICAL: Do NOT use any knowledge, assumptions, or typical ranges.
Extract ONLY what is visible in the image.

TABLE STRUCTURE:
The table has approximately 4-5 columns:
- Column A (Right/First if Arabic): Test/Parameter Name
- Column B: Test Result/Value
- Column C: Unit
- Column D: Reference/Normal Range
- Column E (if present): Sometimes notes or flags

EXTRACTION INSTRUCTIONS:

1. **START FROM THE TOP OF THE TABLE**:
   - Identify the table headers (skip these)
   - Start reading from the first data row
   - Go line-by-line downward

2. **FOR EACH ROW IN THE TABLE**:
   
   Read left-to-right (or right-to-left if Arabic text):
   
   STEP A: Look at the test name column
   - What text do you see? Write it EXACTLY
   - Examples: "RBC", "Hemoglobin", "Glucose", "Creatinine"
   
   STEP B: Look at the result/value column (same row)
   - What number/value do you see? Write it EXACTLY
   - Examples: "4.5", "12.3", "109", "0.56"
   - If you see: * or - or blank or empty → SKIP THIS ENTIRE ROW
   - Do NOT fill in a value from another row
   
   STEP C: Look at the unit column (same row)
   - What unit symbol do you see? Write EXACTLY or leave blank
   - Examples: "M/uL", "g/dL", "mg/dl", "K/uL", "%"
   - If column is empty or has only symbols → leave blank
   
   STEP D: Look at the reference range column (same row)
   - What range do you see? Write EXACTLY or leave blank
   - Examples: "(4.5-11)", "(12-16)", "(70-110)"
   - If column is empty → leave blank
   - Do NOT invent a range

3. **COLUMN ALIGNMENT CHECK**:
   - Verify the value in Step B is HORIZONTALLY aligned with test name in Step A
   - Verify the unit in Step C is HORIZONTALLY aligned with the same test
   - Verify the range in Step D is HORIZONTALLY aligned with the same test
   - If misaligned, recheck rows above/below for correct alignment

4. **EMPTY ROW DETECTION**:
   - If the value column (Step B) shows *, -, —, or blank → DO NOT EXTRACT
   - The row has no result, so skip it entirely
   - Do NOT try to fill in a value from anywhere

5. **BOUNDARY DETECTION**:
   - Continue until you reach the last row with data
   - Stop before any footer text, notes, or signature areas
   - Do NOT include rows outside the main table

OUTPUT FORMAT - EXTRACT EVERYTHING YOU SEE:

{{
  "medical_data": [
    {{
      "field_name": "EXACTLY from Step A",
      "field_value": "EXACTLY from Step B (or skip row if empty)",
      "field_unit": "EXACTLY from Step C (or blank if not shown)",
      "normal_range": "EXACTLY from Step D (or blank if not shown)",
      "is_normal": null,
      "category": "Extracted from image",
      "notes": ""
    }},
    {{
      "field_name": "EXACTLY from Step A",
      "field_value": "EXACTLY from Step B",
      "field_unit": "EXACTLY from Step C",
      "normal_range": "EXACTLY from Step D",
      "is_normal": null,
      "category": "Extracted from image",
      "notes": ""
    }}
    // ... continue for EVERY row that has a value in Step B ...
  ],
  "extraction_notes": {{
    "total_rows_extracted": "count of items in medical_data",
    "rows_skipped_empty_value": "count of rows with * or - or blank in value column",
    "table_orientation": "left-to-right or right-to-left",
    "confidence": "high/medium/low - your confidence in accuracy"
  }}
}}

🚨 CRITICAL RULES:
- NO knowledge-based values
- NO assuming typical ranges
- NO filling empty cells from other rows
- EXTRACT ONLY WHAT IMAGE SHOWS
- VERIFY COLUMN ALIGNMENT
- SKIP EMPTY VALUE ROWS
- READ LINE BY LINE, ROW BY ROW
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
