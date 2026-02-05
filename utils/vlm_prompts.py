"""VLM prompts for patient info and lab table extraction."""


def get_personal_info_prompt(idx, total_pages):
    """Prompt to extract ONLY patient personal info from demographic grid boxes."""
    return f"""You are an expert medical document digitizer.
Task: Extract PATIENT & DOCTOR information (page {idx}/{total_pages}).

🚨 DEMOGRAPHIC ADJACENCY RULE (CRITICAL) 🚨
Find the following labels in the top grids. For each label, extract the text found physically CLOSEST to it WITHIN THE SAME BOX.
- Labels are on the RIGHT. Values are on the LEFT.

REQUIRED FIELDS:
1. **Patient Name**: Find the label "اسم المريض". Extract the name found inside the same box.
2. **ID Number**: Find the label "رقم الهوية".
3. **Gender**: Find the label "الجنس". Convert 'أنثى' to 'Female', 'ذكر' to 'Male'.
4. **DOB**: Find the label "تاريخ الميلاد".
5. **Order Date**: Find the label "تاريخ الطلب" (usually in the Left Grid). Extract as YYYY-MM-DD.
6. **Doctor Name**: Find the label "الطبيب" (usually in the Left Grid). Extract the person's name physically next to it.
   - ⚠️ DO NOT extract "جهة الطلب" as a name.

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
    """Prompt to extract LAB TABLE data with PHANTOM SENTINEL protocol."""
    return f"""You are a high-precision lab data digitizer.
Task: Extract LAB DATA (page {idx}/{total_pages}).

🚨 PHANTOM SENTINEL PROTOCOL (CRITICAL) 🚨
1. **PHYSICAL LINE COUNT**: First, count every horizontal line of text/graphics in the table. 
2. **THE WORD "PHANTOM"**: If a horizontal line has a flag symbol (like "*" or "#") but NO numeric result, you MUST return `field_value`: "PHANTOM".
   - This word acts as a visual anchor to prevent row-shifting. NEVER skip a line.
3. **HORIZONTAL LOCK**: Trace lines from the Test Name to the Result. Only extract the value on that EXACT line.

VALIDATION:
- Count the rows. Ensure you produce an entry for every line of text in the "Test" column.
- One line = One JSON object.

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
