"""
Strict row-by-row table extraction prompt for medical reports.
Enforces spatial alignment and careful sequential reading.
"""


def get_strict_table_extraction_prompt(idx: int, total_pages: int) -> str:
    """Generate a high-precision table extraction prompt that enforces spatial anchoring."""
    
    return f"""
🔬 MEDICAL TABLE DIGITIZATION - SPATIAL ANCHOR LOCK
Page {idx}/{total_pages}

🚨 OPERATIONAL PROTOCOL (CRITICAL) 🚨
1. **Column Scanning (Right to Left)**: 
   - Column 1 (Far Right): [ الفحص ] - Test Parameter
   - Column 2: [ النتيجة ] - Numerical/Text Result
   - Column 3: [ النتيجة الطبيعية ] - Reference Range
   - Column 4: [ الوحدة ] - Measurement Unit
   - Column 5 (Far Left): [ ملاحظات ] - Notes

2. **Horizontal Baseline Lock**: 
   - For every test name found, visually lock onto its horizontal center line. 
   Trace this line leftward. ONLY pick up text that sits DIRECTLY on this same vertical baseline.
   - 🚫 DO NOT jump up or down. If a value is 5 pixels above or below the test name center, it belongs to another test or is a spacer.

3. **Strict Empty/Spacer Skipping**: 
   - If a row contains a test name but the "Result" column is empty, has a dot ".", or a star "*", you MUST SKIP this row. 
   - 🚫 DO NOT extract it. 🚫 DO NOT pull data from adjacent lines to fill it.
   - Only extract rows that have BOTH a clear Test Name and a clear Result on the same line.

4. **Literal Arabic Support**: 
   - Capture the FULL test name exactly as written.

JSON RETURN ONLY:
{{
    "medical_data": [
        {{
            "field_name": "Full Test Name",
            "field_value": "Numerical result (ONLY if present on baseline)",
            "field_unit": "Unit (ONLY if present on baseline)",
            "normal_range": "Range (ONLY if present on baseline)"
        }}
    ]
}}
"""


def get_ocr_refinement_prompt(idx: int, total_pages: int, organized_text: str) -> str:
    """
    Prompt for a second-pass refinement where the VLM maps already-organized OCR text 
    to the original image to produce the final, perfectly aligned JSON.
    """
    return f"""
🔬 MEDICAL JSON - TOTAL BASELINE LOCK & REFINEMENT
Page {idx}/{total_pages}

I have organized OCR text names. You MUST act as a High-Precision Visual Validator to map them to the image. 

🚨 DOCTOR/PATIENT ANCHORS (STRICT) 🚨
1. **PATIENT NAME**: Top-RIGHT grid. Locate "اسم المريض". The name is EXACTLY to its LEFT.
2. **DOCTOR NAME**: Top-LEFT grid. Locate the label "الطبيب" (bottom row of left grid). The name is EXACTLY to its LEFT. 
   - 🚫 **BLANK ANCHOR RULE**: IF the space next to "الطبيب" is blank, you MUST return `EMPTY_IN_IMAGE`. 🚫 DO NOT hallucinate "د.منى على" or "د. راشد الله".
   - 🚫 **LABEL PROTECTION**: Do not extract "عيادة", "مختبر", or "وزارة" as a name.

🚨 VERTICAL ROW INTEGRITY (NON-BORROWING RULES) 🚨
For EVERY row in the OCR REFERENCE, perform a "Pixel-Trace":
1. Find the literal test name in the image.
2. Trace a straight horizontal line to the Result column.
3. **Capture EVERY character**:
   - IF the result is `0.1` or `0.23`, capture it. 🚫 DO NOT skip.
   - 🚫 **THE NO-BORROW RULE**: If Row X has no value in the image, return `EMPTY_SPECIFIED`. 🚫 DO NOT take the value from Row X+1 or Row X-1. This causes "Shift Errors".
   - 🚫 **UNIT MIRRORING**: Capture units exactly (e.g., `%G`, `%L`, `KuL`). Do not strip the trailing letters.

🚨 ROW SEQUENCE SYNC 🚨
- Row 1 In OCR MUST map to Row 1 in Image.
- Row 2 In OCR MUST map to Row 2 in Image.

JSON RETURN ONLY:
{{
    "patient_name": "Name or 'EMPTY_IN_IMAGE'",
    "doctor_names": "Name or 'EMPTY_IN_IMAGE'",
    "patient_age": "Age/DOB",
    "patient_gender": "Male/Female",
    "medical_data": [
        {{
            "field_name": "Test Name from OCR",
            "field_value": "Literal value OR 'EMPTY_SPECIFIED'",
            "field_unit": "EXACT Unit (e.g. %G, %L, KuL)",
            "normal_range": "Range"
        }}
    ]
}}
{organized_text}
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
