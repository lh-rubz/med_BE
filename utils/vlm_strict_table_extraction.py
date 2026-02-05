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
🔬 EXTRACT MEDICAL TABLE DATA - NO-SKIP PROTOCOL
Page {idx}/{total_pages}{page_context}

🚨 NO-SKIP SENTINEL (CRITICAL) 🚨
1. **Vertical Column Lock**: Results (left), Units (center), Ranges (right).
2. **Horizontal Sentinel**: If a row has ONLY a flag (like "*" or "#") but NO number, you MUST return `field_value`: "N/A".
   - DO NOT skip any horizontal line you see in the table. 
   - Every line of text in the "Test" column MUST have a corresponding JSON entry.
3. **Spatial Lock**: Trace a straight horizontal line from the test name. If you find no number, use "N/A". This prevents row-jumping.

JSON RETURN:
{{
    "patient_name": "Value to the LEFT of 'اسم المريض'",
    "patient_age": "Value to the LEFT of 'تاريخ الميلاد' (or DOB)",
    "doctor_names": "Value to the LEFT of 'الطبيب'",
    "medical_data": [
        {{
            "field_name": "Literal test name",
            "field_value": "Result or 'N/A' if row is empty/flagged",
            "field_unit": "Unit",
            "normal_range": "(X-Y)"
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
