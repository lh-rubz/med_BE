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
🔬 EXTRACT MEDICAL TABLE DATA - TWO-STEP SCAN
Page {idx}/{total_pages}{page_context}

CRITICAL: This is a high-precision extraction. Look at the image as a physical grid.

STEP 1: PRE-SCAN (ALL TEST NAMES)
Scan the table from TOP TO BOTTOM. List every single test name you see in the "all_tests_found" array. 
- If a name is Arabic, capture it. 
- If a name is English, capture it literals.
- **MULTI-LINE FIELDS**: Many labs (like Ramallah PHC) have test names that span 2 or 3 lines (e.g., "Red blood cell distribution\nwidth coefficient of\nvariation"). You MUST capture the ENTIRE name string.
- DO NOT hallucinate common names; extract EXACT literal text.

STEP 2: DATA EXTRACTION (ROW-BY-ROW)
For EACH name you listed in Step 1:
1. **BACKGROUND COLOR**: Identify if the row has a **GRAY** or **WHITE** background.
2. **PATTERN ADHERENCE**: Rows typically alternate (Gray, White, Gray, White).
3. **HORIZONTAL BASELINE LOCK**: Move horizontally from the test name to find Value, Unit, and Range on the SAME color band.
4. **UNIT PRECISION**: Extract units precisely (% , K/uL, M/uL, g/dL, fL, pg). Look specifically at the "Unit" column.
5. **SYMBOL ANCHOR (*)**: If you see a "*" or flag next to a value, this is a physical anchor proving a value exists. DO NOT skip these rows or return "N/A".
6. **EMPTY VALUE POLICY**: ONLY skip a field if the result value is physically empty white space.

VALIDATION RULES:
✓ Value must share the EXACT SAME color band as the test name.
✓ If you see "Red blood cell distribution width", ensure the value is from THAT row (e.g., 12.6%) and not the "Platelets Count" row (e.g., 257).
✓ **NO TRUNCATION**: Capture names completely, even if they wrap to 3 lines.
✓ Translate Arabic names to English but keep original in parentheses.

RETURN JSON:
{{
    "patient_name": "Full patient name from header",
    "patient_age": "DOB or Age",
    "patient_gender": "Male/Female",
    "report_date": "YYYY-MM-DD",
    "all_tests_found_in_prescan": ["Test 1", "Test 2", ...],
    "medical_data": [
        {{
            "field_name": "LITERAL name from image",
            "field_value": "numeric result with symbols like < or >",
            "field_unit": "from unit column",
            "normal_range": "(X-Y) from range column",
            "background_color": "gray or white",
            "notes": "any flags or Arabic notes"
        }}
    ]
}}

EXTRACT NOW - First list ALL test names, then fill the data bands.
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
