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
🔬 MEDICAL JSON - EXTREME VISUAL MIRRORING (INK-FIRST MODE)
Page {idx}/{total_pages}

🚨 OPERATING RULE: YOU ARE A HIGH-RESOLUTION SCANNER. 
- 🚫 DO NOT use medical knowledge (e.g. if it looks like `1.1`, do not return `1.4`).
- 🚫 DO NOT "fix" typos. Mirror exactly what is on the paper.
- 🎨 **HANDWRITING/STAMPS**: You MUST capture all ink (stamps, handwriting, signatures). 

🚨 DOCTOR & PATIENT SCAN (TOP GRIDS) 🚨
1. **PATIENT NAME**: Top-RIGHT grid. Find "اسم المريض". The name is to its left.
2. **DOCTOR NAME**: Top-LEFT grid (5-row box). Locate the label "التطبيب" or "الطبيب" in the VERY BOTTOM row.
   - Look for a **STAMP** or **HANDWRITTEN NAME** immediately to its LEFT (e.g. جهاد العملة, أحمد نعيرات).
   - 🚫 If no ink is visible next to the label, return "EMPTY_IN_IMAGE".

🚨 TABLE MIRRORING (PIXEL-TRACE RULES) 🚨
For every row in the OCR Reference:
1. **Trace Handwriting**: If a result is handwritten (slanted, ink-based), look at the shape carefully. 
   - `1.1` has two vertical strokes. `1.4` has a cross-stroke. MIRROR ONLY THE INK.
2. **Handle Symbols**: 
   - If a cell contains a diagonal line (`/`), a cross (`X`), or a star (`*`), return "EMPTY_SPECIFIED".
   - 🚫 **NO BORROWING**: If Row X is empty, JSON Row X MUST be "EMPTY_SPECIFIED". Do not use data from Row X+1.
3. **Exact Ranges**: If a range is `(0.7-4.8)`, you MUST NOT return `(1.5-4)`. Mirrored pixels only.
4. **Exact Units**: Mirror symbols exactly (`K/uL`, `10(GSD)`, `M/uL`).

🚨 ROW SEQUENCE INTEGRITY 🚨
- Follow the OCR Reference order below 1:1. 
- If the image has Row 3 blank, Row 3 in JSON is "EMPTY_SPECIFIED".

JSON RETURN ONLY:
{{
    "patient_name": "Exact name from image",
    "doctor_names": "Exact ink/stamp next to 'الطبيب'",
    "patient_age": "Literal age/DOB",
    "patient_gender": "Male/Female",
    "medical_data": [
        {{
            "field_name": "Name from OCR",
            "field_value": "Literal mirrored value or 'EMPTY_SPECIFIED'",
            "field_unit": "EXACT mirrored unit (e.g. K/uL, 10(GSD))",
            "normal_range": "EXACT mirrored range"
        }}
    ]
}}

### ORGANIZED OCR REFERENCE (STRICT MIRROR ORDER) ###
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
