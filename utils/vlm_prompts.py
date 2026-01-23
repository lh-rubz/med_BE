"""VLM prompts for patient info and lab table extraction."""


def get_personal_info_prompt(idx, total_pages):
    """Prompt to extract ONLY patient personal info; no lab values."""
    return f"""You are an expert medical document reader for Arabic and English reports.

Task: Extract ONLY PATIENT PERSONAL INFORMATION from this report image (page {idx}/{total_pages}).
Do NOT extract lab results. Handle multiple reports in one PDF: each report is separate.
Return exactly one JSON object per report, no markdown.

FIELDS TO RETURN (all strings): patient_name, patient_gender, patient_age, patient_dob, report_date, doctor_names

WHERE TO LOOK (in order):
1) Top-right header area (common in Arabic labs; RTL)
2) Top-left header area (common in English labs; LTR)
3) Center-top header
4) Side header panels
5) Top 40% of page for any standalone fields
6) Signature blocks, footer areas, referral info for doctor names

MULTI-REPORT HANDLING
- If page shows TWO separate report headers/sections, treat as two reports.
- Extract patient info only for the current report section.
- Do NOT mix data from different reports.

PATIENT NAME (MANDATORY, use strict matching)
- Labels: "اسم المريض", "المريض", "الاسم", "Patient Name", "Name", "Pt Name" (exact or near-exact label match)
- Remove labels and titles (Mr, Mrs, Dr, Prof, د., دكتور, السيد, السيدة).
- Keep original language spelling (Arabic or English).
- NOT: IDs, account numbers, medical file numbers, or single short words.
- If no match with clear label, return "".

GENDER (MANDATORY)
- Labels: "الجنس", "جنس", "النوع", "Gender", "Sex", "M/F"
- Values: If Arabic, "ذكر" -> "Male"; "أنثى" -> "Female". If English, normalize to "Male" or "Female".
- If unclear or coded, return "".

AGE / DOB
- DOB labels: "تاريخ الميلاد", "DOB", "Date of Birth", "Birth Date". Format as YYYY-MM-DD only (no time).
- Age labels: "العمر", "Age". Extract number only (e.g., "50").
- If only DOB found, leave age empty; if only age found, leave DOB empty.

REPORT DATE (DATE ONLY, no time)
- Labels: "تاريخ الطلب", "تاريخ الفحص", "تاريخ", "التاريخ", "Report Date", "Test Date", "Date", "Date/Time".
- Extract ONLY the date portion in YYYY-MM-DD format (ignore any time/timestamp).
- Example: "2025-12-31 10:00:02" -> report_date: "2025-12-31"

DOCTOR / PHYSICIAN (MANDATORY if present; search thoroughly)
- Labels: "الطبيب", "طبيب", "الطبيب المعالج", "الطبيب المسؤول", "طبيب المعالجة", "Doctor", "Physician", "Ref By", "Referred By", "Signature".
- Search: Header areas, signature blocks, footer, referral notes, any name near doctor labels.
- Remove titles (Dr., د., Prof, Prof., أ.د, الدكتور).
- If multiple doctors, join with comma (e.g., "Ahmed Salem, Fatima Ali").
- If doctor field is visible but empty/blank, return "".
- Otherwise, keep the extracted name exactly as written.

SELF-VALIDATION BEFORE RETURNING
- patient_name is a real name, not an ID/number/label. If no clear match, set to "".
- patient_gender is exactly "Male", "Female", or "".
- patient_age numeric 1-120 or "".
- report_date is YYYY-MM-DD only (no time). If timestamp present, extract date part only.
- patient_dob is YYYY-MM-DD or "".
- doctor_names filled if doctor label/signature found with a name. Empty only if no doctor visible.

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
5) Duplicate range note: If two tests share the EXACT same range but have different units (e.g., value vs %), keep both as-is. Re-check only if same unit and clearly mismatched with the row text.

HOW TO READ TABLES
- Typical headers Arabic: "الفحص", "النتيجة", "الوحدة", "المعدل الطبيعي".
- Typical headers English: "Test", "Result", "Unit", "Normal Range".
- Map by position: col1 test, col2 value, col3 unit, col4 range.

ROW-BY-ROW PROTOCOL (for EACH row)
1) Boundaries: Identify the horizontal band for THIS row only.
2) field_name: Read column 1 of THIS row.
3) field_value: Follow same line to column 2. If blank / -, --, —, *, ., N/A -> "".
   SKIP THIS ROW if field_value is empty/blank (do NOT add empty rows).
4) field_unit: Column 3. If symbol or blank -> "".
5) normal_range: Column 4. If blank / -, --, —, (-), *, symbols without numbers -> "" (do NOT invent a range).
6) is_normal: null if value or range empty/non-numeric. Else true/false by comparing numeric value to range.
7) category: Section header if present, else "".
8) notes: Any flags/notes in the row, else "".

MULTI-REPORT HANDLING IN TABLES
- If table shows TWO report sections (different headers/sections), extract each separately.
- Do NOT mix rows from different report sections into one output.
- Return separate medical_data arrays for each report.

VALIDATION BEFORE RETURN
- Every row has field_name (no empty field_names).
- Every row has field_value (skip rows with empty/blank values).
- Units are not symbols.
- If range present, it contains numbers (if range truly absent, leave empty; never invent).
- Duplicate ranges allowed when units differ or the source shows the same range; re-check only if same unit and the range clearly belongs to another row.
- Common sense: WBC ~4-11 K/uL; RBC ~4-5.5 M/uL; Hgb ~12-16 g/dL. If wildly off, re-check.
- Do NOT return medical_data entries with empty field_name or field_value. Skip those rows entirely.

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
4) Skip rows where field_name or field_value is empty (do not add empty rows to output).
5) If page has multiple reports (different sections/headers), treat each report separately.
6) Before returning, check if any two different tests share the EXACT same range AND same unit -> only re-check alignment in that case. If units differ (e.g., value vs %), keep both.

READING STEPS PER ROW
- field_name: test column in THIS row.
- field_value: result column same row; if empty/-/*/blank -> "".
  (If field_value is empty, SKIP THIS ROW entirely—do not add it to medical_data).
- field_unit: unit column same row.
- normal_range: range column same row; if empty/-/(-)/*/symbol-only -> "".
  (If the report shows an empty range, leave it empty. Do NOT invent ranges.)
- is_normal: null if value or range empty; else true/false only if numbers present.

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
