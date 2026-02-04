"""
Strict row-by-row table extraction prompt for medical reports.
Enforces spatial alignment and careful sequential reading.
"""


def get_strict_table_extraction_prompt(idx: int, total_pages: int) -> str:
    """Generate a strict table extraction prompt that enforces row-by-row alignment."""
    return f"""
🔬 EXTRACT MEDICAL TABLE DATA - RTL & LTR AWARE
Page {idx}/{total_pages}

CRITICAL: This may be a RIGHT-TO-LEFT (RTL) or LEFT-TO-RIGHT (LTR) table.

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

STEP 3 - EXTRACT ROW-BY-ROW:
Start from TOP row, go DOWN. For EACH row:
1. Find test name position
2. Move HORIZONTALLY in SAME ROW to find value
3. Stay in SAME ROW to find unit and range
4. DO NOT jump to different rows

EXAMPLE - RTL Table (Arabic report):
```
ملاحظات | الوحدة | النتيجة الطبيعية | النتيجة | الفحص
         | mg/dl  | (74-110)        | 109    | Fasting Blood Sugar (FBS)
    *    | mg/dl  | (0.5-0.9)       | 0.56   | Creatinine,serum
    *    | mg/dl  | (0-200)         | 230    | Cholesterol,Total
         | U/L    | (0-33)          | 32     | Alanine transaminase ALT (GPT)
```
Extract as:
- Row 1: field_name="Fasting Blood Sugar", field_value="109", field_unit="mg/dl", normal_range="(74-110)"
- Row 2: field_name="Creatinine serum", field_value="0.56", field_unit="mg/dl", normal_range="(0.5-0.9)", notes="marked_abnormal"
- Row 3: field_name="Total Cholesterol", field_value="230", field_unit="mg/dl", normal_range="(0-200)", notes="marked_abnormal"
- Row 4: field_name="Alanine aminotransferase ALT", field_value="32", field_unit="U/L", normal_range="(0-33)"

VALIDATION RULES:
✓ Value must be in SAME horizontal row as test name
✓ If you see a * or flag → add notes="marked_abnormal"
✓ Translate Arabic test names to English
✓ Extract EVERY row in order top-to-bottom
✗ DO NOT take a value from row above or below
✗ DO NOT skip rows
✗ DO NOT reorder rows

COMMON RTL MISTAKES TO AVOID:
❌ Reading "Cholesterol" row but taking "Creatinine" value (wrong row!)
❌ Reading left-to-right when table is right-to-left
❌ Confusing column positions in RTL layout

RETURN JSON:
{{
    "patient_name": "from header",
    "patient_age": "number",
    "patient_gender": "Male or Female",
    "report_date": "YYYY-MM-DD",
    "report_name": "test type",
    "report_type": "Clinical Chemistry / Hematology / etc",
    "doctor_names": "from signature",
    "medical_data": [
        {{
            "field_name": "English test name",
            "field_value": "number from SAME row as test name",
            "field_unit": "unit from SAME row",
            "normal_range": "(X-Y) from SAME row",
            "category": "section name",
            "notes": "marked_abnormal or empty"
        }}
    ]
}}

EXTRACT NOW - Identify RTL/LTR first, then extract row-by-row carefully.
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
- For each misaligned row: "Row #N (field_name): MISALIGNED - image shows value [X] in that row"
- Summary: "Total table rows: X, Extracted rows: Y"
- If rows are less: "Missing rows - which ones?"
- If rows are more: "Over-extracted - duplicates or hallucinations?"
- Overall: "Status: ALIGNED" or "Status: NEEDS_CORRECTION"

If status is NEEDS_CORRECTION, provide:
- List of values that need to be corrected
- Show what the correct value should be from the image
"""
