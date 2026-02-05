"""VLM prompts for patient info and lab table extraction."""


def get_personal_info_prompt(idx, total_pages):
    """Prompt to extract ONLY patient personal info from specific Arabic/English grid headers."""
    return f"""You are an expert medical document digitizer.
Task: Extract PATIENT & DOCTOR information from this report (page {idx}/{total_pages}).

🚨 HEADER BOX ORIENTATION (CRITICAL) 🚨
This report uses two side-by-side grids at the top.
- **INSIDE EACH BOX**: Each box is horizontally split.
- **RIGHT HALF**: Contains the Arabic Label (e.g., "اسم المريض").
- **LEFT HALF**: Contains the specific Patient Value (e.g., the Arabic name).
- **YOUR TASK**: Extract the text found in the **LEFT HALF** of each box.

1. **RIGHT GRID (Patient Info)**:
   - Box 1: "رقم المريض" (Patient ID)
   - Box 2: "اسم المريض" (Patient Name) -> Extract text from the LEFT half of this box.
   - Box 3: "رقم الهوية" (ID Number)
   - Box 4: "الجنس" (Gender) -> LEFT half. Convert 'أنثى' to 'Female', 'ذكر' to 'Male'.
   - Box 5: "تاريخ الميلاد" (DOB) -> LEFT half.
   - Box 6: "جهة الطلب" (Requesting Entity) -> SKIP this for patient name (it's a facility).

2. **LEFT GRID (Order/Physician Info)**:
   - Box 1: "تاريخ الطلب" (Order Date) -> LEFT half. Extract as YYYY-MM-DD.
   - Box 6: "الطبيب" (Physician) -> LEFT half. Extract the person's name.

CRITICAL RULES:
1. **NO SKIP**: If a box has text in the left half, you MUST extract it. 
2. **NO HALLUCINATION**: If the left half is empty white space, return "".
3. **REPORT DATE**: Extract "تاريخ الطلب" only.

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
    """Prompt to extract LAB TABLE data with Symbol Capture Lock."""
    return f"""You are a high-precision lab data digitizer.
Task: Extract LAB DATA from this image (page {idx}/{total_pages}).

🚨 SYMBOL CAPTURE LOCK (CRITICAL) 🚨
1. **SYMBOLS AS VALUES**: If a row has a flag symbol (like "*" or "#") but NO number, you MUST extract the symbol (e.g. "*") as the `field_value`. 
   - **NEVER skip a row** that contains a symbol. Each horizontal line in the "Test" column MUST have a corresponding JSON entry.
2. **STRICT SPATIAL ALIGNMENT**: Trace a straight horizontal line from the test name. The value you extract must be physically on that same line.
3. **NO TRUNCATION**: Capture names exactly as written (e.g. "Red blood cell distribution width").

VALIDATION:
- Count the rows. There are many tests in this report. Ensure you capture ALL of them sequentially.
- If you find no number and no symbol on a line, you may use "N/A" as a placeholder, but do NOT skip.

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
