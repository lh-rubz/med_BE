"""VLM prompts for patient info and lab table extraction."""


def get_personal_info_prompt(idx, total_pages):
    """Prompt to extract ONLY patient personal info; no lab values."""
    return f"""You are an expert medical document reader for Arabic and English reports.

Task: Extract ONLY PATIENT PERSONAL INFORMATION from this report image (page {idx}/{total_pages}).
Do NOT extract lab results. Return exactly one JSON object, no markdown.

FIELDS TO RETURN (all strings): patient_name, patient_gender, patient_age, patient_dob, report_date, doctor_names

WHERE TO LOOK (in order):
1) Top-right header (common in Arabic labs)
2) Top-left header
3) Center-top header
4) Side header panels
5) Anywhere in top 40% of the page

PATIENT NAME (MANDATORY)
- Labels: "اسم المريض", "المريض", "الاسم", "مريض", "اسم", "Patient Name", "Name", "Patient", "Pt Name"
- Remove labels and titles (Mr, Mrs, Dr, د., دكتور). Keep original language spelling.
- If it looks like a label/ID/too short (<3 chars) -> return "".

GENDER (MANDATORY)
- Labels: "الجنس", "جنس", "النوع", "Gender", "Sex", "M/F"
- Normalize values: Male -> "Male"; Female -> "Female". If unclear -> "".

AGE / DOB
- DOB labels: "تاريخ الميلاد", "DOB", "Date of Birth", "Birth Date". Convert to YYYY-MM-DD if possible.
- Age labels: "العمر", "Age". Extract number only (e.g., "50").
- If only DOB found, leave age empty; if only age found, leave DOB empty.

REPORT DATE
- Labels: "تاريخ الطلب", "تاريخ الفحص", "التاريخ", "Report Date", "Test Date", "Date". Convert to YYYY-MM-DD if possible.

DOCTOR / PHYSICIAN
- Labels: "الطبيب", "طبيب", "الطبيب المعالج", "Doctor", "Physician", "Ref By".
- Remove titles (Dr., د.). Keep name only.

SELF-VALIDATION BEFORE RETURNING
- patient_name looks like a real name (not a label/ID/doctor). If doubtful, set to "".
- patient_gender is exactly "Male", "Female", or "".
- patient_age numeric 1-120 or "".
- Dates formatted YYYY-MM-DD or "".

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
1) Boundaries: Identify the horizontal band for THIS row only.
2) field_name: Read column 1 of THIS row.
3) field_value: Follow same line to column 2. If blank / -, --, —, *, ., N/A -> "".
4) field_unit: Column 3. If symbol or blank -> "".
5) normal_range: Column 4. If blank / -, --, —, (-), *, symbols without numbers -> "".
6) is_normal: null if value or range empty/non-numeric. Else true/false by comparing numeric value to range.
7) category: Section header if present, else "".
8) notes: Any flags/notes in the row, else "".

VALIDATION BEFORE RETURN
- Every row has field_name.
- Units are not symbols.
- If range present, it contains numbers.
- Check duplicate ranges across different tests; if found, re-check alignment.
- Common sense: WBC ~4-11 K/uL; RBC ~4-5.5 M/uL; Hgb ~12-16 g/dL. If wildly off, re-check.

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

RULES
1) One row at a time. Follow the horizontal line even if slanted.
2) If a cell in THIS row is empty or a symbol (-, *, .), return "" for that cell.
3) Do NOT copy values/ranges from other rows. Never invent values.
4) Before returning, check if any two different tests share the EXACT same range -> if yes, re-check alignment.

READING STEPS PER ROW
- field_name: test column in THIS row.
- field_value: result column same row; if empty/-/*/blank -> "".
- field_unit: unit column same row.
- normal_range: range column same row; if empty/-/(-)/*/symbol-only -> "".
- is_normal: null if value or range empty; else true/false only if numbers present.

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
