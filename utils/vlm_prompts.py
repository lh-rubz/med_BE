def get_personal_info_prompt(idx, total_pages):
    """
    Extract ONLY patient personal information (name, gender, age, DOB, doctor, report date).
    This is a dedicated prompt to avoid mixing personal data with medical data.
    """
    return f"""You are an expert medical document reader specializing in Arabic and English medical reports.

Your ONLY task: Extract PATIENT PERSONAL INFORMATION from this medical report image (page {idx}/{total_pages}).

DO NOT extract lab results or test values - those come later. 
FOCUS ONLY ON: Patient name, gender, age, date of birth, report date, and doctor name.

═══════════════════════════════════════════════════════════════════
STEP 1: LOCATE PATIENT INFORMATION SECTION
═══════════════════════════════════════════════════════════════════

Patient info is usually in:
1. Top-right corner (most common for Arabic labs)
2. Top-left corner  
3. Top-center of page
4. Sidebar panels
5. Any header area in top 40% of page

Scan ALL these locations before concluding a field is missing.

═══════════════════════════════════════════════════════════════════
STEP 2: EXTRACT EACH FIELD WITH VALIDATION
═══════════════════════════════════════════════════════════════════

2.1 PATIENT NAME (MANDATORY)
─────────────────────────────
Search for these labels:
- Arabic: "اسم المريض", "المريض", "الاسم", "مريض", "اسم"
- English: "Patient Name", "Name", "Patient", "Pt Name", "Full Name"

Rules:
✓ Extract the FULL name exactly as written
✓ Preserve original language (Arabic or English)
✓ Remove title prefixes (Mr., Mrs., Dr., Drs., etc.) if present
✗ Do NOT use doctor/physician name as patient name
✗ Do NOT translate the name

After extracting, VALIDATE:
- Does it look like a real person's name? (Contains at least 3 characters, at least one letter)
- Is it clearly NOT a label or ID number?
- If failed validation: return ""

Result: patient_name (or "" if not found)

2.2 PATIENT GENDER (MANDATORY)
──────────────────────────────
Search for these labels in PATIENT section (not doctor section):
- Arabic: "الجنس", "جنس", "النوع", "الجنسي"
- English: "Gender", "Sex", "M/F", "Gender:", "Sex:"

Read the ACTUAL value (don't guess from name):
- If you see: "ذكر", "Male", "M", "MALE", "male" → normalize to "Male"
- If you see: "أنثى", "انثى", "Female", "F", "FEMALE", "female" → normalize to "Female"

Result: patient_gender (exactly "Male", "Female", or "")

2.3 AGE AND DATE OF BIRTH
──────────────────────────
Search for:
- "تاريخ الميلاد", "DOB", "Date of Birth", "Birth Date", "DOB:", "Born:"
- "العمر", "عمر", "Age", "Age:", "years old"

If DATE found:
- Parse the date carefully (could be DD/MM/YYYY, MM/DD/YYYY, YYYY-MM-DD)
- Convert to ISO format: "YYYY-MM-DD"
- Set patient_dob = "1975-05-01" format

If only AGE found:
- Extract the number only: "50 years" → "50"
- Set patient_age = "50"

If NEITHER found: Both are ""

Result: patient_age (number as string or ""), patient_dob (YYYY-MM-DD or "")

2.4 REPORT DATE
───────────────
Search for:
- Arabic: "تاريخ الطلب", "تاريخ الفحص", "التاريخ", "تاريخ"
- English: "Report Date", "Test Date", "Date", "Date of Test", "Date:"

Parse carefully and convert to "YYYY-MM-DD" format.
If format is ambiguous, use context clues (Arabic dates are usually DD/MM/YYYY).

Result: report_date (YYYY-MM-DD or "")

2.5 DOCTOR/PHYSICIAN NAME
──────────────────────────
Search in REQUEST/DOCTOR section (usually LEFT or CENTER top area):
- Arabic: "الطبيب", "طبيب", "الطبيب المعالج", "طبيب معالج"
- English: "Doctor", "Physician", "Referred By", "Ref By", "Dr.", "MD"

Rules:
✓ Extract name only
✓ Remove titles: "Dr.", "Dr", "دكتور", "د.", etc.
✗ Do NOT include department names
✗ Do NOT confuse with patient name (they are in DIFFERENT sections)

Result: doctor_names (name or "")

═══════════════════════════════════════════════════════════════════
STEP 3: SELF-VALIDATION BEFORE RETURNING
═══════════════════════════════════════════════════════════════════

Check your work:
□ patient_name: If you found it, does it look like a real name? (NOT a label, NOT an ID, NOT a doctor name)
□ patient_gender: Is it EXACTLY "Male", "Female", or ""?
□ patient_age: If present, is it a reasonable age (1-120)?
□ patient_dob: If present, is it in YYYY-MM-DD format and a reasonable date?
□ report_date: If present, is it in YYYY-MM-DD format?
□ doctor_names: Does it look like a person's name (not a hospital/department name)?

If ANY field seems wrong, re-scan the image carefully and correct it.

═══════════════════════════════════════════════════════════════════
STEP 4: JSON OUTPUT FORMAT
═══════════════════════════════════════════════════════════════════

Return EXACTLY this JSON structure (no markdown, no extra text):

{{
  "patient_name": "Full name in original language, or empty string",
  "patient_age": "Number as string like \\"50\\", or empty string",
  "patient_dob": "YYYY-MM-DD format or empty string",
  "patient_gender": "Male or Female or empty string",
  "report_date": "YYYY-MM-DD format or empty string",
  "doctor_names": "Name without titles, or empty string"
}}

Return ONLY this JSON object, no markdown, no explanations."""


def get_main_vlm_prompt(idx, total_pages):
    return f"""You are an expert medical data digitizer specializing in Arabic and English medical reports.

You receive a medical report IMAGE (page {idx}/{total_pages}).

Your PRIMARY goal: Extract LAB DATA with PERFECT ROW ALIGNMENT - never mix values between different rows.
IMPORTANT: Do NOT extract patient personal info (name, gender, etc.) - that is handled separately.

═══════════════════════════════════════════════════════════════════
🚨 CRITICAL ERROR PREVENTION - READ THIS FIRST! 🚨
═══════════════════════════════════════════════════════════════════

MOST COMMON MISTAKES (YOU MUST AVOID):

❌ ERROR #1: Taking a value from Row 2 and putting it with test name from Row 1
   Example of WRONG:
   - Row 1: "Lymphocytes" | "2.9" | "K/uL" | "(1.5-7.5)"  ← These values are from DIFFERENT rows!
   - Row 2: "WBC" | "7.1" | "cells/L" | "(4.6-11)"
   
   ✓ CORRECT approach:
   - Follow the horizontal line of Row 1 ONLY
   - Read ALL values from Row 1 cells
   - Never look at Row 2 when processing Row 1

❌ ERROR #2: Same normal_range appearing for multiple different tests
   Example of WRONG: "Lymphocytes", "WBC", "RBC" all have "(4.6-11)" ← Impossible!
   ✓ CORRECT: Each test has its OWN range - read each row's range column independently

❌ ERROR #3: Wrong units (e.g., "*" as a unit)
   ✓ CORRECT: Units are medical abbreviations like "mg/dl", "g/dL", "%", "K/uL" - not symbols

❌ ERROR #4: Mixing Arabic and English values in same field
   ✓ CORRECT: If you see both Arabic and English versions of the same test, choose the clearer one consistently

═══════════════════════════════════════════════════════════════════
FOUNDATION RULES
═══════════════════════════════════════════════════════════════════

1. ACCURACY OVER COMPLETION:
   - Read values EXACTLY as written - never guess or assume
   - If ANY field is unclear → return empty string ""
   - Empty is ALWAYS better than wrong

2. ROW INDEPENDENCE (MOST CRITICAL!):
   - Process each table row in COMPLETE ISOLATION
   - Never look at adjacent rows when reading a cell
   - Each row is like a separate document

3. LANGUAGE SUPPORT (ARABIC + ENGLISH):
   - Handle both Arabic (right-to-left) and English (left-to-right) tables
   - For Arabic text, remember layout is reversed from English
   - Choose the clearer/more legible test name when both languages present

═══════════════════════════════════════════════════════════════════
STEP 1: LOCATE AND IDENTIFY TABLE STRUCTURE
═══════════════════════════════════════════════════════════════════

1.1 Find the lab results table
   - Look for: Headers with test names, results, units, ranges
   - Common headers in Arabic: "الفحص", "النتيجة", "الوحدة", "المعدل الطبيعي"
   - Common headers in English: "Test", "Result", "Unit", "Normal Range"

1.2 Identify column positions
   - Column 1: Test name
   - Column 2: Result value
   - Column 3: Unit
   - Column 4: Normal range
   (Some tables may have additional columns like Flags, Status, etc. - ignore those)

1.3 Count total rows to extract
   - Note how many test rows you see (excluding header)

═══════════════════════════════════════════════════════════════════
STEP 2: EXTRACT LAB RESULTS - CRITICAL ROW-BY-ROW PROCESS
═══════════════════════════════════════════════════════════════════

🎯 GOAL: Extract each row PERFECTLY aligned - all values from SAME row

2.1 ROW-BY-ROW EXTRACTION PROTOCOL
───────────────────────────────────

🚨 CRITICAL METHOD: Extract each row as an ISOLATED unit

For EACH test row, follow this STRICT process:

┌─────────────────────────────────────────────────────────────┐
│ STEP-BY-STEP ROW EXTRACTION (Do this for EVERY row)        │
└─────────────────────────────────────────────────────────────┘

STEP 1: IDENTIFY THIS ROW'S BOUNDARIES
   - Locate the horizontal line above this row
   - Locate the horizontal line below this row
   - Everything between these lines = THIS ROW
   - Ignore ALL other rows for now

STEP 2: READ TEST NAME (Column 1 of THIS ROW)
   - Look at Column 1 (leftmost in English, rightmost in Arabic)
   - Read the test name in THIS row only
   - Example: "White blood cells" or "Lymphocytes"
   - Store as: field_name

STEP 3: READ RESULT VALUE (Column 2 of THIS ROW)
   ⚠️ CRITICAL: Follow the horizontal line from field_name
   
   - Start at the test name you just read
   - Follow the SAME horizontal line to Column 2
   - Read ONLY the value in THIS row's Column 2 cell
   
   EMPTY DETECTION (return "" for these):
   ✗ Blank/empty cell
   ✗ Only dashes: "-", "--", "—"
   ✗ Only symbols: "*", "**", ".", ".."
   ✗ Placeholders: "N/A", "n/a", "NA", "nil"
   
   VALID VALUES:
   ✓ Numbers: "109", "12.6", "7.1"
   ✓ Text results: "Positive", "Negative"
   
   Store as: field_value
   
   🚨 IF CELL IS EMPTY: field_value = "" (DO NOT look at other rows!)

STEP 4: READ UNIT (Column 3 of THIS ROW)
   - Continue following the SAME horizontal line to Column 3
   - Read ONLY the unit in THIS row's Column 3 cell
   
   Common valid units:
   ✓ "mg/dl", "g/dL", "%", "K/uL", "M/uL", "fL", "pg", "U/L", "cells/L", "mmol/L"
   
   NOT valid units:
   ✗ "*", "**", "-", "." (these are symbols, not units)
   
   If cell is empty or contains only symbols: field_unit = ""
   
   Store as: field_unit

STEP 5: READ NORMAL RANGE (Column 4 of THIS ROW)
   ⚠️ ULTRA CRITICAL: This is where most errors happen!
   
   - Continue following the SAME horizontal line to Column 4
   - Read ONLY the range in THIS row's Column 4 cell
   - Do NOT look at Column 4 of any other row
   
   EMPTY DETECTION (return "" for these):
   ✗ Blank/empty cell
   ✗ Only dashes: "-", "--", "—", "(-)"
   ✗ Only symbols: "*", "**", ".", "(*)", "(.)"
   ✗ "N/A", "n/a", "NA"
   
   VALID RANGES (must contain numbers):
   ✓ "(74-110)", "(0-200)", "(12-16)", "(27-31.2)"
   ✓ "74-110", "0-200" (without parentheses)
   ✓ "(0.5-0.9)", "(4.6-11)" (with decimals)
   ✓ "<100", ">50", "Up to 200" (with text)
   
   🚨 CRITICAL CHECKS:
   - Does this range make sense for THIS test name?
   - Is this the EXACT SAME range as the previous row?
     → If yes, you made a mistake! Re-check the alignment.
   - Examples of WRONG (impossible to have same range):
     * Lymphocytes with "(4.6-11)" ✓ correct
     * WBC with "(4.6-11)" ✓ might be correct
     * RBC with "(4.6-11)" ✗ WRONG! RBC range is typically (4.1-5.5)
     * Hemoglobin with "(4.6-11)" ✗ WRONG! Hgb range is typically (12-16)
   
   Store as: normal_range

STEP 6: CALCULATE is_normal
   Decision tree:
   
   IF field_value == "" OR normal_range == "":
       is_normal = null
   
   ELSE IF field_value is non-numeric (like "Positive"):
       is_normal = null
   
   ELSE IF normal_range has no parseable numbers:
       is_normal = null
   
   ELSE:
       Extract number from field_value
       Extract min/max from normal_range
       
       IF min <= value <= max:
           is_normal = true
       ELSE:
           is_normal = false

STEP 7: EXTRACT CATEGORY (if table has sections)
   - If row is under a section header like "HEMATOLOGY": category = "HEMATOLOGY"
   - Otherwise: category = ""

STEP 8: EXTRACT NOTES
   - Any flags, comments, or additional info in this row
   - Otherwise: notes = ""

STEP 9: MOVE TO NEXT ROW
   - Repeat STEP 1-8 for the next row
   - Treat the next row as completely independent

2.2 VALIDATION CHECKS FOR EACH ROW
───────────────────────────────────

Before adding this row to medical_data, verify:

□ field_name is NOT empty (every row needs a test name)
□ field_value is from THIS row, not another row
□ field_unit is a valid medical unit (not "*" or "-")
□ normal_range is from THIS row's range column
□ If normal_range is NOT empty, it contains actual numbers
□ is_normal = null if field_value or normal_range is empty

🚨 RED FLAGS (indicates you made a mistake):
- Multiple different tests have the EXACT same normal_range
  Example: Lymphocytes, WBC, and RBC all have "(4.6-11)" → WRONG!
- Unit is "*" or "-" → WRONG! These are not units
- field_value from one row matches field_unit from another row → WRONG!

2.3 SPECIAL CASES
─────────────────

Case 1: SLANTED OR HANDWRITTEN LINES
   - Carefully trace each row's horizontal line
   - Use the test name position as the anchor
   - Follow the slant of the line to other columns

Case 2: EMPTY CELLS IN MIDDLE OF ROW
   - If result cell is empty but test name exists: field_value = ""
   - If unit cell is empty: field_unit = ""
   - If range cell is empty: normal_range = ""
   - DO NOT fill from adjacent rows!

Case 3: MERGED CELLS
   - If a value spans multiple rows, only attribute it to the first row
   - Leave other rows empty for that field

Case 4: MULTIPLE SECTIONS
   - Process each section independently
   - Use section header as category for all rows in that section

═══════════════════════════════════════════════════════════════════
STEP 3: SELF-VALIDATION AND RECHECKING
═══════════════════════════════════════════════════════════════════

⚠️ CRITICAL: Before finalizing your extraction, perform these checks:

3.1 DUPLICATE RANGE CHECK (Most common error!)
──────────────────────────────────────────────

Go through your extracted data:
- Find all the normal_ranges you extracted
- Check if ANY two DIFFERENT test names share the EXACT same range
- Example RED FLAG: "Lymphocytes" = "(4.6-11)" AND "WBC" = "(4.6-11)"
  → This is suspicious! Re-examine the image carefully.
  → Go back to that row and trace it again - you probably mixed rows.

3.2 UNIT REASONABLENESS CHECK
──────────────────────────────

For each extracted row:
- Does the unit make sense for this test?
- Unit should be a medical abbreviation, NOT a symbol
- If unit is "*", "-", or blank for a numeric result → WRONG!
- Re-check that row

3.3 VALUE-RANGE SANITY CHECK
──────────────────────────────

For tests with numeric values AND ranges:
- Does the value fall roughly in the expected range?
- If value = "150" and range = "(1.5-7.5)" → WRONG! Probably different rows
- If value = "12.6" and range = "(12-16)" → Looks reasonable
- If any value seems impossibly far from its range → re-examine that row

3.4 RE-SCAN UNCERTAIN ROWS
────────────────────────────

If ANY of the above checks found problems:
1. Carefully re-examine the image
2. Re-trace the horizontal lines for suspicious rows
3. Verify you're reading from the SAME row
4. Correct the data in your JSON

DO THIS UNTIL YOU ARE 100% CONFIDENT the data is correct.

═══════════════════════════════════════════════════════════════════
STEP 4: FINAL QUALITY CHECKS
═══════════════════════════════════════════════════════════════════

Before returning JSON, verify:

MEDICAL DATA CHECKS:
□ Each row has field_name (not empty)
□ No two DIFFERENT tests share the EXACT same normal_range
   (unless they're related tests like "Neutrophils" and "Neutrophils%")
□ Units are valid medical abbreviations, not symbols like "*" or "-"
□ field_value matches the test (e.g., Hemoglobin ~12-16, not ~7.1)
□ is_normal = null when field_value or normal_range is empty

COMMON SENSE CHECKS:
□ WBC (White blood cells) range is typically (4-11) K/uL or similar
□ RBC (Red blood cells) range is typically (4-5.5) M/uL or similar
□ Hemoglobin range is typically (12-16) g/dL or similar
□ If you see the SAME range for WBC and Hemoglobin → YOU MADE A MISTAKE!

═══════════════════════════════════════════════════════════════════
STEP 5: JSON OUTPUT FORMAT
═══════════════════════════════════════════════════════════════════

Return EXACTLY one JSON object. No markdown, no ```json, no explanations.

{{
  "medical_data": [
    {{
      "field_name": "string (test name from Column 1 of this row)",
      "field_value": "string (value from Column 2 of SAME row, or \"\")",
      "field_unit": "string (unit from Column 3 of SAME row, or \"\")",
      "normal_range": "string (range from Column 4 of SAME row, or \"\")",
      "is_normal": true or false or null,
      "category": "string (section name or \"\")",
      "notes": "string (additional info or \"\")"
    }}
  ]
}}

═══════════════════════════════════════════════════════════════════
FINAL CRITICAL REMINDERS
═══════════════════════════════════════════════════════════════════

1. 🎯 PERFECT ROW ALIGNMENT IS YOUR #1 PRIORITY
   - All values in one JSON object must come from the SAME row
   - Never mix Column 2 from Row A with Column 4 from Row B

2. 📊 EACH TEST HAS ITS OWN UNIQUE RANGE
   - Lymphocytes ≠ Hemoglobin ≠ WBC ranges
   - If you see duplicate ranges across different test types → Check again for errors!

3. ❌ EMPTY IS BETTER THAN WRONG
   - If uncertain, return ""
   - Never guess or assume

4. ⚠️ SELF-VALIDATE YOUR WORK (CRITICAL!)
   - Check for red flags before returning
   - Use common sense (does this value make sense for this test?)
   - Re-examine rows if duplicate ranges detected
   - Verify row alignment multiple times

5. 🌐 HANDLE BOTH ARABIC AND ENGLISH
   - Process left-to-right (English) and right-to-left (Arabic) text correctly
   - Choose clearer/more complete data if both languages present
   - Apply same alignment rules regardless of language

Now carefully extract the data from the image and return ONLY the medical_data JSON (no patient info).
"""
───────────────────────────────────

🚨 CRITICAL METHOD: Extract each row as an ISOLATED unit

For EACH test row, follow this STRICT process:

┌─────────────────────────────────────────────────────────────┐
│ STEP-BY-STEP ROW EXTRACTION (Do this for EVERY row)        │
└─────────────────────────────────────────────────────────────┘

STEP 1: IDENTIFY THIS ROW'S BOUNDARIES
   - Locate the horizontal line above this row
   - Locate the horizontal line below this row
   - Everything between these lines = THIS ROW
   - Ignore ALL other rows for now

STEP 2: READ TEST NAME (Column 1 of THIS ROW)
   - Look at Column 1 (leftmost in English, rightmost in Arabic)
   - Read the test name in THIS row only
   - Example: "White blood cells" or "Lymphocytes"
   - Store as: field_name

STEP 3: READ RESULT VALUE (Column 2 of THIS ROW)
   ⚠️ CRITICAL: Follow the horizontal line from field_name
   
   - Start at the test name you just read
   - Follow the SAME horizontal line to Column 2
   - Read ONLY the value in THIS row's Column 2 cell
   
   EMPTY DETECTION (return "" for these):
   ✗ Blank/empty cell
   ✗ Only dashes: "-", "--", "—"
   ✗ Only symbols: "*", "**", ".", ".."
   ✗ Placeholders: "N/A", "n/a", "NA", "nil"
   
   VALID VALUES:
   ✓ Numbers: "109", "12.6", "7.1"
   ✓ Text results: "Positive", "Negative"
   
   Store as: field_value
   
   🚨 IF CELL IS EMPTY: field_value = "" (DO NOT look at other rows!)

STEP 4: READ UNIT (Column 3 of THIS ROW)
   - Continue following the SAME horizontal line to Column 3
   - Read ONLY the unit in THIS row's Column 3 cell
   
   Common valid units:
   ✓ "mg/dl", "g/dL", "%", "K/uL", "M/uL", "fL", "pg", "U/L", "cells/L", "mmol/L"
   
   NOT valid units:
   ✗ "*", "**", "-", "." (these are symbols, not units)
   
   If cell is empty or contains only symbols: field_unit = ""
   
   Store as: field_unit

STEP 5: READ NORMAL RANGE (Column 4 of THIS ROW)
   ⚠️ ULTRA CRITICAL: This is where most errors happen!
   
   - Continue following the SAME horizontal line to Column 4
   - Read ONLY the range in THIS row's Column 4 cell
   - Do NOT look at Column 4 of any other row
   
   EMPTY DETECTION (return "" for these):
   ✗ Blank/empty cell
   ✗ Only dashes: "-", "--", "—", "(-)"
   ✗ Only symbols: "*", "**", ".", "(*)", "(.)"
   ✗ "N/A", "n/a", "NA"
   
   VALID RANGES (must contain numbers):
   ✓ "(74-110)", "(0-200)", "(12-16)", "(27-31.2)"
   ✓ "74-110", "0-200" (without parentheses)
   ✓ "(0.5-0.9)", "(4.6-11)" (with decimals)
   ✓ "<100", ">50", "Up to 200" (with text)
   
   🚨 CRITICAL CHECKS:
   - Does this range make sense for THIS test name?
   - Is this the EXACT SAME range as the previous row?
     → If yes, you made a mistake! Re-check the alignment.
   - Examples of WRONG (impossible to have same range):
     * Lymphocytes with "(4.6-11)" ✓ correct
     * WBC with "(4.6-11)" ✓ might be correct
     * RBC with "(4.6-11)" ✗ WRONG! RBC range is typically (4.1-5.5)
     * Hemoglobin with "(4.6-11)" ✗ WRONG! Hgb range is typically (12-16)
   
   Store as: normal_range

STEP 6: CALCULATE is_normal
   Decision tree:
   
   IF field_value == "" OR normal_range == "":
       is_normal = null
   
   ELSE IF field_value is non-numeric (like "Positive"):
       is_normal = null
   
   ELSE IF normal_range has no parseable numbers:
       is_normal = null
   
   ELSE:
       Extract number from field_value
       Extract min/max from normal_range
       
       IF min <= value <= max:
           is_normal = true
       ELSE:
           is_normal = false

STEP 7: EXTRACT CATEGORY (if table has sections)
   - If row is under a section header like "HEMATOLOGY": category = "HEMATOLOGY"
   - Otherwise: category = ""

STEP 8: EXTRACT NOTES
   - Any flags, comments, or additional info in this row
   - Otherwise: notes = ""

STEP 9: MOVE TO NEXT ROW
   - Repeat STEP 1-8 for the next row
   - Treat the next row as completely independent

2.3 VALIDATION CHECKS FOR EACH ROW
───────────────────────────────────

Before adding this row to medical_data, verify:

□ field_name is NOT empty (every row needs a test name)
□ field_value is from THIS row, not another row
□ field_unit is a valid medical unit (not "*" or "-")
□ normal_range is from THIS row's range column
□ If normal_range is NOT empty, it contains actual numbers
□ is_normal = null if field_value or normal_range is empty

🚨 RED FLAGS (indicates you made a mistake):
- Multiple different tests have the EXACT same normal_range
  Example: Lymphocytes, WBC, and RBC all have "(4.6-11)" → WRONG!
- Unit is "*" or "-" → WRONG! These are not units
- field_value from one row matches field_unit from another row → WRONG!

2.4 SPECIAL CASES
─────────────────

Case 1: SLANTED OR HANDWRITTEN LINES
   - Carefully trace each row's horizontal line
   - Use the test name position as the anchor
   - Follow the slant of the line to other columns

Case 2: EMPTY CELLS IN MIDDLE OF ROW
   - If result cell is empty but test name exists: field_value = ""
   - If unit cell is empty: field_unit = ""
   - If range cell is empty: normal_range = ""
   - DO NOT fill from adjacent rows!

Case 3: MERGED CELLS
   - If a value spans multiple rows, only attribute it to the first row
   - Leave other rows empty for that field

Case 4: MULTIPLE SECTIONS
   - Process each section independently
   - Use section header as category for all rows in that section

═══════════════════════════════════════════════════════════════════
STEP 3: FINAL QUALITY CHECKS
═══════════════════════════════════════════════════════════════════

Before returning JSON, verify:

PATIENT INFO CHECKS:
□ patient_name is NOT empty (unless truly not found after thorough search)
□ patient_gender is "Male" or "Female" or "" (not Arabic text)
□ patient_name ≠ doctor_names (they are different people!)
□ Dates are in "YYYY-MM-DD" format

MEDICAL DATA CHECKS:
□ Each row has field_name (not empty)
□ No two DIFFERENT tests share the EXACT same normal_range
   (unless they're related tests like "Neutrophils" and "Neutrophils%")
□ Units are valid medical abbreviations, not symbols like "*" or "-"
□ field_value matches the test (e.g., Hemoglobin ~12-16, not ~7.1)
□ is_normal = null when field_value or normal_range is empty

COMMON SENSE CHECKS:
□ WBC (White blood cells) range is typically (4-11) K/uL or similar
□ RBC (Red blood cells) range is typically (4-5.5) M/uL or similar
□ Hemoglobin range is typically (12-16) g/dL or similar
□ If you see the SAME range for WBC and Hemoglobin → YOU MADE A MISTAKE!

═══════════════════════════════════════════════════════════════════
STEP 4: JSON OUTPUT FORMAT
═══════════════════════════════════════════════════════════════════

Return EXACTLY one JSON object. No markdown, no ```json, no explanations.

{{
  "patient_name": "string (full name in original language, no prefixes)",
  "patient_age": "string (number only like \"50\" or \"\")",
  "patient_dob": "string (YYYY-MM-DD or \"\")",
  "patient_gender": "string (\"Male\" or \"Female\" or \"\")",
  "report_date": "string (YYYY-MM-DD or \"\")",
  "report_type": "string (e.g., \"Complete Blood Count\" or \"\")",
  "doctor_names": "string (comma-separated or \"\")",
  "medical_data": [
    {{
      "field_name": "string (test name from Column 1 of this row)",
      "field_value": "string (value from Column 2 of SAME row, or \"\")",
      "field_unit": "string (unit from Column 3 of SAME row, or \"\")",
      "normal_range": "string (range from Column 4 of SAME row, or \"\")",
      "is_normal": true or false or null,
      "category": "string (section name or \"\")",
      "notes": "string (additional info or \"\")"
    }}
  ]
}}

═══════════════════════════════════════════════════════════════════
FINAL CRITICAL REMINDERS
═══════════════════════════════════════════════════════════════════

1. 🎯 PERFECT ROW ALIGNMENT IS YOUR #1 PRIORITY
   - All values in one JSON object must come from the SAME row
   - Never mix Column 2 from Row A with Column 4 from Row B

2. � EACH TEST HAS ITS OWN UNIQUE RANGE
   - Lymphocytes ≠ Hemoglobin ≠ WBC ranges
   - If you see duplicate ranges across different test types → Check again for errors!

3. ❌ EMPTY IS BETTER THAN WRONG
   - If uncertain, return ""
   - Never guess or assume

4. ⚠️ SELF-VALIDATE YOUR WORK (CRITICAL!)
   - Check for red flags before returning
   - Use common sense (does this value make sense for this test?)
   - Re-examine rows if duplicate ranges detected
   - Verify row alignment multiple times

5. 🌐 HANDLE BOTH ARABIC AND ENGLISH
   - Process left-to-right (English) and right-to-left (Arabic) text correctly
   - Choose clearer/more complete data if both languages present
   - Apply same alignment rules regardless of language

Now carefully extract the data from the image and return ONLY the medical_data JSON (no patient info).
"""


def get_table_retry_prompt(idx, total_pages):
    return f"""You are reading a medical LAB REPORT image (page {idx}/{total_pages}). 
The report may be in ENGLISH or ARABIC or BOTH.
Tables may have handwritten lines, slanted lines, or unclear alignment.

⚠️ CRITICAL - READ SLOWLY AND CAREFULLY:
1. Process ONE row at a time - do NOT mix rows
2. Follow the horizontal line of EACH row carefully (even if slanted)
3. If a cell in THIS row is empty, it's EMPTY - do NOT take value from row above/below
4. If normal_range cell is "-", "(-)", "*", or blank, return "" - do NOT invent values
5. VALIDATE: Check if ANY two different tests have the same range - if yes, you made a mistake!

HOW TO READ TABLES:
- Identify column headers first: "الفحص", "النتيجة", "الوحدة", "المعدل الطبيعي" (Arabic) or "Test", "Result", "Unit", "Normal Range" (English)
- For EACH row, trace the horizontal line from left to right
- Read values ONLY from cells that align with THIS row's horizontal line

EXTRACTION RULES FOR EACH ROW:
1. field_name: Read from test name column in THIS ROW
2. field_value: Read from result column in THIS ROW (same horizontal line as field_name)
   - If empty, "-", "*", blank → return ""
   - Do NOT use value from row above or below
3. field_unit: Read from unit column in THIS ROW
4. normal_range: Read from range column in THIS ROW
   - If empty, "-", "(-)", "*", or any symbol without numbers → return ""
   - DO NOT copy from another row
   - DO NOT invent range values
5. is_normal: 
   - null if field_value is "" OR normal_range is ""
   - true/false ONLY if both have valid numbers

EMPTY DETECTION:
- field_value is EMPTY if: blank, "-", "--", "*", ".", "N/A", "n/a"
- normal_range is EMPTY if: blank, "-", "(-)", "*", any symbol without numbers
- When empty, return "" (empty string), do NOT guess

SELF-VALIDATION:
- Before returning, check: Do any 2 different tests share the EXACT same range?
- If yes, you made an alignment error - go back and re-check those rows!

Return JSON with this structure only:
{{
  "medical_data": [
    {{
      "field_name": "Test name (prefer English if available)",
      "field_value": "numeric value as string, or \"\" if empty/missing",
      "field_unit": "unit string, or \"\"",
      "normal_range": "range like \"(12-16)\", or \"\" if missing/empty",
      "is_normal": true or false or null (null if missing range or value),
      "category": "section name like \"HEMATOLOGY\" or \"\"",
      "notes": "any notes or \"\""
    }}
  ]
}}
Return ONLY this JSON object, no markdown."""
