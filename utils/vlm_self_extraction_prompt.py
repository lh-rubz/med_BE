"""
Self-Prompting: Model analyzes report structure and writes its own extraction prompt.
This ensures compatibility with all report types without predefined structure patterns.
"""


def get_self_prompting_analysis_prompt(idx: int, total_pages: int) -> str:
    """
    Phase 1: Ask model to analyze the report and write its own extraction prompt.
    The model understands the structure better than hardcoded rules.
    """
    return f"""You are analyzing page {idx}/{total_pages} of a medical report.

STEP 1: ANALYZE THE REPORT STRUCTURE
Look at this medical report image and identify:
1. Layout direction: Is it LTR (left-to-right, English) or RTL (right-to-left, Arabic)?
2. Language: English, Arabic, or Bilingual?
3. Table structure: How many columns? What are the headers?
4. Column order: From left to right (or right to left if RTL), what columns are in what order?
5. Number of data rows: How many test entries do you see?

STEP 2: WRITE YOUR OWN EXTRACTION PROMPT
Based on what you see, write a detailed extraction prompt that YOU would use to extract data from this report accurately.
Your prompt should:
- Explain how to read the table (column by column, row by row)
- Specify what to extract for each column
- Include exact value preservation rules (operators, decimal places, etc.)
- Explain that empty fields should be returned as empty strings
- Specify JSON output format

STEP 3: RETURN THIS EXACT JSON (no markdown, no extra text):
{{
  "language": "English|Arabic|Bilingual",
  "direction": "LTR|RTL",
  "column_count": 3|4|5|6,
  "columns": ["col1_name", "col2_name", "col3_name", ...],
  "total_test_rows_estimate": <number>,
  "extraction_prompt": "YOUR DETAILED EXTRACTION PROMPT HERE - make it clear and specific for THIS report structure"
}}

Remember: Your extraction prompt will be used directly by the model to extract medical data. Make it clear, specific, and detailed.
Include exact instructions on:
- How to read the table (direction and order)
- What each column contains
- How to handle empty cells
- How to preserve exact values (operators, decimals, spacing)
- Expected JSON output format
"""


def get_self_directed_extraction_prompt(
    analysis_data: dict,
    idx: int,
    total_pages: int,
    report_types: list
) -> str:
    """
    Phase 2: Use the model's own analysis to guide extraction.
    The model's extraction_prompt tells it exactly how to read the report.
    """
    
    custom_extraction_prompt = analysis_data.get(
        'extraction_prompt',
        'Extract all medical test data from this report.'
    )
    
    report_metadata = f"""
REPORT METADATA TO EXTRACT (Page {idx}/{total_pages}):
- patient_name: Patient's name from header (remove titles: Dr., Mr., Mrs., etc.)
- patient_age: Age as number only
- patient_gender: Convert to "Male" or "Female" (or "" if not found)
- report_date: Date in YYYY-MM-DD format only (no time)
- report_name: The report section title (e.g., "HAEMATOLOGY", "BIOCHEMISTRY")
- report_type: Match to: {', '.join(report_types)}
- doctor_names: Referring doctor name (remove Dr. title)

DATA EXTRACTION RULES (Critical):
1. Take values EXACTLY as shown in the report
2. If a field is empty/blank in the report, return empty string ""
3. If normal_range is missing, that's OK - return ""
4. Preserve operators: If shows "< 5.7", keep it as "< 5.7"
5. Preserve decimals exactly: 14.5 not 14.50
6. Only include entries with BOTH field_name and field_value (skip empty rows)
7. Read each row independently - do NOT mix values from different rows

THE MODEL'S ANALYSIS OF THIS REPORT:
- Language: {analysis_data.get('language', 'Unknown')}
- Direction: {analysis_data.get('direction', 'Unknown')}
- Columns: {', '.join(analysis_data.get('columns', []))}
- Estimated rows: {analysis_data.get('total_test_rows_estimate', 'Unknown')}

THE MODEL'S EXTRACTION INSTRUCTIONS FOR THIS SPECIFIC REPORT:
{custom_extraction_prompt}

JSON OUTPUT FORMAT (exactly this structure):
{{
    "patient_name": "",
    "patient_age": "",
    "patient_gender": "",
    "report_date": "YYYY-MM-DD",
    "report_name": "",
    "report_type": "",
    "doctor_names": "",
    "total_fields_in_image": 0,
    "medical_data": [
        {{
            "field_name": "Test Name",
            "field_value": "123.4",
            "field_unit": "mg/dL",
            "normal_range": "100-200",
            "category": "SECTION NAME",
            "notes": ""
        }}
    ]
}}

VALIDATION:
- Count all rows: How many tests do you see? {analysis_data.get('total_test_rows_estimate', '?')} or more/less?
- Only return rows with field_name AND field_value
- If value is empty, skip that row
- If range is empty, that's OK - leave it empty
- Do NOT invent data

Return ONLY valid JSON (no markdown).
"""
    
    return report_metadata


def get_simplified_extraction_prompt(idx: int, total_pages: int, report_types: list) -> str:
    """
    Simplified one-shot extraction: Skip structure analysis, go straight to extraction.
    Optimized for both LTR (English) and RTL (Arabic) report layouts.
    """
    
    return f"""Extract EVERY medical test from this report image (page {idx}/{total_pages}).

LANGUAGE & LAYOUT DETECTION:
- If the report is mostly ARABIC text: It's likely RTL (right-to-left reading direction)
- If the report is mostly ENGLISH text: It's likely LTR (left-to-right reading direction)
- If BILINGUAL (Arabic + English): Check the table headers language and determine reading direction
  - Arabic headers = RTL reading direction
  - English headers in RTL table = Still read columns from right to left logically

CRITICAL: RTL Table Column Mapping for Arabic Medical Reports
===============================================================

IMPORTANT: On the screen (visual), RTL Arabic medical tables appear as:
    Visual Position: Left    Mid-Left   Mid    Mid-Right   Right
    (what you see):  Notes → Unit    → Range → Value   → Test Name

But the logical reading order (how to extract) is OPPOSITE:
    Logical Order:   Test Name ← Value ← Range ← Unit ← Notes
    (right column)   (rightmost) 

EXACT COLUMN MAPPING FOR RTL MEDICAL TABLES:

1. IDENTIFY COLUMNS BY VISUAL POSITION ON SCREEN:
   - Column A (Leftmost visual):     Usually "ملاحظات" (Notes) or "Remarks"
   - Column B (Left-middle visual):  Usually "الوحدة" (Unit) or "Unit"
   - Column C (Center visual):       Usually "النسبة الطبيعية" (Normal Range) or "Normal"
   - Column D (Right-middle visual): Usually "النسبة" (Value) or a numeric column
   - Column E (Rightmost visual):    Usually "المختبر" (Test Name) or long descriptive text

2. EXTRACTION MAPPING (Logical Order - Right to Left):
   - TEST NAME:      From Column E (Rightmost) - it's the longest text, descriptive
   - VALUE:          From Column D (Right-middle) - it's numeric, matches the test
   - NORMAL RANGE:   From Column C (Center) - it's in parentheses like "(80-100)" or shows "-" if none
   - UNIT:           From Column B (Left-middle) - short abbreviations like "g/dL", "%", "K/uL"
   - NOTES:          From Column A (Leftmost) - flags or additional info

3. VERIFICATION - Match Test Name to Value:
   After extraction, VERIFY that:
   - The VALUE is logically correct for the TEST NAME
   - Examples:
     ✓ "Haemoglobin" = "12.6" (numeric value makes sense)
     ✓ "Platelet Count" = "257" (numeric value makes sense)
     ✗ "Red Blood Cell Distribution Width" = "257" (wrong - 257 is platelet count)
     ✗ "Basophils" = "17.7" with unit "%" (only if 17.7 makes sense for basophils)

4. ROW-BY-ROW EXTRACTION:
   For EACH row in the table:
   - Identify Test Name first (rightmost column)
   - Then find its Value (next column to left)
   - Then find Range/Unit/Notes (remaining columns)
   - DO NOT skip columns or read them out of order
   - Each value must stay with its test name on the same row

5. SPECIAL HANDLING FOR ARABIC RTL TABLES:
   - Some tables may have column order variations (rare)
   - If a numeric value doesn't make sense for a test name, you likely read it from wrong row
   - If you see a test name twice with different values, extract BOTH (not a duplicate)
   - If Range column shows "-" or blank, return empty string ""
   - Units may be in different columns depending on lab format

6. COMMON MISTAKES TO AVOID:
   ✗ Reading the same column twice
   ✗ Matching values from one row to test names from another row
   ✗ Confusing Unit and Normal Range columns
   ✗ Missing or inventing data
   ✗ Extracting test names in wrong language order

TABLE READING STRATEGY - IMPLEMENTATION:
For LTR (English/Left-to-Right) reports: Read columns LEFT to RIGHT

For LTR (English/Left-to-Right) reports:
  Read the table LEFT to RIGHT:
  Column 1 (Leftmost) → Column 2 → Column 3 → Column 4 (Rightmost)
  
  Typical LTR structure:
  Test Name | Value | Unit | Reference Range | Notes
  
  Example row (LTR):
  Hemoglobin | 14.5 | g/dL | (12-16) | —

CRITICAL: LTR Table Column Mapping for English Medical Reports
==============================================================

For LTR tables, IDENTIFY COLUMNS BY VISUAL POSITION (LEFT to RIGHT):
1. Column A (Leftmost):        Test Name - The medical test name (e.g., "Hemoglobin", "Fasting Blood Sugar")
2. Column B (Left-middle):     Value - The numeric result (e.g., "14.5", "109", "0.56")
3. Column C (Center):          Unit - Measurement unit (e.g., "g/dL", "mg/dl", "U/L")
4. Column D (Right-middle):    Normal Range - Reference range in parentheses like "(12-16)" or "(74-110)"
5. Column E (Rightmost):       Notes/Remarks - Optional flags or additional info (often empty or "*")

EXTRACTION MAPPING FOR LTR (Left to Right):
- TEST NAME:      From Column A (Leftmost) - the descriptive test name
- VALUE:          From Column B (Left-middle) - the numeric result value
- UNIT:           From Column C (Center) - the measurement unit
- NORMAL RANGE:   From Column D (Right-middle) - reference range in parentheses
- NOTES:          From Column E (Rightmost) - any flags or remarks

ROW-BY-ROW EXTRACTION FOR LTR:
1. For EACH row in the table:
   - Start from the LEFTMOST column
   - Read: Test Name → Value → Unit → Range → Notes
   - STAY ON THE SAME ROW - do NOT mix columns from different rows
   - Each row contains ONE test with all its data

2. CRITICAL: Do NOT confuse columns:
   - Value column is NEXT TO test name (2nd column from left)
   - Unit column is NEXT TO value (3rd column from left)
   - Range column is NEXT TO unit (4th column from left)
   - Do NOT read values from wrong columns

3. Example of CORRECT extraction:
   Row: "Fasting Blood Sugar | 109 | mg/dl | (74-110) | "
   Extract: field_name="Fasting Blood Sugar", field_value="109", field_unit="mg/dl", normal_range="(74-110)"

4. Example of WRONG extraction:
   If you mistakenly read: "Creatinine | 230 | mg/dl | (0.5-0.9) | "
   This is WRONG because 230 is from a different row's value
   CORRECT is: "Creatinine, serum | 0.56 | mg/dl | (0.5-0.9) | "

COMMON LTR ROW-MIXING ERRORS TO AVOID:
- ❌ Reading test name from row 1, but value from row 2
- ❌ Reading value that doesn't match the test name
- ❌ Skipping rows because they look different
- ❌ Reading the same row twice with different interpretations
- ✅ Read each row completely from left to right, one row at a time
- ✅ Verify value is logically correct for the test name
- ✅ Example: "Creatinine" should have value 0.56, NOT 230 (230 is cholesterol)

For RTL (Arabic/Right-to-Left) reports:
  Read the table RIGHT to LEFT:
  Column 1 (Rightmost visually) → Column 2 → Column 3 → Column 4 (Leftmost visually)
  
  BUT the LOGICAL order is still: Test Name, Value, Unit, Range
  
  Visual RTL structure (what you see on screen):
  Notes | Reference Range | Unit | Value | Test Name
  (Leftmost visually)                    (Rightmost visually)
  
  Example row (RTL visual):
  — | (12-16) | g/dL | 14.5 | Hemoglobin
  
  HOW TO EXTRACT FROM RTL:
  1. IDENTIFY THE TEST NAME:
     - It's the RIGHTMOST column in the table (visually on the right side)
     - Usually the longest text, descriptive names like "الهيموجلوبين" or "Hemoglobin"
     - Examples: "red blood cell", "white blood cell", "platelet count"
  
  2. IDENTIFY THE VALUE:
     - It's NEXT TO the test name (to the left of test name in visual RTL layout)
     - Always a number, possibly with decimals or operators (< > ≤ ≥)
     - Examples: "14.5", "12.6", "40.2", "< 5.0"
  
  3. IDENTIFY THE UNIT:
     - It's NEXT TO the value (to the left in visual RTL)
     - Short abbreviations or symbols: "g/dL", "mg/dL", "%", "K/uL", "cells/L"
     - Can be empty in some reports
  
  4. IDENTIFY THE RANGE:
     - It's NEXT TO the unit (to the left in visual RTL, usually near leftmost)
     - Format: "(min-max)" or "[min-max]" or "(value)"
     - Examples: "(12-16)", "(0-33)", "(74-110)"

IMPORTANT RTL CORRECTION RULES:
- If you extract the same test twice on the same page, it's a duplicate - KEEP ONLY THE FIRST
- If rows have mixed order in RTL, match Test Name + Value together (they should be adjacent)
- Do NOT skip rows because they look different - all rows in the table should be extracted
- After reading RIGHT to LEFT, the extracted data should still have logical order

EXTRACTION RULES:
1. Read ALL test rows in the main table (do not skip any rows)
2. For EACH test row, extract:
   - field_name: Test name (exactly as shown, can be Arabic or English)
   - field_value: Result value (exactly as shown, including < > operators, preserve decimals)
   - field_unit: Measurement unit (mg/dL, U/L, %, etc. - can be empty)
   - normal_range: Reference range with parentheses if shown (e.g., "(74-110)"), otherwise ""
   - category: Section name (HAEMATOLOGY, BIOCHEMISTRY, CLINICAL CHEMISTRY, كيمياء سريرية, etc.)
   - notes: Any flags (High, Low, Critical, abnormal, etc.) - usually shown as symbols or text

3. ONLY include rows with a test name AND a result value
4. If a field is empty, return ""
5. Preserve exact values: decimals, operators (< > ≤ ≥), spacing
6. If normal_range appears as separate columns, combine into one field
7. DEDUPLICATE: If you see the same test name twice with identical values, report only once

HEADER/METADATA EXTRACTION:
Look for these fields in the HEADER section (not the table):

For ENGLISH reports, look for:
- "Patient Name:" or "Name:" → patient_name (extract THE COMPLETE FULL NAME as written, including all words - first, middle, last names)
- "Age:" or "DOB:" or "Date of Birth:" → patient_age 
  * If shows "Age: XX" → extract the number only (XX)
  * If shows "DOB:" or "Date of Birth:" → extract the date, then CALCULATE age: (report_date - DOB)
- "Gender:" or "Sex:" → patient_gender (must extract: look for "M", "F", "Male", "Female", "ذكر" (male), "أنثى" (female))
- "Date:" or "Report Date:" → report_date (use THIS date from the report, NOT today's date)

For ARABIC reports, look for:
- "اسم المريض:" or "الاسم:" or "اسم" → patient_name (extract THE COMPLETE FULL NAME as written, including all Arabic words)
- "العمر:" or "السن:" → patient_age (if shows number, extract it)
- "تاريخ الميلاد:" or "DOB:" → if shows date, CALCULATE age: (report_date - DOB)
- "الجنس:" or "النوع:" → patient_gender (look for: "ذكر", "أنثى", "M", "F", "Male", "Female")
- "التاريخ:" or "تاريخ التقرير:" or "التاريخ:" → report_date (use the report date from the header)
- "الطبيب:" or "المراجع:" or "اسم الطبيب:" → doctor_names

IMPORTANT - FULL NAMES:
- Extract the COMPLETE name as written in the report
- If name is "Ahmed Mohamed Hassan Ali" → extract ALL: "Ahmed Mohamed Hassan Ali" (not just "Ahmed Ali")
- If name is "أحمد محمد حسن علي" → extract ALL: "أحمد محمد حسن علي"
- Do NOT abbreviate or shorten names - keep the exact full name

IMPORTANT - GENDER EXTRACTION:
Gender MUST be extracted. Look carefully for:
- ENGLISH: "Male", "M", "male", "m"
- ENGLISH: "Female", "F", "female", "f"
- ARABIC: "ذكر" (male), "م" (male abbreviation)
- ARABIC: "أنثى" (female), "ا" (female abbreviation)
- If you see gender field, extract it - do NOT leave blank

IMPORTANT - AGE CALCULATION FROM DOB:
If report shows "Date of Birth" or "DOB" instead of age:
1. Extract the DOB date (format: DD/MM/YYYY or similar)
2. Extract the Report Date from the report
3. Calculate: Age = (Report Date - DOB) in years
4. Return the calculated age as a number
Example: If DOB = 1980-05-15 and Report Date = 2026-02-04
         Age = 2026 - 1980 = 46 years old → return "46"

CRITICAL NAME CLEANING:
After extracting patient_name or doctor_names:
1. Remove ONLY medical/professional titles at the START: "د." "دكتور" "Dr" "Prof" "أ.د" "الدكتور" "البروفيسور" "MD" "Dr." "Prof."
2. Remove ONLY position titles at the START: "رئيسة" "رئيس" "مدير" "مسؤول" "مساعد" "معاون"
3. Keep the actual person's name - ALL their names (first, middle, last)
4. Arabic names: Keep them in Arabic
5. Do NOT remove words that are part of the actual name
6. CLEAN CORRUPTED TEXT: If text contains symbols, parentheses, or corrupted characters mixed with names:
   - Remove symbols: ")" "(" "[" "]" "{" "}" 
   - Remove corrupted fragments that don't look like Arabic or English words
   - Keep only readable text that looks like a real name
   
Example: "Dr. Ahmed Mohamed Hassan" → remove "Dr." → keep "Ahmed Mohamed Hassan"
Example: "رئيسة أسماء محمد علي" → remove "رئيسة" → keep "أسماء محمد علي"
Example: "الطب المطم ) منبررا صعة رل الله" → This is corrupted/nonsensical
         Remove: symbols ")", corrupted words "المطم", "منبررا", "صعة", "رل"
         Keep: ONLY if meaningful name found, otherwise return ""
         Result: "" (because "الطب" is "medicine" not a name)

IMPORTANT: If extracted text contains:
- Random symbols or parentheses mixed with words
- Words that don't form a logical name
- Corrupted/garbled text
- Medical terms mixed with names (like "الطب" = medicine)
Then return "" (empty) instead of the corrupted text
It's better to return empty than to store corrupted data

For BILINGUAL reports: Look in the HEADER for BOTH English and Arabic labels

Date Format Handling:
- Extract the REPORT DATE from the report (not today's date)
- If date is DD/MM/YYYY format: Convert to YYYY-MM-DD
- If date is MM/DD/YYYY format: Convert to YYYY-MM-DD
- If date is already YYYY-MM-DD: Keep as is
- Extract only the DATE part, ignore time
- Use this date for age calculation if DOB is present

REPORT TYPE AND NAME:
- report_type: Match from list: {', '.join(report_types)}
- report_name: Look for section headers like "CLINICAL CHEMISTRY", "HAEMATOLOGY", "كيمياء سريرية", etc.
- If multiple sections: Use the section name corresponding to the current table

BEST PRACTICES FOR ACCURATE EXTRACTION:
1. Match Test Name + Value carefully - they should be on the same row
2. For RTL tables, visually, the test name is on the RIGHT and value is to the LEFT
3. Copy Units and Ranges EXACTLY as shown in the table
4. If Range column is empty or shows "-", return empty string ""
5. Double-check numeric values match what you see (do not round or convert)
6. Examples of correct pairings:
   ✓ "Hemoglobin" = "12.6" with unit "g/dL" and range "(12-16)"
   ✓ "Platelet Count" = "257" with unit "K/uL" and range "(140-450)"
   ✓ "Basophils" = "0.2" with unit "%" and range "(0-1)"
7. Do NOT invent or assume values - extract ONLY what you see

JSON OUTPUT (only this, no markdown, no extra text):
{{
    "patient_name": "",
    "patient_age": "",
    "patient_gender": "",
    "report_date": "YYYY-MM-DD",
    "report_name": "",
    "report_type": "",
    "doctor_names": "",
    "total_fields_in_image": 0,
    "medical_data": [
        {{
            "field_name": "Test Name (can be Arabic)",
            "field_value": "Value",
            "field_unit": "Unit",
            "normal_range": "(min-max) or empty",
            "category": "Section",
            "notes": ""
        }}
    ]
}}

VALIDATION CHECKLIST:
✓ Count all visible test rows in the table
✓ Each medical_data entry has field_name and field_value
✓ Empty cells are represented as ""
✓ Decimal values and operators are preserved exactly
✓ Normal ranges are in parentheses if present
✓ No invented data - extract only what you see
✓ Date is in YYYY-MM-DD format
✓ Patient name includes Arabic characters if present
✓ All test values match what's shown in the image
"""
