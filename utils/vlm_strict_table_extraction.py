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
   - IF the result is `< 6.0`, you MUST capture `< 6.0`. 🚫 DO NOT strip the `<`.
   - IF the result is `*`, capture `field_value`: "EMPTY_SPECIFIED". 🚫 DO NOT borrow from the next line.
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
    Enhanced VLM prompt featuring Chain-of-Thought reasoning, explicit RTL rules, 
    and one-shot examples for high-precision medical data extraction.
    Enforces exact row count alignment with OCR anchors but reads names from the image.
    """
    return f"""
🔬 MEDICAL REPORT DIGITIZATION - PHASE 2 (VISUAL VERIFICATION)
Page {idx}/{total_pages}

### 🧠 STEP-BY-STEP REASONING (DO THIS FIRST)
1. **Analyze Layout**: Identify if the report is a Grid, a List, or a Tabular structure.
2. **Identify Column Order**: Look for Arabic labels (الفحص, النتيجة). If present, columns scan RIGHT-TO-LEFT.
3. **Row Counting**: Count the rows in the OCR REFERENCE below — your output MUST have the SAME number of rows.
4. **Visual Reading**: For each row, READ the test name, value, unit, and range DIRECTLY FROM THE IMAGE.

### 🚨🚨🚨 ROW COUNT GUIDANCE (IMPORTANT) 🚨🚨🚨
- The OCR REFERENCE below lists the rows found in the report.
- Your output should include ONLY rows that have a VISIBLE NUMERIC RESULT in the image.
- 🚫 **SKIP any row** that has NO visible numeric value, or shows only "*", "-", ".", or is blank in the Result column.
- 🚫 NEVER MERGE TWO ROWS. 🚫 NEVER ADD EXTRA ROWS not in the report.
- 🚫 **ZERO HALLUCINATION**: If you cannot see a clear numeric result for a row in the image, DO NOT INCLUDE THAT ROW. Do NOT guess or invent a number.

### 🚨🚨 FIELD NAME RULE (READ FROM IMAGE, NOT OCR) 🚨🚨
- The OCR list below is for **ROW COUNT and ORDER reference ONLY**.
- 🚫 Do **NOT** copy the field names from the OCR list. OCR often mangles names (truncates, adds extra characters, wrong letters).
- ✅ You MUST **read every test name character-by-character directly from the image**.
- ✅ Copy the EXACT spelling as printed in the report image — including parentheses, abbreviations, and punctuation.
- Example: If OCR says "Cholesterol, Tota" but the image clearly shows "Cholesterol,Total", you MUST write "Cholesterol,Total".
- Example: If OCR says "hematocrit (HCT)T)" but image shows "hematocrit (HCT)", you MUST write "hematocrit (HCT)".

### 🚨 EXTRACTION RULES
- 🚨 **UNIT FIDELITY (ULTRA-STRICT)**: Capture units **EXACTLY** as they appear in the ink. If the image says "%L" or "%G", DO NOT simplify it to "%". **DO NOT "HELP" BY CLEANING THE UNIT**. Extract exactly what is written, character-for-character.
- 🚫 **NO SHIFTING**: Do NOT pull a result from the row above or below. 
- 🚨 **PIXEL-LOCKED ALIGNMENT**: For each Test Name, trace a direct horizontal path (baseline). Capture ONLY the numeric value and unit that sits on that exact vertical level. If you hit a different row's pixels, STOP.
- 🚫 **ZERO HALLUCINATION (VALUES)**: If there is NO visible numeric ink for a row, **DO NOT INCLUDE THAT ROW**. Skip it entirely. NEVER guess a number from the range, unit, or a different row.
- 🚫 **NO RANGE BLEEDING**: Strictly keep "Normal Range" separate from "Test Name".
   - Bad: "Monocytes (% (1.0-3.0)"
   - Good: Name="Monocytes (%)", Range="(1.0-3.0)"
- 🔬 **PREFIX PROTECTION**: If a test starts with a letter and dash (e.g., "C - Reactive Proteins", "S - Albumin"), YOU MUST capture the "C -" as part of the Test Name. NEVER put "C" in the Result column.
- 🚨 **EMPTY RANGE RULE**: If the Normal Range column shows only `(-)`, `(—)`, `(-)` or a single dash, that means NO reference range exists. Return `normal_range`: "" (empty string). Do NOT return "(-)".

### ⬅️ ARABIC TABLE FLOW (RIGHT-TO-LEFT)
[RIGHTMOST] Test Name (الفحص) ➔ Result (النتيجة) ➔ Range (النتيجة الطبيعية) ➔ Unit (الوحدة) [LEFTMOST]

### 👤 DEMOGRAPHICS (READ FROM IMAGE)
1. **Patient Name**: Look at the cell next to "اسم المريض" in the header. **Read the EXACT characters from the image**, letter by letter. Do NOT copy the OCR name below — OCR may have wrong letters.
   - 🚨 **SPACING RULE**: The word "ابو" (Abu) is ALWAYS a separate word. NEVER merge it with the next word.
2. **Doctor Name**: Look at the cell next to "الطبيب" in the header. **Read the EXACT characters from the image**.
   - 🚫 Do NOT confuse "عيادة" (Clinic) or "مختبر" (Lab) or "وزارة" (Ministry) with a doctor name.
   - The doctor name is a PERSON's name (e.g., "جهاد العملة"), NOT a facility or department.

---
### 📋 OCR REFERENCE (ROW COUNT ONLY — do NOT copy names or spelling from here)
{organized_text}

JSON RETURN ONLY:
{{
    "patient_name": "Read EXACT name from image next to اسم المريض. Letter by letter.",
    "patient_age": "Literal age or DOB",
    "patient_gender": "Male or Female",
    "report_date": "YYYY-MM-DD (Arabic: DD/MM/YYYY, English: MM/DD/YYYY)",
    "doctor_names": "Read EXACT doctor name from image next to الطبيب. Person name only.",
    "medical_data": [
        {{
            "field_name": "Read EXACT test name from image (NOT from OCR list). Character by character.",
            "field_value": "Numeric Value from SAME row ONLY (empty string if no value visible or shows * only)",
            "field_unit": "Unit (🚨 MIRROR PRECISELY: e.g. '%L', '%G', 'mg/dL'). No simplification.",
            "normal_range": "Literal Range from image. If column shows (-) or dash only, return empty string.",
            "notes": "Any visual flags (handwritten, signature, etc)"
        }}
    ]
}}

🚨 FINAL CHECK: Verify that every row in your output has a REAL numeric value that you can see in the image. If any row has a value you are not confident about, REMOVE that row.
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
