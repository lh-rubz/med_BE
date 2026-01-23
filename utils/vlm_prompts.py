"""VLM prompts for patient info and lab table extraction."""


def get_personal_info_prompt(idx, total_pages):
    """Prompt to extract ONLY patient personal info; no lab values."""
    return f"""You are an expert bilingual Arabic/English medical document reader.

Task: Extract ONLY PATIENT PERSONAL INFORMATION from this report image (page {idx}/{total_pages}).
Do NOT extract lab results. Handle multiple reports in one PDF: each report is separate.
Return exactly one JSON object per report, no markdown.

FIELDS TO RETURN (all strings): patient_name, patient_gender, patient_age, patient_dob, report_date, doctor_names

BILINGUAL REPORT STRUCTURE
- Arabic reports often show bilingual headers: Arabic text (RTL) on RIGHT side, English (LTR) on LEFT side.
- Labels and values appear TOGETHER in both languages.
- Search RIGHT side first for Arabic labels, then LEFT side for English equivalents.
- PREFER the field with more actual data content (not just labels).

WHERE TO LOOK (priority order):
1) TOP-RIGHT header area (Arabic side of bilingual reports)
2) TOP-LEFT header area (English side)
3) Center-top section
4) Entire header row(s) - scan left to right and right to left
5) Footer and signature areas (especially for doctor names)
6) Any standalone fields in top 40% of page

PATIENT NAME (CRITICAL - MUST FIND)
- Arabic labels: "اسم المريض", "اسم المرضى", "اسم", "Patient Name", "Name"
- Location: Header area, often in RIGHT side (Arabic) AND/OR LEFT side (English) - look for BOTH
- Extract: Text immediately following the label (right-to-left for Arabic, left-to-right for English)
- Clean: Remove titles like Dr., Mr., Mrs., Prof., د., دكتور, السيد, السيدة, أ.د
- If TWO names found (one Arabic, one English), use the LONGER/MORE COMPLETE one
- Validate: 3+ characters, looks like a person's name (NOT: "Patient", "N/A", numbers, facility names)
- CRITICAL FILTERS - SKIP these (they are NOT patient names):
  * Any text containing: "facility", "جهاز" (device), "مختبر" (lab), "مرفق", "مستشفى" (hospital), "clinic", "equipment", "laboratory", "centre", "center"
  * Single words that are place/thing names: "Ramallah", "PHC", "مختبر رمالله", facility codes/IDs
  * Abbreviations like "PHC", "Lab", "CDC", "WHO" - these are facilities, not patient names
  * If header shows "Laboratory(Ramallah PHC)" or similar - skip it, find the ACTUAL patient name nearby
- Return: Original language text or "" if uncertain

GENDER
- Arabic labels: "الجنس", "جنس", "النوع", "Gender", "Sex"
- Arabic values: "ذكر" -> "Male"; "أنثى" -> "Female"
- English values: normalize to exactly "Male" or "Female"
- Return: Only "Male", "Female", or ""

AGE / DOB
- DOB Arabic labels: "تاريخ الميلاد", "تاريخ الولادة"
- DOB English labels: "DOB", "Date of Birth"
- Age Arabic labels: "العمر"
- Age English labels: "Age"
- DOB Format: Convert to YYYY-MM-DD (handle both DD/MM/YYYY and MM/DD/YYYY formats)
- Age: Extract NUMBER only (1-120)
- Return: Both if available; one if only one available; "" if none

REPORT DATE (CRITICAL - DATE ONLY, NO TIMESTAMP)
- Arabic labels: "تاريخ الطلب", "تاريخ الفحص", "التاريخ", "تاريخ التقرير"
- English labels: "Report Date", "Test Date", "Date", "Date/Time"
- Location: Top section, often MULTIPLE locations (pick most recent/prominent)
- Extract: ONLY the DATE part in YYYY-MM-DD format
- CRITICAL: If shows "2025-12-31 10:00:02.0" or similar, EXTRACT ONLY "2025-12-31"
- Timestamp (time portion after date) must be REMOVED
- Return: YYYY-MM-DD only, or "" if not found

DOCTOR / PHYSICIAN (CRITICAL - SEARCH THOROUGHLY AND AGGRESSIVELY)
- Arabic labels: "الطبيب", "طبيب", "الطبيب المعالج", "طبيب المعالجة", "المحيل", "الطبيب المسؤول", "اسم الطبيب"
- English labels: "Doctor", "Physician", "Ref By", "Referred By", "Signature", "Doctor Name", "Treating Physician"
- Search ALL locations in this order:
  1. Header area - scan ENTIRE top section for doctor label + name
  2. RIGHT margin - Arabic side (RTL text area on right)
  3. LEFT margin - English side (LTR text area on left)
  4. BOTTOM of page - signature blocks, footer area
  5. SIDE panels - any information boxes
  6. After any line containing "doctor", "physician", "Dr.", "د.", "طبيب"
- Extract Rules:
  * If you see "Dr. [Name]" or "الطبيب [الاسم]" → Extract the [Name] part
  * If you see a label like "الطبيب:" or "Doctor:" → Extract the text IMMEDIATELY following
  * Remove ALL titles and prefixes: Dr., Dr, Prof., Prof, د., دكتور, أ.د, الدكتور, أستاذ, البروفيسور
  * Keep only the actual person name
- Multiple doctors: If signature block shows multiple names, extract first doctor only or join with comma
- Validate: Must be person name (3+ chars), not facility/lab/abbreviation
- Return: Clean name or "" if truly not found after thorough search

SELF-VALIDATION BEFORE RETURNING
- patient_name: Real person name (3+ chars, not ID/number/facility). Return "" if doubt.
- patient_gender: Exactly "Male", "Female", or "".
- patient_age: Numeric 1-120 or "".
- patient_dob: YYYY-MM-DD or "".
- report_date: YYYY-MM-DD ONLY (no time/timestamp). This field is CRITICAL.
- doctor_names: Person name or "" if not found. No titles included.

JSON OUTPUT (exactly this object, no extra text):
{{
  "patient_name": "",
  "patient_age": "",
  "patient_dob": "",
  "patient_gender": "",
  "report_date": "",
  "doctor_names": ""
}}
"""


def get_main_vlm_prompt(idx, total_pages):
    """Prompt to extract LAB TABLE data only, enforcing row alignment."""
    return f"""You are an expert medical data digitizer for Arabic and English lab reports.

You receive a medical report IMAGE (page {idx}/{total_pages}).
Primary goal: Extract LAB DATA with PERFECT ROW ALIGNMENT. Do NOT extract patient info.
Return exactly one JSON object (no markdown) with medical_data array.

CRITICAL RULES
1) Row independence: All values in one entry come from the SAME row. Never mix rows.
2) Empty is better than wrong: If uncertain, use "".
3) Language: Handle Arabic (RTL) and English (LTR). Use the clearer test name.
4) Units must be medical abbreviations, not symbols (*, -, .).
5) Duplicate range red flag: If two different tests share the EXACT same range, re-check alignment.

HOW TO READ TABLES
- Typical headers Arabic: "الفحص", "النتيجة", "الوحدة", "المعدل الطبيعي".
- Typical headers English: "Test", "Result", "Unit", "Normal Range".
- Map by position: col1 test, col2 value, col3 unit, col4 range.

ROW-BY-ROW PROTOCOL (for EACH row)
CRITICAL: Use EXTREME caution with row boundaries. Trace horizontal lines precisely.

1) Visual Row Boundary: Draw an imaginary horizontal line across THIS row ONLY. Do not look above or below.
2) field_name: Read ONLY from the far left cell of THIS row's boundary.
3) field_value: Trace straight RIGHT along THIS row's line to the NEXT column. STOP at the vertical boundary.
   - Do NOT look at other rows' values.
   - If there is NO value in this cell for THIS row, return "".
4) field_unit: Continue RIGHT along THIS row's line to the UNIT column. STOP at vertical boundary.
   - Extract the unit symbol from THIS row ONLY.
   - If blank or symbol, return "".
5) normal_range: Continue RIGHT along THIS row to the RANGE column. STOP at vertical boundary.
   - Extract the numeric range from THIS row ONLY.
   - If blank, return "" (never invent).
6) is_normal: Calculate ONLY using THIS row's value and range.
7) category: Section header for THIS row's section, else "".
8) notes: Flags in THIS row ONLY, else "".

RED FLAGS that indicate misalignment (REDO the row if found):
- field_value looks like a unit (e.g., "%" or "K/uL")
- field_unit looks like a range (e.g., "(4-11)")
- normal_range looks like a value (e.g., "5.2" or "109")
- The extracted value is physically in a different row than the test name in the image
- Units don't match the test type (e.g., "%" for RBC which should be M/uL or cells/L)

VALIDATION BEFORE RETURN
- Every row has field_name (no empty field_names).
- Every row has field_value (skip rows with empty/blank values).
- Units are not symbols and not numbers.
- If range present, it contains numbers (if range truly absent, leave empty; never invent).
- CRITICAL: Normal_range must NOT look like a value, and field_value must NOT look like a unit or range.
- Duplicate ranges allowed when units differ or the source shows the same range; re-check only if same unit and the range clearly belongs to another row.
- Common sense: WBC ~4-11 K/uL; RBC ~4-5.5 M/uL; Hgb ~12-16 g/dL. If wildly off, re-check.
- Do NOT return medical_data entries with empty field_name or field_value. Skip those rows entirely.
- If ANY extracted row looks misaligned (e.g., value is a %, unit is a range, range is a value), RE-CHECK that row's alignment before including it.

JSON OUTPUT (exactly this structure, no extra text):
{{
  "medical_data": [
    {{
      "field_name": "",
      "field_value": "",
      "field_unit": "",
      "normal_range": "",
      "is_normal": null,
      "category": "",
      "notes": ""
    }}
  ]
}}
"""


def get_table_retry_prompt(idx, total_pages):
    """Fallback prompt focused on table alignment with duplicate-range self-check."""
    return f"""You are reading a lab report image (page {idx}/{total_pages}) in Arabic or English.
Focus ONLY on table rows. Return exactly one JSON object with medical_data.

CRITICAL ALIGNMENT RULES
1) Vertical Column Boundaries: Each table has clear vertical lines separating columns.
   - Do NOT cross these boundaries.
   - Column 1 = Test Names (far left)
   - Column 2 = Values (after first vertical line)
   - Column 3 = Units (after second vertical line)
   - Column 4 = Normal Range (after third vertical line)

2) Horizontal Row Boundaries: Each row has a clear horizontal space or line separating it from adjacent rows.
   - Trace across ONE row at a time.
   - Read each column value ONLY from within that row's horizontal band.

3) One row at a time. Follow the horizontal line even if slanted.
4) If a cell in THIS row is empty or a symbol (-, *, .), return "" for that cell.
5) Do NOT copy values/ranges from other rows. Never invent values.
6) MISALIGNMENT CHECK: Before returning, verify that:
   - Each field_value is a number or qualitative text (NOT a %, unit, or range)
   - Each field_unit is a medical unit (NOT a number, range, or percentage symbol alone)
   - Each normal_range is a range like (X-Y) (NOT a number or unit)
   - If any two different tests share the EXACT same range AND same unit -> re-check alignment.

READING STEPS PER ROW
- field_name: test column in THIS row. Must be a medical test name.
- field_value: result column same row; if empty/-/*/blank -> "".
  (If field_value is empty, SKIP THIS ROW entirely—do not add it to medical_data).
- field_unit: unit column same row. Must be a medical unit abbreviation.
- normal_range: range column same row; if empty/-/(-)/*/symbol-only -> "".
  (If the report shows an empty range, leave it empty. Do NOT invent ranges.)
- is_normal: null if value or range empty; else true/false only if numbers present.

FINAL CHECK
- value should NOT contain % or unit symbols
- unit should NOT contain numbers, ranges, or value-like content
- range should NOT contain just a single number
- If this check FAILS, recheck the row alignment

OUTPUT: Only rows with non-empty field_name AND non-empty field_value.

JSON OUTPUT ONLY:
{{
  "medical_data": [
    {{
      "field_name": "",
      "field_value": "",
      "field_unit": "",
      "normal_range": "",
      "is_normal": null,
      "category": "",
      "notes": ""
    }}
  ]
}}
"""
