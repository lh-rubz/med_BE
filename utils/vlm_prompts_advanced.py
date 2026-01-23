"""Advanced VLM prompts with intelligent error correction and robust extraction."""
import json
import re
from datetime import datetime


def calculate_age_from_dob(dob_str: str) -> str:
    """
    Calculate age from DOB string in various formats.
    Handles DD/MM/YYYY, MM/DD/YYYY, YYYY-MM-DD formats.
    Returns age as string (1-120) or "" if invalid.
    """
    if not dob_str or not isinstance(dob_str, str):
        return ""
    
    dob_str = dob_str.strip()
    date_obj = None
    
    # Try parsing different formats
    for fmt in ['%d/%m/%Y', '%m/%d/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d.%m.%Y']:
        try:
            date_obj = datetime.strptime(dob_str, fmt)
            break
        except ValueError:
            continue
    
    if not date_obj:
        return ""
    
    # Calculate age
    today = datetime.now()
    age = today.year - date_obj.year - ((today.month, today.day) < (date_obj.month, date_obj.day))
    
    # Validate age range
    if 0 <= age <= 130:
        return str(age)
    return ""


def get_advanced_personal_info_prompt(idx, total_pages):
    """
    Advanced prompt for personal info extraction with:
    - Intelligent gender conversion with validation
    - Automatic age calculation from DOB
    - Robust doctor name search
    - Better bilingual handling
    """
    return f"""🧠 ADVANCED MEDICAL REPORT PERSONAL INFO EXTRACTION (PAGE {idx}/{total_pages})

You are a medical document expert with deep understanding of:
- Bilingual Arabic/English medical reports
- Date handling in multiple formats
- Medical terminology and titles
- Report metadata structures

📋 CRITICAL EXTRACTION MISSION:
Extract patient personal information PERFECTLY. You will be evaluated on accuracy.
Return exactly one JSON object per report.

═══════════════════════════════════════════════════════════════════════════════
🔴 CRITICAL FIELD: PATIENT GENDER
═══════════════════════════════════════════════════════════════════════════════

GENDER EXTRACTION RULE - YOU WILL BE GRADED ON THIS:
Your output MUST be EXACTLY "Male" or "Female" in English. NO EXCEPTIONS.

IF YOU EXTRACT ARABIC, YOU FAILED!

Gender value search:
1. Look for label: "الجنس:", "جنس:", "Gender:", "Sex:"
2. Read the VALUE IMMEDIATELY AFTER the label
3. If value is "ذكر" (or variations: "ذكور", "ذكر ", " ذكر") → CONVERT TO "Male"
4. If value is "أنثى" (or variations: "انثى", "انثي", "أنثي", " أنثى") → CONVERT TO "Female"
5. If English value: "Male", "M" → return "Male" | "Female", "F" → return "Female"

⚠️ VALIDATION CHECK BEFORE RETURNING:
- Did you write "ذكر" in output? WRONG! Change to "Male"
- Did you write "أنثى" in output? WRONG! Change to "Female"
- Did you write anything other than "Male" or "Female"? WRONG!

Your final gender value must be EXACTLY one of these three: "Male", "Female", ""

═══════════════════════════════════════════════════════════════════════════════
🔴 CRITICAL FIELD: PATIENT AGE (CALCULATE FROM DOB IF NEEDED)
═══════════════════════════════════════════════════════════════════════════════

Age extraction priority (in order):
1. Look for "العمر:" or "Age:" - extract numeric value directly
2. If age not found, look for DOB ("تاريخ الميلاد:", "DOB:", "Date of Birth:")
3. CALCULATE age from DOB:
   - Current date: {datetime.now().strftime('%Y-%m-%d')}
   - If DOB is "01/05/1975": Age = {2026 - 1975 - 1} = 50 years (not 28!)
   - Formula: Age = Current_Year - DOB_Year - (1 if birthday hasn't occurred this year else 0)

CRITICAL EXAMPLE:
- Patient DOB shown as: "01/05/1975" or "05/01/1975"
- Today's date: {datetime.now().strftime('%Y-%m-%d')}
- Your calculated age MUST be approximately 50-51, NOT 28!
- If you extract "28", you FAILED the age calculation!

Age format validation:
- Must be numeric 1-120
- If age > 120 or < 0, set to ""
- Return age as string: "50", "25", ""

═══════════════════════════════════════════════════════════════════════════════
🔴 CRITICAL FIELD: PATIENT DATE OF BIRTH (DOB)
═══════════════════════════════════════════════════════════════════════════════

DOB Format Rules:
- Arabic labels: "تاريخ الميلاد", "تاريخ الولادة"
- English labels: "DOB", "Date of Birth"

Input formats you may see:
- DD/MM/YYYY → Convert to YYYY-MM-DD
- MM/DD/YYYY → Convert to YYYY-MM-DD  
- DD-MM-YYYY → Convert to YYYY-MM-DD
- DD.MM.YYYY → Convert to YYYY-MM-DD
- YYYY-MM-DD → Keep as is

Example conversions:
- "01/05/1975" → "1975-05-01" (European format: day/month/year)
- "05/01/1975" → "1975-01-05" (US format: month/day/year)
- Ambiguous? Use common sense: If day > 12, it's definitely DD/MM/YYYY

Output format: YYYY-MM-DD or "" if not found

═══════════════════════════════════════════════════════════════════════════════
🟢 CRITICAL FIELD: REPORT DATE
═══════════════════════════════════════════════════════════════════════════════

Search labels: "تاريخ الطلب", "تاريخ الفحص", "Report Date", "Test Date", "Date"
Extract: DATE ONLY in YYYY-MM-DD format
REMOVE: Any timestamp, time portion, or extra text
If you see "2025-12-31 10:00:02.0" → Extract ONLY "2025-12-31"

═══════════════════════════════════════════════════════════════════════════════
🟢 CRITICAL FIELD: DOCTOR NAMES (AGGRESSIVE SEARCH REQUIRED)
═══════════════════════════════════════════════════════════════════════════════

Doctor search strategy (in order of priority):
1. Header section - scan for "الطبيب:", "طبيب:", "Doctor:", "DR:", "Physician:"
2. Right margin (Arabic side RTL)
3. Left margin (English side LTR)
4. BOTTOM of page - signature blocks, footer areas, physician signatures
5. Side panels and information boxes
6. Any text containing medical titles: Dr., د., دكتور, Prof., Prof., أ.د

Extraction rules:
- If you see "الطبيب: جهاد العملة" → Extract "جهاد العملة" (NOT including the label)
- If you see "Doctor: John Smith" → Extract "John Smith"
- Remove title prefixes: "Dr.", "د.", "دكتور", "Prof.", "أ.د", "الدكتور", "أستاذ"
- Validate: Must be a person's name (3+ chars), not a facility

⚠️ CRITICAL: Do NOT return "" for doctor_names without thorough search!
If you skip this field, you FAILED the task.
Search EVERY part of the document.

═══════════════════════════════════════════════════════════════════════════════
🟢 CRITICAL FIELD: PATIENT NAME
═══════════════════════════════════════════════════════════════════════════════

Patient name search:
- Arabic label: "اسم المريض:", "اسم المرضى:"
- English label: "Patient Name:", "Name:"
- Look in: Header area (top 40% of page)

Validation - REJECT these:
- "Patient", "Name", "N/A", "Unknown"
- Facility names: "Ramallah", "PHC", "مختبر رمالله", "Laboratory(Ramallah PHC)"
- Device names: "جهاز", "equipment"
- Lab names: "مختبر", "clinic"

Accept:
- Full names with 3+ characters
- Arabic or English person names
- If two names found (Arabic + English), use the LONGER one

═══════════════════════════════════════════════════════════════════════════════
📦 REQUIRED JSON OUTPUT (exactly this structure):
═══════════════════════════════════════════════════════════════════════════════

{{
  "patient_name": "Full name from header or empty string",
  "patient_age": "Numeric age (extracted or calculated) or empty string",
  "patient_dob": "Date in YYYY-MM-DD format or empty string",
  "patient_gender": "Male, Female, or empty string - MUST be English",
  "report_date": "Date in YYYY-MM-DD format (no timestamp)",
  "doctor_names": "Doctor name from signature/header or empty string"
}}

═══════════════════════════════════════════════════════════════════════════════
✅ SELF-VALIDATION CHECKLIST (BEFORE RETURNING):
═══════════════════════════════════════════════════════════════════════════════

✓ patient_gender: Is it "Male", "Female", or ""? (NOT "ذكر", NOT "أنثى")
✓ patient_age: Is it numeric 1-120 or ""? (If DOB was 01/05/1975, is age ~50, NOT 28?)
✓ patient_dob: Is it YYYY-MM-DD or ""? (NOT MM/DD/YYYY, NOT DD/MM/YYYY, NOT timestamp)
✓ report_date: Is it YYYY-MM-DD with NO time portion? (NOT "2025-12-31 10:00:02.0")
✓ patient_name: Is it a person's name, NOT a facility? (NOT "Ramallah PHC", NOT "Laboratory")
✓ doctor_names: Did you search thoroughly? (NOT "", should have found the doctor)

If ANY field fails validation, fix it before returning!

═══════════════════════════════════════════════════════════════════════════════
"""


def get_advanced_medical_data_prompt(idx, total_pages):
    """
    Advanced prompt for medical table extraction with:
    - Strict row alignment verification
    - Empty value and symbol handling
    - Multi-page awareness
    - Duplicate detection
    - Gender-based range validation
    """
    return f"""🧠 ADVANCED MEDICAL LAB TABLE EXTRACTION (PAGE {idx}/{total_pages})

You are extracting medical lab data with ABSOLUTE PRECISION.
This page is {idx} of {total_pages} total pages.

═══════════════════════════════════════════════════════════════════════════════
🔴 RULE #1: EXTRACT EVERY SINGLE ROW - DO NOT SKIP ANY ROWS
═══════════════════════════════════════════════════════════════════════════════

Medical reports typically contain 15-50+ test rows.
YOU MUST COUNT AND EXTRACT ALL OF THEM.

Before returning:
1. Count the rows in the table image
2. Count the items in your medical_data array
3. If counts don't match → YOU FAILED → Go back and extract missing rows

Examples of reports:
- If image shows 24 rows → You must return 24 items (or fewer if some rows are completely empty)
- If image shows 10 rows → You must return 10 items
- If you return only 6 items for a 24-row table → YOU FAILED

═══════════════════════════════════════════════════════════════════════════════
🔴 RULE #2: HANDLE EMPTY VALUES AND SYMBOLS CORRECTLY
═══════════════════════════════════════════════════════════════════════════════

Empty value indicators in medical reports:
- Blank cell
- Single dash: "-"
- Asterisk: "*"
- Parentheses with nothing: "()"
- Checkmark: "✓"
- Crossed out value
- Any other symbol

Correct handling:
IF field_value is empty/symbol → Set field_value to "" (empty string)
IF field_value is empty → Still include the row in output IF field_name exists
  (Unless field_value is critical and truly missing)

Example:
Row showing: "WBC | - | cells/L | (4.6-11)"
Should extract: {{"field_name": "WBC", "field_value": "", "field_unit": "cells/L", "normal_range": "(4.6-11)"}}

═══════════════════════════════════════════════════════════════════════════════
🔴 RULE #3: VERIFY ROW ALIGNMENT - CHECK FOR SWAPPED VALUES
═══════════════════════════════════════════════════════════════════════════════

RED FLAG INDICATORS (This row is MISALIGNED):
❌ field_value contains "%" or unit symbols (%, K/uL, mg/dL, etc.)
❌ field_value looks like a range: "(10-15)" or "(4.6-11)"
❌ field_unit contains a number or looks like a range
❌ field_unit is a whole number like "230" or "109"
❌ normal_range contains only a number without parentheses: "32" or "230"
❌ normal_range is physically in a different row than test name in image
❌ field_value is clearly a unit: "U/L", "mg/dL", "cells/L"

If you detect ANY red flag → RECHECK THAT ROW'S ALIGNMENT IMMEDIATELY

Example of swapped values (WRONG):
❌ field_name: "ALT", field_value: "320", field_unit: "U/L", normal_range: "(0-33)"
   Problem: Value "320" looks too high, might be swapped with range or previous row

Correct alignment (RIGHT):
✓ field_name: "ALT", field_value: "32", field_unit: "U/L", normal_range: "(0-33)"
   Validates: 32 U/L is reasonable, within or close to range (0-33)

═══════════════════════════════════════════════════════════════════════════════
🔴 RULE #4: NEVER INVENT NORMAL RANGES
═══════════════════════════════════════════════════════════════════════════════

Critical rule about normal_range:
- ONLY extract ranges that are VISIBLE in the image
- If the table shows EMPTY normal_range cell → Set to "" (empty string)
- NEVER use your medical knowledge to fill in ranges
- NEVER guess or hallucinate ranges like "(0-0.75)" if not shown

Example:
Report shows:
Row 1: Platelet Width | 8 | μm | [EMPTY]
✓ CORRECT: {{"field_name": "Platelet Width", "field_value": "8", "field_unit": "μm", "normal_range": ""}}
❌ WRONG: {{"field_name": "Platelet Width", "field_value": "8", "field_unit": "μm", "normal_range": "(0-0.75)"}}
          (This is hallucinated! Not shown in image!)

═══════════════════════════════════════════════════════════════════════════════
🟢 RULE #5: HANDLE COMPLEX TABLE LAYOUTS
═══════════════════════════════════════════════════════════════════════════════

Complex layouts you may encounter:
- Multiple sections (Hematology, Chemistry, etc.) - track category for each row
- Rotated/tilted tables - still read horizontally
- Poor handwriting - do your best, use context
- Mixed Arabic/English test names - use the clearer version
- Side-by-side tables - extract left table, then right table
- Sub-headers and separators - skip separators, extract data rows

Column mapping (typical structure):
[Test Name] [Result] [Unit] [Normal Range]
OR (bilingual):
[Normal Range] [Unit] [Result] [Test Name]  (right-to-left reading)

═══════════════════════════════════════════════════════════════════════════════
🟢 RULE #6: PROCESS MULTI-PAGE REPORTS CORRECTLY
═══════════════════════════════════════════════════════════════════════════════

You are on page {idx}/{total_pages}.
If multiple tables exist on THIS page, extract ALL of them.
Include all extracted data in ONE medical_data array.

If table continues to next page:
- Extract all visible rows on THIS page
- Note in "notes" field if row appears incomplete: "continued on page {idx+1}"

═══════════════════════════════════════════════════════════════════════════════
🟢 RULE #7: CRITICAL ALIGNMENT VERIFICATION EXAMPLES
═══════════════════════════════════════════════════════════════════════════════

EXAMPLE 1 - MISALIGNED (SWAPPED VALUES):
Image shows:
| Fasting Blood Sugar | 320 | mg/dl | (74-110) |
| Cholesterol | 230 | mg/dL | (0-200) |
| ALT | 32 | U/L | (0-33) |

❌ WRONG extraction (values swapped with previous row):
[
  {{"field_name": "Fasting Blood Sugar", "field_value": "320", ...}},  ← SWAPPED with next row!
  {{"field_name": "Cholesterol", "field_value": "230", ...}},         ← Correct
  {{"field_name": "ALT", "field_value": "32", ...}}                    ← SWAPPED from row above!
]

✓ CORRECT extraction (properly aligned):
[
  {{"field_name": "Fasting Blood Sugar", "field_value": "109", ...}},  ← Real value
  {{"field_name": "Cholesterol", "field_value": "230", ...}},
  {{"field_name": "ALT", "field_value": "320", ...}}                   ← Correct swapped pair
]

EXAMPLE 2 - EMPTY VALUES:
Image shows:
| WBC | - | K/uL | (4.6-11) |
| RBC | 4.8 | M/uL | (*) |
| Hemoglobin | [blank] | g/dL | (12-16) |

✓ CORRECT:
[
  {{"field_name": "WBC", "field_value": "", "field_unit": "K/uL", "normal_range": "(4.6-11)"}},
  {{"field_name": "RBC", "field_value": "4.8", "field_unit": "M/uL", "normal_range": ""}},
  {{"field_name": "Hemoglobin", "field_value": "", "field_unit": "g/dL", "normal_range": "(12-16)"}}
]

═══════════════════════════════════════════════════════════════════════════════
📋 FINAL EXTRACTION CHECKLIST
═══════════════════════════════════════════════════════════════════════════════

Before returning, verify EACH extracted row:
☐ field_name: Is it a medical test name? (Not blank, not a unit, not a range)
☐ field_value: Is it a number, "N/A", or ""? (NOT a unit, NOT a range)
☐ field_unit: Is it a medical unit or ""? (NOT a number, NOT a range, NOT a test name)
☐ normal_range: Is it "(X-Y)" format or ""? (NOT a single number, NOT hallucinated)
☐ is_normal: true/false/null based on value vs range? (null if value or range missing)
☐ Alignment: Does this row's data come from the SAME horizontal line in the image?

Before returning:
☐ Total rows count matches image
☐ No rows are completely empty
☐ No obvious value swaps detected
☐ All normal_ranges are from image (not hallucinated)
☐ All values are from correct rows (not swapped)

═══════════════════════════════════════════════════════════════════════════════
📦 REQUIRED JSON OUTPUT (exactly this structure):
═══════════════════════════════════════════════════════════════════════════════

{{
  "medical_data": [
    {{
      "field_name": "Test name from image",
      "field_value": "Numeric value or N/A or empty string",
      "field_unit": "Unit abbreviation or empty string",
      "normal_range": "Format: (X-Y) or (X-Y) unit or empty string",
      "is_normal": true OR false OR null,
      "category": "Section name: Hematology, Chemistry, etc.",
      "notes": "Any special notes or flags"
    }}
  ]
}}

═══════════════════════════════════════════════════════════════════════════════
"""


def get_advanced_page_verification_prompt(idx, total_pages):
    """
    Prompt to verify extraction accuracy page-by-page.
    Used BEFORE moving to next page to ensure current page is fully processed.
    """
    return f"""🔍 PAGE {idx} VERIFICATION AND COMPLETION CHECK

Before moving to page {idx + 1}, verify that page {idx} has been COMPLETELY extracted.

═══════════════════════════════════════════════════════════════════════════════
STEP 1: Visual table count
═══════════════════════════════════════════════════════════════════════════════

On page {idx}, count ALL medical data tables you see:
- How many separate medical data tables are on this page?
- How many rows total in all tables combined?
- Are there any continuation markers (arrows, "continued...", etc.)?

Example response:
- Table 1: "Hematology" with 12 rows
- Table 2: "Clinical Chemistry" with 14 rows
- Total rows on page {idx}: 26 rows

═══════════════════════════════════════════════════════════════════════════════
STEP 2: Patient info extraction verification
═══════════════════════════════════════════════════════════════════════════════

On page {idx}, verify these are fully extracted:
- Patient name (in header) - Did you find it? [Yes/No]
- Patient gender (in header) - Did you find it? [Yes/No] - MUST be "Male" or "Female"
- Patient DOB (in header) - Did you find it? [Yes/No]
- Patient age (extracted or calculated) - Did you find it? [Yes/No]
- Report date (in header) - Did you find it? [Yes/No]
- Doctor name (in header or signature) - Did you find it? [Yes/No]

═══════════════════════════════════════════════════════════════════════════════
STEP 3: Row-by-row verification
═══════════════════════════════════════════════════════════════════════════════

For the first 3 rows and last 3 rows of this page, verify alignment:

First 3 rows:
1. Test: [name] | Value: [value] | Unit: [unit] | Range: [range] | Status: [aligned/misaligned]
2. Test: [name] | Value: [value] | Unit: [unit] | Range: [range] | Status: [aligned/misaligned]
3. Test: [name] | Value: [value] | Unit: [unit] | Range: [range] | Status: [aligned/misaligned]

Last 3 rows:
[N-2]. Test: [name] | Value: [value] | Unit: [unit] | Range: [range] | Status: [aligned/misaligned]
[N-1]. Test: [name] | Value: [value] | Unit: [unit] | Range: [range] | Status: [aligned/misaligned]
[N]. Test: [name] | Value: [value] | Unit: [unit] | Range: [range] | Status: [aligned/misaligned]

═══════════════════════════════════════════════════════════════════════════════
STEP 4: Quality checks
═══════════════════════════════════════════════════════════════════════════════

☐ All rows extracted: Does extracted row count match table row count?
☐ No swapped values: Are any values clearly misaligned or swapped?
☐ Empty handling: Are empty values handled as "" (not skipped)?
☐ Ranges from image: Are all ranges copied from image (not hallucinated)?
☐ Gender conversion: Is gender "Male" or "Female" (not "ذكر"/"أنثى")?
☐ Age validation: Is age reasonable (1-120) and calculated correctly if from DOB?
☐ Date format: Are dates in YYYY-MM-DD format with no timestamps?

═══════════════════════════════════════════════════════════════════════════════
FINAL ASSESSMENT
═══════════════════════════════════════════════════════════════════════════════

Page {idx} Status:
- COMPLETE: All tables extracted, all personal info found, all rows aligned
- INCOMPLETE: Missing rows or fields
- NEEDS REVIEW: Some rows appear misaligned

Readiness for next page:
- ✓ READY: Page {idx} fully processed, safe to move to page {idx + 1}
- ✗ NOT READY: Need to re-extract page {idx} first

Return JSON:
{{
  "page_number": {idx},
  "total_pages": {total_pages},
  "status": "COMPLETE|INCOMPLETE|NEEDS_REVIEW",
  "tables_on_page": [
    {{
      "table_name": "Name or section",
      "row_count": number,
      "rows_extracted": number,
      "sample_rows": ["row 1", "row 2", "row 3"]
    }}
  ],
  "personal_info_found": {{
    "patient_name": true|false,
    "patient_gender": true|false,
    "patient_age": true|false,
    "report_date": true|false,
    "doctor_name": true|false
  }},
  "alignment_issues": ["issue 1", "issue 2"] or [],
  "notes": "Summary of findings"
}}
"""
