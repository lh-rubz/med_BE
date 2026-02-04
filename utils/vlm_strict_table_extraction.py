"""
Strict row-by-row table extraction prompt for medical reports.
Enforces spatial alignment and careful sequential reading.
"""


def get_strict_table_extraction_prompt(idx: int, total_pages: int) -> str:
    """Generate a strict table extraction prompt that enforces row-by-row alignment."""
    return f"""
🔬 EXTRACT MEDICAL TABLE DATA - CAREFUL LINE-BY-LINE
Page {idx}/{total_pages}

GOAL: Extract every test name and value from the table. Read line-by-line from top to bottom.

STEPS:
1. Find the data table (ignore headers)
2. For each row in the table (top to bottom):
   - Find the test name (left side usually)
   - Find the value (middle-right side)
   - Find the unit (small text near value)
   - Find the normal range if shown (usually in parentheses)
3. Make sure: value is in SAME ROW as test name
4. Translate Arabic test names to English
5. Extract EVERY row - don't skip any

IMPORTANT:
- If test name has a value in the same row → EXTRACT IT
- If unsure about column alignment → STILL EXTRACT with note "uncertain_alignment"
- Do NOT skip rows because they might be misaligned
- Include ALL data even if some fields might be in wrong columns

EXAMPLE 1 - Horizontal table:
Image: "Glucose | 95 | mg/dl | (70-100)"
Extract: field_name="Glucose", field_value="95", field_unit="mg/dl", normal_range="(70-100)"

EXAMPLE 2 - Vertical table with Arabic:
Image row: "السكر | 109 | mg/dl"
Extract: field_name="Blood Sugar", field_value="109", field_unit="mg/dl"

EXAMPLE 3 - Marked abnormal:
Image: "Creatinine | * 230 | mg/dl"  
Extract: field_name="Creatinine", field_value="230", field_unit="mg/dl", notes="marked_abnormal"

RETURN JSON (REQUIRED):
{{
    "patient_name": "from report header",
    "patient_age": "number only",
    "patient_gender": "Male or Female",
    "report_date": "YYYY-MM-DD",
    "report_name": "test name from header",
    "report_type": "Clinical Chemistry / Hematology / etc",
    "doctor_names": "from signature or header",
    "medical_data": [
        {{
            "field_name": "test name",
            "field_value": "value",
            "field_unit": "unit",
            "normal_range": "(X-Y) or empty",
            "category": "section name if visible",
            "notes": "empty or uncertain_alignment or marked_abnormal"
        }}
    ]
}}

EXTRACT NOW - Read every row, translate Arabic, return JSON only.
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
