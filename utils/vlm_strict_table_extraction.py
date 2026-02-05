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
🔬 EXTRACT MEDICAL TABLE DATA - SYMBOL CAPTURE LOCK
Page {idx}/{total_pages}{page_context}

🚨 SYMBOL CAPTURE LOCK (CRITICAL) 🚨
1. **Vertical Column Lock**: Results (left), Units (center), Ranges (right).
2. **Symbol as Value**: If a row has ONLY a flag (like "*" or "#") but NO number, you MUST return `field_value`: "*".
   - NEVER skip a horizontal line that has a symbol. This is the only way to maintain vertical alignment.
3. **Box Reading (Demographics)**: Each header box has the Label on the RIGHT and the Value on the LEFT. Extract the text from the LEFT side.

JSON RETURN:
{{
    "patient_name": "Arabic name from LEFT half of 'اسم المريض' box",
    "patient_age": "Value from LEFT half of 'تاريخ الميلاد' box",
    "doctor_names": "Person name from LEFT half of 'الطبيب' box",
    "medical_data": [
        {{
            "field_name": "Literal test name",
            "field_value": "Result (number or '*' if only flag exists)",
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
