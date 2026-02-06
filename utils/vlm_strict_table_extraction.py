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
🔬 MEDICAL JSON - STRICT IMAGE MIRRORING PASS
Page {idx}/{total_pages}

🚨 CRITICAL: YOU ARE A DUMB VISUAL MIRROR. DO NOT USE MEDICAL KNOWLEDGE.
- If the image says range "(0.7-4.8)", you MUST NOT return "(1.5-4)".
- If the image says result "1.1", you MUST NOT return "1.4".
- Trust ONLY physical pixels. If columns are empty/diagonal, do not "fill" them.

🚨 DOCTOR & PATIENT SCAN (TOP BOXES) 🚨
1. **PATIENT NAME**: Top-Right grid. Locate "اسم المريض". The name is in the same cell area immediately to its left.
2. **DOCTOR NAME**: Top-LEFT grid (smaller box). Find the very LAST row labeled "الطبيب". Extract the name immediately to its LEFT (e.g., جهاد العملة).
   - 🚫 **BLANK RULE**: If that space is empty, return "EMPTY_IN_IMAGE". Do not invent names based on clinic titles.

🚨 TABLE INTEGRITY (THE "NO-BRAIN" MIRROR RULES) 🚨
For every row in the OCR Reference:
1. **Horizontal Trace**: Locate test name -> Trace 100% horizontally to the Result column.
2. **Literal Capture**: 
   - Capture small numbers (`0.1`, `1.1`, `0.23`) exactly.
   - **Scenario: Symbol**: If the result column has a star (`*`), a diagonal line (`/` or `X`), or a dash (`-`), you MUST return `EMPTY_SPECIFIED`. 
   - 🚫 **DO NOT BORROW**: Do not pull data from a neighboring row just because the current row is empty. 
3. **Exact Units**: Mirror every character. If it says `K/uL`, do not return `KuL`. If it says `10(GSD)`, return `10(GSD)`. 

🚨 ROW SEQUENCE SYNC 🚨
- You MUST follow the EXACT order of the OCR Reference below.
- Row 1 In OCR MUST map to Row 1 in Image.
- If Row 3 is empty in the image, Row 3 in JSON MUST be `EMPTY_SPECIFIED`.

JSON RETURN ONLY:
{{
    "patient_name": "As seen in image",
    "doctor_names": "Name next to 'الطبيب' (Mirror physical name)",
    "patient_age": "Age",
    "patient_gender": "Male/Female",
    "medical_data": [
        {{
            "field_name": "Name from OCR",
            "field_value": "Literal mirrored value or 'EMPTY_SPECIFIED'",
            "field_unit": "EXACT mirrored unit (e.g. K/uL, %G, 10(GSD))",
            "normal_range": "EXACT mirrored range (e.g. 0.7-4.8)"
        }}
    ]
}}

### ORGANIZED OCR REFERENCE (STRICT ORDER) ###
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
