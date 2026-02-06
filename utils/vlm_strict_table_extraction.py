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
- Each page may contain DIFFERENT TEST SECTIONS (page 1 = Biochemistry, page 2 = Hematology)
- Extract ALL tests from THIS page - do NOT skip them
- Do NOT skip data that appeared on a different page
"""
    
    return f"""
🔬 EXTRACT MEDICAL TABLE DATA - STRICT BASELINE LOCK
Page {idx}/{total_pages}{page_context}

🚨 HORIZONTAL BASELINE LOCK (CRITICAL) 🚨
1. **Vertical Column Discovery (Arabic RTL)**: This report is primarily Arabic. Columns are arranged RIGHT to LEFT:
   - [ الفحص (Test Title) | النتيجة (Result) | النتيجة الطبيعية (Normal Range) | الوحدة (Unit) | ملاحظات (Notes) ]
2. **Horizontal Row Anchor**: For every row, identify the vertical center (baseline) of the Test Name. 
3. **Strict Column Extraction**: ONLY extract values/ranges that are physically located on that SAME vertical baseline. 
   - If a value is slightly above or below the baseline of the test name, it belongs to a DIFFERENT test. 
4. **No Merging**: Do not merge the value and unit. Keep them separate.
5. **Literal Capture**: Capture the Test Name exactly as written (Arabic or English). 
6. **Full Name Capture**: For patient demographics, find "اسم المريض" on the right. Capture EVERY WORD to its left until the border of the box. Do not truncate names.

JSON RETURN:
{{
    "patient_name": "Full patient name (all words)",
    "patient_age": "Literal age/DOB",
    "doctor_names": "Literal doctor name",
    "medical_data": [
        {{
            "field_name": "Literal test name",
            "field_value": "Literal result value",
            "field_unit": "Literal unit",
            "normal_range": "Literal Range (e.g. 0-200 or < 5.0)"
        }}
    ]
}}
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
