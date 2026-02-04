"""
Strict row-by-row table extraction prompt for medical reports.
Enforces spatial alignment and careful sequential reading.
"""


def get_strict_table_extraction_prompt(idx: int, total_pages: int) -> str:
    """Generate a strict table extraction prompt that enforces row-by-row alignment."""
    return f"""
🔬 MEDICAL TABLE EXTRACTION - STRICT ROW-BY-ROW MODE
Page {idx}/{total_pages}

YOUR TASK: Extract EVERY test result from the medical table(s) on this page.
Each row in the table contains ONE test result with multiple columns.

⚠️ CRITICAL RULES - DO NOT VIOLATE:

1️⃣ READ TABLES ROW-BY-ROW FROM TOP TO BOTTOM:
   - Start at the FIRST data row (after headers)
   - Move DOWN one row at a time
   - DO NOT skip rows
   - DO NOT read out of order
   - DO NOT rearrange values from different rows

2️⃣ FOR EACH ROW, IDENTIFY THE 4 COLUMNS:
   Column A: Test Name/Parameter name (left or right, depends on table orientation)
   Column B: Measured Value (the number/result)
   Column C: Unit of Measurement (mg/dl, %, U/L, etc.)
   Column D: Normal/Reference Range ((X-Y) format)

3️⃣ SPATIAL ALIGNMENT - CRITICAL:
   - The VALUE must be physically in the SAME ROW as the TEST NAME in the image
   - If value is in a different row than the test name → THAT IS MISALIGNMENT
   - Do NOT take a value from above or below the test name row
   - Verify each value is aligned horizontally with its test name

4️⃣ MARKED/ABNORMAL VALUES:
   - If a value is marked with * or ^ or has a flag → KEEP the value exactly, add note "marked_abnormal"
   - Example: If you see "* 230" → extract "230" with notes "marked_abnormal"
   - Do NOT remove the value or the marker

5️⃣ HANDLE ARABIC TEXT:
   - If test name is in Arabic, translate it to English
   - Examples:
     - "صوديوم" → "Sodium"
     - "بوتاسيوم" → "Potassium"
     - "الجلوكوز" → "Glucose"
     - "كرات الدم البيضاء" → "White Blood Cells"

6️⃣ COLUMN SEPARATION - VALIDATE:
   Before extracting, verify:
   - [ ] Test Name: looks like a medical test → NOT a number, NOT a range, NOT a unit
   - [ ] Value: is a number (possibly with %) → NOT a test name, NOT a range description
   - [ ] Unit: is a unit symbol (mg/dl, %, U/L, etc.) → NOT a number, NOT a range
   - [ ] Range: is (X-Y) or X-Y format → NOT a single number, NOT a unit
   If ANY check fails, you have column misalignment → DO NOT extract that row

7️⃣ EMPTY/MISSING VALUES:
   - If a cell shows "-" or "(-)" or is blank → write "" (empty string)
   - If a cell shows "*" alone → write "" 
   - DO NOT invent values

8️⃣ TABLE LAYOUT VARIANTS:
   This report may have:
   - Horizontal tables (columns left-to-right)
   - Vertical tables (columns top-to-bottom)
   - Mixed Arabic/English text
   - Multiple separate table sections
   - Rows with sub-rows or merged cells
   Use spatial position to determine which value belongs to which test.

📋 EXTRACTION PROCESS:

Step 1: Identify all table sections on the page
Step 2: For EACH table section:
   - Locate the header row
   - Number the data rows (1st, 2nd, 3rd, etc.)
Step 3: For EACH data row (top to bottom):
   - Find test name position
   - Find value position in SAME row
   - Find unit position in SAME row  
   - Find range position in SAME row
   - Verify spatial alignment before extraction
Step 4: Extract ONLY rows with both test name AND value

🚨 COMMON MISTAKES TO AVOID:
   ❌ Reading value from row below the test name
   ❌ Reading value from row above the test name
   ❌ Merging two different rows' data
   ❌ Taking range as the value
   ❌ Taking unit as the value
   ❌ Extracting values without test names
   ❌ Reading in wrong order (not top to bottom)

✅ CORRECT EXAMPLE:
   Image row: "Glucose | 95 | mg/dl | (70-100)"
   Extract:
   {{
     "field_name": "Glucose",
     "field_value": "95",
     "field_unit": "mg/dl",
     "normal_range": "(70-100)"
   }}

✅ CORRECT EXAMPLE (RTL/Arabic):
   Image row: "السكر الصائم | 109 | mg/dl | (74-110)"
   Extract:
   {{
     "field_name": "Fasting Blood Sugar",
     "field_value": "109",
     "field_unit": "mg/dl",
     "normal_range": "(74-110)"
   }}

✅ CORRECT EXAMPLE (Marked abnormal):
   Image row: "الكوليسترول | * 230 | mg/dl | (0-200)"
   Extract:
   {{
     "field_name": "Total Cholesterol",
     "field_value": "230",
     "field_unit": "mg/dl",
     "normal_range": "(0-200)",
     "notes": "marked_abnormal"
   }}

EXTRACTION CHECKLIST FOR EACH ROW:
   Before submitting a row, verify:
   [✓] Test name is present and is a medical test
   [✓] Value is present and is numeric or "-" or empty
   [✓] Value is in the SAME row as test name (spatial alignment verified)
   [✓] Unit is in the SAME row
   [✓] Range is in the SAME row
   [✓] No column shifting detected
   [✓] Reading in order from top to bottom

JSON OUTPUT FORMAT (exactly this structure, no variations):
{{
    "patient_name": "name from report header",
    "patient_age": "age number only",
    "patient_gender": "Male or Female",
    "report_date": "YYYY-MM-DD format",
    "report_name": "extract from header",
    "report_type": "Clinical Chemistry / Hematology / etc",
    "doctor_names": "name from signature or header",
    "medical_data": [
        {{
            "field_name": "Test name (English, translated if Arabic)",
            "field_value": "numeric value or empty string",
            "field_unit": "unit symbol or empty string",
            "normal_range": "(X-Y) or empty string",
            "category": "section name (Clinical Chemistry, Hematology, etc)",
            "notes": "marked_abnormal or empty"
        }}
    ]
}}

FINAL VALIDATION:
- medical_data should contain EVERY row with both test name AND value
- NO missing rows (count table rows in image and match in output)
- NO reordered rows (must be top to bottom)
- Values must exactly match image
- Column alignment must be verified for each row

BEGIN EXTRACTION NOW - Remember: ROW-BY-ROW, SAME ROW, TOP-TO-BOTTOM, SPATIAL ALIGNMENT VERIFIED FOR EACH ROW.
"""


def get_alignment_verification_prompt(extracted_data: dict, page_num: int) -> str:
    """
    Generate a verification prompt that rechecks table alignment.
    Used after initial extraction to catch misaligned rows.
    """
    fields_text = "\n".join([
        f"{idx+1}. {f.get('field_name', '???')} = {f.get('field_value', '')} {f.get('field_unit', '')}"
        for idx, f in enumerate(extracted_data.get('medical_data', [])[:30])
    ])

    return f"""
🔍 ALIGNMENT VERIFICATION - PAGE {page_num}

Your extracted data:
{fields_text}

VERIFICATION TASK:
For EACH extracted row, verify in the image:
1. Find the test name in the image
2. Is the value physically in the SAME ROW as that test name?
   - YES ✓ → Mark as ALIGNED
   - NO ✗ → Mark as MISALIGNED, describe what value is actually in that row
3. Count total rows in the table image
4. Count total rows you extracted
5. If counts don't match → rows are missing or reordered

RESPOND WITH:
- For each misaligned row: "Row #N ({field_name}): MISALIGNED - image shows value [X] in that row"
- Summary: "Total table rows: X, Extracted rows: Y"
- If Y < X: "Missing {X-Y} rows - which ones?"
- If Y > X: "Over-extracted - duplicates or hallucinations?"
- Overall: "Status: ALIGNED" or "Status: NEEDS_CORRECTION"

If status is NEEDS_CORRECTION, provide:
- List of values that need to be corrected
- Show what the correct value should be from the image
"""
