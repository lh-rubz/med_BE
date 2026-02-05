"""VLM prompts for patient info and lab table extraction."""


def get_personal_info_prompt(idx, total_pages):
    """Prompt to extract ONLY patient personal info from specific Arabic/English grid headers."""
    return f"""You are an expert medical document digitizer.
Task: Extract PATIENT & DOCTOR information from this report (page {idx}/{total_pages}).

🚨 HEADER ORIENTATION (CRITICAL) 🚨
This report uses two side-by-side grids at the top.
- **COLUMN PATTERN**: Each grid cell typically contains a **Label on the RIGHT** and a **Value on the LEFT**.
- **READING DIRECTION**: Scan from Right-to-Left to find the Label, then look immediately to its LEFT for the Value.

1. **RIGHT GRID (Patient Info)**:
   - Row 1: "رقم المريض" (Patient ID)
   - Row 2: "اسم المريض" (Patient Name) -> The value is to the LEFT of this label.
   - Row 3: "رقم الهوية" (ID Number)
   - Row 4: "الجنس" (Gender) -> Value to the LEFT. (أنثى -> Female, ذكر -> Male).
   - Row 5: "تاريخ الميلاد" (DOB) -> Value to the LEFT.
   - Row 6: "جهة الطلب" (Requesting Entity) -> SKIP this for patient name (it's a facility/insurance).

2. **LEFT GRID (Order/Physician Info)**:
   - Row 1: "تاريخ الطلب" (Order Date) -> Value to the LEFT.
   - Row 6: "الطبيب" (Physician) -> Value to the LEFT. (Person name like جهاد العملة).

CRITICAL RULES:
1. **NO SKIP**: If a box is physically there but empty, return "".
2. **NO HALLUCINATION**: Only extract text physically present to the left of the labels.
3. **REPORT DATE**: Extract "تاريخ الطلب" as YYYY-MM-DD.

JSON OUTPUT ONLY:
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
    """Prompt to extract LAB TABLE data with the NO-SKIP sentinel protocol."""
    return f"""You are a high-precision lab data digitizer.
Task: Extract LAB DATA from this image (page {idx}/{total_pages}).

🚨 NO-SKIP SENTINEL PROTOCOL (CRITICAL) 🚨
1. **SCAN HORIZONTALLY**: Move line-by-line from top to bottom.
2. **SENTINEL VALUE**: If a row has ONLY a flag symbol (like "*" or "#") but NO numeric result, you MUST return `field_value`: "N/A".
   - **WHY?**: This prevents row-shifting. If you skip the row, the next result will be assigned to the wrong test!
   - Example row: "Red blood cell distribution width" has only a "*". Value = "N/A".
3. **EXACT ALIGNMENT**: The value in the center column must belong to the test name on the SAME horizontal line.
4. **NO TRUNCATION**: Capture the ENTIRE test name (e.g. "Red blood cell distribution width coefficient of variation").

VALIDATION:
- Count the rows. There should be approximately 23 rows.
- If a result is a number (e.g. 14.4), it MUST stay on its line.
- If a row is truly empty white space with no text or symbols, you may skip it.

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


def generate_prompt_for_page(page_text, page_idx, total_pages):
    """Generate a prompt for extracting structured medical data from a report page.
    
    Args:
        page_text: The text content of the page
        page_idx: Current page index
        total_pages: Total number of pages
        
    Returns:
        A formatted prompt string with properly escaped JSON template
    """
    return f"""
    TASK: Extract medical data from the report page.

    PAGE INDEX: {page_idx}/{total_pages}

    PAGE CONTENT:
    {page_text}

    INSTRUCTIONS:
    1. Group data by sections (e.g., Haematology Report, Biochemistry).
    2. Extract all medical fields with their values, units, and normal ranges.
    3. Extract doctor names and ensure they are complete.
    4. For each field, calculate and set "is_normal" based on the value and range.
    5. Ensure all extracted data is accurate and matches the page content.
    6. Handle both Arabic and English text correctly.

    OUTPUT FORMAT:
    {{{{
        "sections": [
            {{{{
                "section_name": "Haematology Report",
                "fields": [
                    {{{{
                        "field_name": "",
                        "field_value": "",
                        "field_unit": "",
                        "normal_range": "",
                        "is_normal": null,
                        "notes": ""
                    }}}}
                ]
            }}}}
        ],
        "doctor_names": ""
    }}}}
    """
