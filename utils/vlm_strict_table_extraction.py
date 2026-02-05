"""
Strict row-by-row table extraction prompt for medical reports.
Enforces spatial alignment and careful sequential reading.
"""


def get_strict_table_extraction_prompt(idx: int, total_pages: int) -> str:
    """Generate a strict table extraction prompt that enforces row-by-row alignment."""
    
    page_context = ""
    if total_pages > 1:
        page_context = f"""\n
⚠️  MULTI-PAGE REPORT:
This report has {total_pages} pages total. You are extracting page {idx}.
- Each page may contain DIFFERENT TEST SECTIONS (page 1 = Chemistry, page 2 = CBC/Hematology)
- Extract ALL tests from THIS page - do NOT skip them
- Do NOT skip data that appeared on a different page
- Complementary tests on different pages are normal and should all be extracted
"""
    
    return f"""
🔬 EXTRACT MEDICAL TABLE DATA - RTL & LTR AWARE
Page {idx}/{total_pages}{page_context}

CRITICAL: This may be a RIGHT-TO-LEFT (RTL) or LEFT-TO-RIGHT (LTR) table.

STEP 0 - EXTRACT HEADER INFORMATION CAREFULLY:
Look at the TOP of the page for patient information table:
- Patient Name (اسم المريض / Name)
- Patient ID (رقم المريض)
- Date of Birth (تاريخ الميلاد) - This is DOB, NOT report date!
- Report Date (تاريخ الطلب / Report Date / Sample Date) - This is the actual report date!
- Doctor Name (الطبيب)
- Gender (الجنس / Sex)

IMPORTANT DATE EXTRACTION:
- "تاريخ الميلاد" or older date (e.g., 1975) = Date of Birth (DOB) → Put in patient_age field
- "تاريخ الطلب" or "Report Date" or recent date (e.g., 2025) = Actual report date → Put in report_date field
- If you see TWO dates: The older one is likely DOB, the recent one is report date
- DO NOT confuse DOB with report date!

STEP 1 - IDENTIFY TABLE DIRECTION:
Look at the table headers and structure:
- If test names are on the RIGHT side → This is RTL (Arabic-style)
- If test names are on the LEFT side → This is LTR (English-style)

STEP 2 - IDENTIFY COLUMN POSITIONS:
For RTL tables (test names on right):
   Position 1 (RIGHTMOST): Test name (English or Arabic)
   Position 2: Result value (number)
   Position 3: Reference range (X-Y format)
   Position 4: Unit (mg/dl, %, etc)
   Position 5 (LEFTMOST): Notes (Arabic or empty)

For LTR tables (test names on left):
   Position 1 (LEFTMOST): Test name
   Position 2: Result value
   Position 3: Unit
   Position 4: Reference range
   Position 5 (RIGHTMOST): Notes

STEP 3 - EXTRACTION STRATEGY:
1. Find the test name (Fحص). Note: Names might be long and span MULTIPLE lines.
2. The result value (النتيجة) is physically in the SAME HORIZONTAL ROW as the test name's FIRST line or center.
3. Move HORIZONTALLY to find result, range, and unit.
4. DO NOT jump to different rows. If a row has no result, skip it (it might be a header).
5. DO NOT extract duplicate test names.
6. Extract EVERY single row - even those that look like sub-headers or have special codes.
7. Extract SUB-SECTIONS (e.g., under "DIFFERENTIAL COUNT", extract "Neutrophils", "Lymphocytes", etc.).
8. **UNIT PRECISION**: Extract units precisely from the unit column. 
   - Look for `%`, `K/uL`, `M/uL`, `g/dL`, `fL`, `pg`. 
   - DO NOT assume a unit. If the unit column for "Red blood cell distribution width coefficient" says "%", extract "%".
9. **LITERAL TEST NAMES**: Extract the EXACT text for the test name. If it says "Platelet Crit", DO NOT change it to "Platelet Count".
10. **EMPTY VALUE POLICY**: ONLY skip a field if the result value is physically blank in the image. If there is a name, there is almost always a value. If a value is missing, return "" (empty string).

STEP 4 - ROW-BY-ROW CHECKERBOARD SCAN:
Extract EVERY row from top to bottom. For each row:
1. **BACKGROUND COLOR**: Identify if the row has a **GRAY** or **WHITE** background.
2. **PATTERN ADHERENCE**: Rows typically alternate (Gray, White, Gray, White). If you see two whites, you likely skipped a row.
3. **HORIZONTAL BASELINE LOCK**: The Result, Range, and Unit must be exactly centered on the same color band as the Test Name.
4. **VALUE ANCHORING**: Extract values ONLY from the same color band as the test name.

EXAMPLE - Checkerboard RTL Table:
```
Background | Unit  | Range     | Value | Fحص
GRAY       | %     | (12-16)   | 14.4  | RDW-CV
WHITE      | %     | (0.1-0.5) | 0.23  | Platelet Crit
GRAY       | K/uL  | (0.1-0.8) | 0.1   | Monocytes
```

VALIDATION RULES:
✓ Value must be on the EXACT same color band as the test name
✓ Extract EXACT literal text for test names
✓ DO NOT skip a row unless it is physically blank
✓ Include background color in your mental scan to prevent 1-row shifts
✓ Translate Arabic test names to English (with original in parentheses if helpful)

RETURN JSON:
{{
    "patient_name": "actual patient name from header",
    "patient_age": "DD/MM/YYYY DOB",
    "patient_gender": "Male or Female",
    "report_date": "YYYY-MM-DD",
    "report_name": "test type from header",
    "report_type": "Clinical Chemistry / Hematology / etc",
    "doctor_names": "from header",
    "medical_data": [
        {{
            "field_name": "LITERAL test name from image",
            "field_value": "result from same color band",
            "field_unit": "unit from unit column",
            "normal_range": "(X-Y) reference range",
            "background_color": "gray or white",
            "notes": "any flags like *"
        }}
    ]
}}

EXTRACT NOW - Use the checkerboard pattern (Gray/White) to anchor every value to its test name.
"""


def get_alignment_verification_prompt(extracted_data: dict, page_num: int) -> str:
    """
    Generate a verification prompt that rechecks table alignment.
    Used after initial extraction to catch misaligned rows.
    """
    fields_text = "\\n".join([
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
- For each misaligned row: "Row #N (field_name): MISALIGNED - image shows value [X] in that row"
- Summary: "Total table rows: X, Extracted rows: Y"
- If rows are less: "Missing rows - which ones?"
- If rows are more: "Over-extracted - duplicates or hallucinations?"
- Overall: "Status: ALIGNED" or "Status: NEEDS_CORRECTION"

If status is NEEDS_CORRECTION, provide:
- List of values that need to be corrected
- Show what the correct value should be from the image
"""
