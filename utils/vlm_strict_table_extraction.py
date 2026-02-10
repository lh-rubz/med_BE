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
    """
    return f"""
🔬 MEDICAL REPORT DIGITIZATION - PHASE 2 (VISUAL VERIFICATION)
Page {idx}/{total_pages}

### 🧠 STEP-BY-STEP REASONING (DO THIS FIRST)
1. **Analyze Layout**: Identify if the report is a Grid, a List, or a Tabular structure.
2. **Identify Column Order**: Look for Arabic labels (الفحص, النتيجة). If present, columns scan RIGHT-TO-LEFT.
3. **Anchor Matching**: Locate the Test Names provided in the 'OCR REFERENCE' on the physical image.
4. **Visual Alignment**: For each Test Name, trace a horizontal line ➔ capture ONLY the value, unit, and range that sits on that exact line.

### 🚨 OPERATIONAL RULES
- 🚫 **NO HALLUCINATION**: If the image shows '12.5' but OCR says '12.8', use '12.5'.
- 🚫 **NO SHIFTING**: Do NOT pull a result from the row above or below. If the current row is empty, use "EMPTY_SPECIFIED".
- 🌍 **MULTILINGUAL**: Supports English, Arabic, and Mixed text. Keep labels in their original language.
- 🎨 **INK-CAPTURE**: Mirror handwriting, stamps, and signatures exactly as they appear in ink.

### ⬅️ ARABIC TABLE FLOW (RIGHT-TO-LEFT)
If the table is Arabic, the column sequence is:
[RIGHTMOST] Test Name (الفحص) ➔ Result (النتيجة) ➔ Range (النتيجة الطبيعية) ➔ Unit (الوحدة) [LEFTMOST]

### 👤 DEMOGRAPHICS (ULTRA-SEARCH MODE)
1. **Patient Name**: Find "اسم المريض". Capture the FULL person's name (at least 3-4 words). 
   - 🚨 **MIRROR PERFECT SPELLING**: Do NOT change the letters. If it says "الرب" (Al-Rub), capture it as "الرب". DO NOT add letters like "الروب".
   - 🚨 **SPACING RULE**: The word "ابو" (Abu) is ALWAYS a separate word. NEVER merge it with the next word (e.g. 'أبو الرب' NOT 'أبورب').
   - ⚠️ Fix disjointed characters (e.g. 'أحمد نعی رات' -> 'أحمد نعيرات').
2. **Doctor**: 🔍 **MANDATORY ANCHOR RESPECT**. 
   - Look at the `OCR REFERENCE` doctor name below. 
   - You MUST locate this name in the IMAGE (check top-left red/blue header area, background logos, and stamps).
   - If the Anchor says "أحمد نعيرات", and you see ink that says "أحمد نعيرات", YOU MUST EXTRACT IT. DO NOT return "Not found".

---
### 📋 OCR REFERENCE (STRICT ANCHORS)
{organized_text}

JSON RETURN ONLY:
{{
    "patient_name": "Literal full name (🚫 NEVER merge 'أبو' with following word)",
    "patient_age": "Literal age or DOB",
    "patient_gender": "Male or Female",
    "report_date": "YYYY-MM-DD (Arabic: DD/MM/YYYY, English: MM/DD/YYYY)",
    "doctor_names": "Literal doctor name (🔍 Cross-check OCR Anchor with Header Ink/Stamps)",
    "medical_data": [
        {{
            "field_name": "Test Name",
            "field_value": "Value or 'EMPTY_SPECIFIED'",
            "field_unit": "Unit",
            "normal_range": "Range (🚨 PRECISION CHECK: Recount vertical pixels for numbers like '5.7' vs '1.7'. Do NOT guess.)",
            "notes": "Any visual flags (handwritten, signature, etc)"
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
