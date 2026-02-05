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
🔬 EXTRACT MEDICAL TABLE DATA - RTL & LTR AWARE
Page {idx}/{total_pages}{page_context}

CRITICAL: This may be a RIGHT-TO-LEFT (RTL) or LEFT-TO-RIGHT (LTR) table.

STEP 0 - EXTRACT HEADER INFORMATION CAREFULLY:
Look at the TOP of the page for patient information table:
- Patient Name (اسم المريض / Name)
- Patient ID (رقم المريض)
- Date of Birth (تاريخ الميلاد) - This is DOB, NOT report date!
- Report Date (تاريخ الطلب / Report Date / Sample Date) - This is the actual report date!
- Doctor Name (الطبيب)
- Gender (الجنس / Sex)

IMPORTANT DATE EXTRACTION:
- "تاريخ الميلاد" or older date (e.g., 1975) = Date of Birth (DOB) → Put in patient_age field
- "تاريخ الطلب" or "Report Date" or recent date (e.g., 2025) = Actual report date → Put in report_date field
- If you see TWO dates: The older one is likely DOB, the recent one is report date
- DO NOT confuse DOB with report date!

STEP 1 - IDENTIFY TABLE DIRECTION:
Look at the table headers and structure:
- If test names are on the RIGHT side → This is RTL (Arabic-style)
- If test names are on the LEFT side → This is LTR (English-style)

STEP 2 - IDENTIFY COLUMN POSITIONS:
For RTL tables (test names on right):
   Position 1 (RIGHTMOST): Test name (English or Arabic)
   Position 2: Result value (number)
   Position 3: Reference range (X-Y format)
   Position 4: Unit (mg/dl, %, etc)
   Position 5 (LEFTMOST): Notes (Arabic or empty)

For LTR tables (test names on left):
   Position 1 (LEFTMOST): Test name
   Position 2: Result value
   Position 3: Unit
   Position 4: Reference range
   Position 5 (RIGHTMOST): Notes

STEP 3 - EXTRACT ROW-BY-ROW (TOP TO BOTTOM, NO SKIPPING):
Start from TOP row, go DOWN. For EACH row:
1. Find test name position (might be followed by a colon ":" or spaces)
2. Move HORIZONTALLY in SAME ROW to find result value (usually the FIRST number after the name)
3. Stay in SAME ROW to find unit and range
4. DO NOT jump to different rows
5. DO NOT extract duplicate test names
6. Extract EVERY single row - even those that look like sub-headers or have special codes (e.g., "Hb A1c", "Lipid Profile")
7. Extract SUB-SECTIONS (e.g., under "DIFFERENTIAL COUNT", extract "Neutrophils", "Lymphocytes", etc.)
8. If test name shows UNIT (e.g., "%"), clarify in field_name (e.g., "Lymphocyte %" vs "Lymphocyte Count")

EXAMPLE - RTL Table (Arabic report):
```
ملاحظات | الوحدة | النتيجة الطبيعية | النتيجة | الفحص
         | mg/dl  | (74-110)        | 109    | Fasting Blood Sugar (FBS)
         | mg/dl  | (0.5-0.9)       | 0.56   | Creatinine,serum
    *    | mg/dl  | (0-200)         | 230    | Cholesterol,Total
         | U/L    | (0-33)          | 32     | Alanine transaminase ALT (GPT)
```
Extract as:
- Row 1: field_name="Fasting Blood Sugar", field_value="109", field_unit="mg/dl", normal_range="(74-110)"
- Row 2: field_name="Creatinine serum", field_value="0.56", field_unit="mg/dl", normal_range="(0.5-0.9)"
- Row 3: field_name="Total Cholesterol", field_value="230", field_unit="mg/dl", normal_range="(0-200)", notes="*"
- Row 4: field_name="Alanine aminotransferase ALT", field_value="32", field_unit="U/L", normal_range="(0-33)"

VALIDATION RULES:
✓ Value must be in SAME horizontal row as test name
✓ The Result is typically the FIRST numeric value after the test name
✓ If you see a * or flag in notes column → add that to notes field exactly as shown
✓ Translate Arabic test names to English (with original in parentheses if helpful)
✓ Translate Arabic units to standard medical units (e.g., "٧/L" becomes "U/L", "mg/dl" remains "mg/dl")
✓ Include unit type in field_name if clarifies (e.g., "Lymphocyte %" vs "Lymphocyte Count")
✓ Extract EVERY row in order top-to-bottom, including all sub-sections
✓ DO NOT extract the same test name twice (skip duplicate rows)
✓ SKIP header rows (containing "Test Name", "Value", "Result", "Unit", etc.)
✗ DO NOT take a value from row above or below
✗ DO NOT jump over the Result column to the Range column
✗ DO NOT confuse DOB (old date like 1975) with report date (recent date like 2025)
✗ DO NOT put square brackets [ ] around names or values

RETURN JSON:
{{
    "patient_name": "actual patient name from header",
    "patient_age": "FULL DATE if you see تاريخ الميلاد or older date like 1975 (format: DD/MM/YYYY or YYYY-MM-DD), otherwise just number",
    "patient_gender": "Male or Female",
    "report_date": "YYYY-MM-DD from تاريخ الطلب or Report Date field ONLY (recent date like 2025, NOT old date like 1975)",
    "report_name": "test type from header",
    "report_type": "Clinical Chemistry / Hematology / etc",
    "doctor_names": "from header",
    "medical_data": [
        {{
            "field_name": "English test name with clarification if needed (e.g., Lymphocyte % or Lymphocyte Count) - unique",
            "field_value": "result from SAME row. INCLUDE symbols like < or > or >= if present in report (e.g., '< 6.0')",
            "field_unit": "unit from SAME row",
            "normal_range": "(X-Y) from SAME row",
            "category": "section name",
            "notes": "exact text from notes column or empty"
        }}
    ]
}}

EXTRACT NOW - Distinguish DOB from report date, include unit clarification in field names, extract row-by-row.
"""


def get_alignment_verification_prompt(extracted_data: dict, page_num: int) -> str:
    """
    Generate a verification prompt that rechecks table alignment.
    Used after initial extraction to catch misaligned rows.
    """
    fields_text = "\n".join([
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
